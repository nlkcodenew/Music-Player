import ctypes
import threading

from .audio import AudioPlayer
from .input import InputState
from .logger import get_logger
from .reporter import queue_report
from .settings import Settings
from .sdl_runtime import (
    SDL_Color,
    SDL_DisplayMode,
    SDL_Event,
    SDL_INIT_AUDIO,
    SDL_INIT_GAMECONTROLLER,
    SDL_INIT_JOYSTICK,
    SDL_INIT_VIDEO,
    SDL_QUIT,
    SDL_Rect,
    SDL_RENDERER_ACCELERATED,
    SDL_RENDERER_PRESENTVSYNC,
    SDL_RENDERER_SOFTWARE,
    SDL_WINDOW_FULLSCREEN,
    SDL_WINDOW_SHOWN,
    SDLRuntime,
    font_candidates,
)
from .updater import apply_update, fetch_manifest, update_available


class MusicPlayerApp:
    BG = (13, 17, 28, 255)
    PANEL = (20, 28, 46, 255)
    ACCENT = (0, 230, 170, 255)
    TEXT = (242, 245, 250, 255)
    MUTED = (150, 160, 180, 255)
    ERROR = (105, 32, 42, 255)

    def __init__(self, paths, tracks):
        self.paths = paths
        self.tracks = tracks
        self.settings = Settings(paths.settings_file).load()
        self.runtime = None
        self.window = None
        self.renderer = None
        self.fonts = {}
        self.width = 1024
        self.height = 768
        self.running = True
        self.screen = "library"
        self.selection = 0
        self.scroll = 0
        self.input = InputState()
        self.player = None
        self.status = ""
        self.update_manifest = None
        self.update_busy = False
        self.update_lock = threading.Lock()

    def initialize(self):
        self.runtime = SDLRuntime(self.paths)
        flags = SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER
        if self.runtime.SDL_Init(flags) != 0:
            raise RuntimeError("SDL initialization failed: %s" % self.runtime.error())
        if self.runtime.TTF_Init() != 0:
            raise RuntimeError("SDL_ttf initialization failed: %s" % self.runtime.error())
        mode = SDL_DisplayMode()
        if self.runtime.SDL_GetCurrentDisplayMode(0, ctypes.byref(mode)) == 0:
            if mode.w >= 320 and mode.h >= 240:
                self.width, self.height = mode.w, mode.h
        self.window = self.runtime.SDL_CreateWindow(
            b"Portable Music Player", 0, 0, self.width, self.height,
            SDL_WINDOW_SHOWN | SDL_WINDOW_FULLSCREEN,
        )
        if not self.window:
            self.window = self.runtime.SDL_CreateWindow(
                b"Portable Music Player", 0, 0, self.width, self.height, SDL_WINDOW_SHOWN
            )
        if not self.window:
            raise RuntimeError("window creation failed: %s" % self.runtime.error())
        self.renderer = self.runtime.SDL_CreateRenderer(
            self.window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC
        )
        if not self.renderer:
            self.renderer = self.runtime.SDL_CreateRenderer(self.window, -1, SDL_RENDERER_SOFTWARE)
        if not self.renderer:
            raise RuntimeError("renderer creation failed: %s" % self.runtime.error())
        self.runtime.open_inputs()
        self._load_fonts()
        self.player = AudioPlayer(self.runtime, self.tracks, self.settings)
        self.player.initialize()
        self._restore_selection()
        if self.settings.get("auto_update"):
            threading.Thread(target=self._check_update, name="ota-check", daemon=True).start()

    def _load_fonts(self):
        candidates = font_candidates(self.paths)
        if not candidates:
            raise RuntimeError("no TrueType font found on this firmware")
        font_path = candidates[0].encode("utf-8")
        scale = max(0.75, min(self.width / 1024.0, self.height / 768.0))
        for name, size in (("small", 20), ("body", 27), ("title", 36), ("hero", 44)):
            font = self.runtime.TTF_OpenFont(font_path, max(14, round(size * scale)))
            if not font:
                raise RuntimeError("cannot load font %s" % candidates[0])
            self.fonts[name] = font
        get_logger().info("font loaded from %s", candidates[0])

    def _restore_selection(self):
        last_track = self.settings.get("last_track")
        for index, track in enumerate(self.tracks):
            if track.path == last_track:
                self.selection = index
                break

    def _check_update(self):
        try:
            manifest = fetch_manifest(self.paths)
            if update_available(manifest) and manifest.get("version") != self.settings.get("skipped_version"):
                with self.update_lock:
                    self.update_manifest = manifest
                    self.status = "Update v%s available - press SELECT to install" % manifest["version"]
        except Exception as error:
            get_logger().warning("OTA check failed: %s", error)
            queue_report(self.paths, "ota_manifest_failed", str(error))

    def _install_update(self):
        with self.update_lock:
            if self.update_busy or not self.update_manifest:
                return
            self.update_busy = True
            manifest = self.update_manifest
            self.status = "Installing update v%s..." % manifest["version"]

        def worker():
            try:
                apply_update(self.paths, manifest)
                self.status = "Update installed. Restarting..."
                self.running = False
            except Exception as error:
                get_logger().error("OTA installation failed: %s", error)
                self.status = "Update failed; see music-player.log"
            finally:
                with self.update_lock:
                    self.update_busy = False

        threading.Thread(target=worker, name="ota-install", daemon=True).start()

    def cleanup(self):
        try:
            self.settings.save()
        except OSError as error:
            get_logger().error("cannot save settings: %s", error)
            queue_report(self.paths, "settings_save_failed", str(error))
        if self.player:
            self.player.close()
        if self.runtime:
            self.runtime.close_inputs()
            for font in self.fonts.values():
                self.runtime.TTF_CloseFont(font)
            if self.renderer:
                self.runtime.SDL_DestroyRenderer(self.renderer)
            if self.window:
                self.runtime.SDL_DestroyWindow(self.window)
            self.runtime.TTF_Quit()
            self.runtime.SDL_Quit()

    def run(self):
        try:
            self.initialize()
            event = SDL_Event()
            while self.running:
                while self.runtime.SDL_PollEvent(ctypes.byref(event)):
                    if event.type == SDL_QUIT:
                        self.running = False
                    else:
                        self.input.feed(event)
                for action in self.input.poll():
                    self._handle(action)
                self.player.update()
                if self.player.error:
                    self.status = self.player.error
                self._render()
                self.runtime.SDL_Delay(16)
            return 0
        finally:
            self.cleanup()

    def _handle(self, action):
        if self.update_busy:
            return
        if action == "select" and self.update_manifest:
            self._install_update()
            return
        if action == "start":
            self.screen = "playing" if self.screen == "library" else "library"
            return
        if action == "b":
            if self.screen == "playing":
                self.screen = "library"
            else:
                self.running = False
            return
        if action == "l1":
            self.player.advance(False)
            self.screen = "playing"
            return
        if action == "r1":
            self.player.advance(True)
            self.screen = "playing"
            return
        if action == "l2":
            self.player.set_volume(int(self.settings.get("volume")) - 5)
            return
        if action == "r2":
            self.player.set_volume(int(self.settings.get("volume")) + 5)
            return
        if action == "x":
            self.settings.set("shuffle", not self.settings.get("shuffle"))
            return
        if action == "y":
            values = ("off", "all", "one")
            current = values.index(self.settings.get("repeat"))
            self.settings.set("repeat", values[(current + 1) % len(values)])
            return
        if self.screen == "library":
            if action == "up" and self.tracks:
                self.selection = max(0, self.selection - 1)
            elif action == "down" and self.tracks:
                self.selection = min(len(self.tracks) - 1, self.selection + 1)
            elif action == "left" and self.tracks:
                self.selection = max(0, self.selection - self.visible_rows())
            elif action == "right" and self.tracks:
                self.selection = min(len(self.tracks) - 1, self.selection + self.visible_rows())
            elif action == "a" and self.tracks and self.player.play(self.selection):
                self.screen = "playing"
        else:
            if action == "a":
                self.player.toggle_pause()
            elif action == "left":
                self.player.seek(-10)
            elif action == "right":
                self.player.seek(10)

    def visible_rows(self):
        return max(3, (self.height - 160) // 52)

    def fill(self, x, y, width, height, color):
        self.runtime.SDL_SetRenderDrawColor(self.renderer, *color)
        rect = SDL_Rect(int(x), int(y), int(width), int(height))
        self.runtime.SDL_RenderFillRect(self.renderer, ctypes.byref(rect))

    def measure(self, text, font_name="body"):
        width = ctypes.c_int()
        height = ctypes.c_int()
        self.runtime.TTF_SizeUTF8(
            self.fonts[font_name], text.encode("utf-8", "replace"),
            ctypes.byref(width), ctypes.byref(height),
        )
        return width.value, height.value

    def ellipsize(self, text, max_width, font_name="body"):
        if self.measure(text, font_name)[0] <= max_width:
            return text
        value = text
        while value and self.measure(value + "...", font_name)[0] > max_width:
            value = value[:-1]
        return value + "..."

    def text(self, text, x, y, font_name="body", color=None, center=False):
        color = color or self.TEXT
        surface = self.runtime.TTF_RenderUTF8_Blended(
            self.fonts[font_name], text.encode("utf-8", "replace"), SDL_Color(*color)
        )
        if not surface:
            return
        texture = self.runtime.SDL_CreateTextureFromSurface(self.renderer, surface)
        if texture:
            width, height = surface.contents.w, surface.contents.h
            if center:
                x -= width // 2
            target = SDL_Rect(int(x), int(y), width, height)
            self.runtime.SDL_RenderCopy(self.renderer, texture, None, ctypes.byref(target))
            self.runtime.SDL_DestroyTexture(texture)
        self.runtime.SDL_FreeSurface(surface)

    def _render(self):
        self.runtime.SDL_SetRenderDrawColor(self.renderer, *self.BG)
        self.runtime.SDL_RenderClear(self.renderer)
        self.fill(0, 0, self.width, 68, self.PANEL)
        self.fill(0, 66, self.width, 2, self.ACCENT)
        self.text("LIBRARY" if self.screen == "library" else "NOW PLAYING", 28, 15, "title")
        subtitle = "%s | %d tracks" % (self.paths.os_name.upper(), len(self.tracks))
        subtitle_width = self.measure(subtitle, "small")[0]
        self.text(subtitle, self.width - 28 - subtitle_width, 23, "small", self.MUTED)
        if self.screen == "library":
            self._render_library()
        else:
            self._render_playing()
        self._render_footer()
        self.runtime.SDL_RenderPresent(self.renderer)

    def _render_library(self):
        if not self.tracks:
            self.text("No supported music found", self.width // 2, self.height // 2 - 35, "hero", center=True)
            self.text(self.paths.music_dir, self.width // 2, self.height // 2 + 25, "small", self.MUTED, center=True)
            return
        rows = self.visible_rows()
        self.scroll = min(self.scroll, self.selection)
        if self.selection >= self.scroll + rows:
            self.scroll = self.selection - rows + 1
        y = 82
        for index in range(self.scroll, min(len(self.tracks), self.scroll + rows)):
            selected = index == self.selection
            if selected:
                self.fill(18, y - 5, self.width - 36, 48, self.ACCENT)
            track = self.tracks[index]
            color = self.BG if selected else self.TEXT
            folder_color = self.BG if selected else self.MUTED
            self.text(self.ellipsize(track.title, self.width - 330), 32, y, "body", color)
            folder = self.ellipsize(track.folder, 245, "small")
            folder_width = self.measure(folder, "small")[0]
            self.text(folder, self.width - 32 - folder_width, y + 5, "small", folder_color)
            y += 52

    def _render_playing(self):
        track = self.player.current
        if not track:
            self.text("Nothing is playing", self.width // 2, self.height // 2 - 25, "hero", center=True)
            return
        center_y = self.height // 2
        self.text(self.ellipsize(track.title, self.width - 100, "hero"), self.width // 2, center_y - 115, "hero", center=True)
        self.text(track.folder, self.width // 2, center_y - 55, "body", self.MUTED, center=True)
        position = self.player.position()
        duration = self.player.duration()
        progress_width = self.width - 160
        self.fill(80, center_y + 25, progress_width, 10, self.PANEL)
        ratio = min(1.0, position / duration) if duration > 0 else 0.0
        self.fill(80, center_y + 25, progress_width * ratio, 10, self.ACCENT)
        elapsed = self._format_time(position)
        total = self._format_time(duration) if duration else "--:--"
        self.text("%s / %s" % (elapsed, total), self.width // 2, center_y + 55, "body", center=True)
        state = "PAUSED" if self.runtime.Mix_PausedMusic() else "PLAYING"
        self.text(state, self.width // 2, center_y + 105, "small", self.ACCENT, center=True)

    def _render_footer(self):
        footer_height = 62
        y = self.height - footer_height
        self.fill(0, y, self.width, footer_height, self.PANEL)
        state = "SHUFFLE %s   REPEAT %s   VOL %d%%" % (
            "ON" if self.settings.get("shuffle") else "OFF",
            str(self.settings.get("repeat")).upper(), self.settings.get("volume"),
        )
        self.text(state, 24, y + 18, "small", self.MUTED)
        hint = "A PLAY  B BACK  X SHUFFLE  Y REPEAT"
        hint_width = self.measure(hint, "small")[0]
        self.text(hint, self.width - 24 - hint_width, y + 18, "small")
        if self.status:
            color = self.ACCENT if self.update_manifest else self.ERROR
            self.fill(0, y - 38, self.width, 38, color)
            text_color = self.BG if self.update_manifest else self.TEXT
            self.text(self.ellipsize(self.status, self.width - 40, "small"), 20, y - 31, "small", text_color)

    @staticmethod
    def _format_time(seconds):
        seconds = max(0, int(seconds))
        return "%d:%02d" % (seconds // 60, seconds % 60)

