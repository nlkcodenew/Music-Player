import ctypes
import threading

from .audio import AudioPlayer
from .collections import Collections
from .display import DisplayController
from .input import InputState
from .logger import get_logger
from .lyrics import load_lyrics
from .reporter import queue_report, retry_pending
from .settings import Settings
from .sleep_timer import SleepTimer
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
        self.collections = Collections(paths.collections_file).load()
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
        self.status_error = False
        self.update_manifest = None
        self.update_busy = False
        self.update_lock = threading.Lock()
        self.exit_confirmation = False
        self.library_mode = "all"
        self.playlist_parent_mode = "playlists"
        self.active_playlist = ""
        self.quick_menu = False
        self.quick_menu_selection = 0
        self.sleep_timer = SleepTimer()
        self.display = DisplayController(paths)
        self.lyrics_cache = {}

    def initialize(self):
        self.display.restore()
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
                    self.status = "Update v%s available - open SELECT menu to install" % manifest["version"]
                    self.status_error = False
        except Exception as error:
            get_logger().warning("OTA check failed: %s", error)

    def _install_update(self):
        with self.update_lock:
            if self.update_busy or not self.update_manifest:
                return
            self.update_busy = True
            manifest = self.update_manifest
            self.status = "Installing update v%s..." % manifest["version"]
            self.status_error = False

        def worker():
            try:
                apply_update(self.paths, manifest)
                self.status = "Update installed. Restarting..."
                self.status_error = False
                self.running = False
            except Exception as error:
                get_logger().error("OTA installation failed: %s", error)
                self.status = "Update failed; see music-player.log"
                self.status_error = True
            finally:
                with self.update_lock:
                    self.update_busy = False

        threading.Thread(target=worker, name="ota-install", daemon=True).start()

    def _send_diagnostic(self):
        with self.update_lock:
            if self.update_busy:
                return
            self.update_busy = True
            self.status = "Sending diagnostic report..."
            self.status_error = False

        def worker():
            try:
                queue_report(self.paths, "manual_diagnostic", "Submitted with SELECT")
                if retry_pending(self.paths):
                    self.status = "Diagnostic report sent to GitHub Issues"
                else:
                    self.status = "Report saved; reconnect Wi-Fi and resend from Quick Menu"
                self.status_error = False
            except Exception as error:
                get_logger().warning("diagnostic upload failed: %s", error)
                self.status = "Report saved; upload failed"
                self.status_error = True
            finally:
                with self.update_lock:
                    self.update_busy = False

        threading.Thread(target=worker, name="diagnostic-upload", daemon=True).start()

    def cleanup(self):
        self.display.restore()
        try:
            self.settings.save()
            self.collections.save()
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
                        get_logger().info("received SDL quit event")
                        self.running = False
                    else:
                        self.input.feed(event)
                actions = self.input.poll()
                if self.display.is_off and actions:
                    self.display.restore()
                    self.status = "Screen on"
                    self.status_error = False
                else:
                    for action in actions:
                        self._handle(action)
                self._update_sleep_timer()
                self.player.update()
                if self.player.error:
                    self.status = self.player.error
                    self.status_error = True
                if self.display.is_off:
                    self.runtime.SDL_Delay(80)
                else:
                    self._render()
                    self.runtime.SDL_Delay(16)
            return 0
        finally:
            self.cleanup()

    def _handle(self, action):
        get_logger().info("input action=%s screen=%s", action, self.screen)
        if self.update_busy:
            return
        if getattr(self, "quick_menu", False):
            self._handle_quick_menu(action)
            return
        if self.exit_confirmation:
            if action == "a":
                get_logger().info("exit confirmed by user")
                self.running = False
            elif action == "b":
                get_logger().info("exit cancelled by user")
                self.exit_confirmation = False
            return
        if action == "select":
            self.quick_menu = True
            self.quick_menu_selection = 0
            return
        if action == "start":
            self.screen = "playing" if self.screen == "library" else "library"
            return
        if action == "b":
            if self.screen == "lyrics":
                self.screen = "playing"
            elif self.screen == "playing":
                self.screen = "library"
            elif self.library_mode == "playlist_tracks":
                self.library_mode = self.playlist_parent_mode
                self.active_playlist = ""
                self.selection = 0
                self.scroll = 0
            else:
                self.exit_confirmation = True
            return
        if action == "l1":
            self.player.advance(False)
            if self.screen == "library":
                self.screen = "playing"
            return
        if action == "r1":
            self.player.advance(True)
            if self.screen == "library":
                self.screen = "playing"
            return
        if action == "l2":
            self.player.set_volume(int(self.settings.get("volume")) - 5)
            return
        if action == "r2":
            self.player.set_volume(int(self.settings.get("volume")) + 5)
            return
        if action == "x":
            if self.screen == "lyrics":
                self._cycle_lyrics_translation()
            else:
                self._toggle_favorite()
            return
        if action == "y":
            if self.screen == "library":
                self._cycle_library_mode()
            else:
                values = ("off", "all", "one")
                current = values.index(self.settings.get("repeat"))
                self.settings.set("repeat", values[(current + 1) % len(values)])
            return
        if self.screen == "library":
            entries = self._library_entries()
            if action == "up" and entries:
                self.selection = max(0, self.selection - 1)
            elif action == "down" and entries:
                self.selection = min(len(entries) - 1, self.selection + 1)
            elif action == "left" and entries:
                self.selection = max(0, self.selection - self.visible_rows())
            elif action == "right" and entries:
                self.selection = min(len(entries) - 1, self.selection + self.visible_rows())
            elif action == "a" and entries:
                if self.library_mode in ("playlists", "favorite_playlists"):
                    self.active_playlist = entries[self.selection]
                    self.playlist_parent_mode = self.library_mode
                    self.library_mode = "playlist_tracks"
                    self.selection = 0
                    self.scroll = 0
                else:
                    track = entries[self.selection]
                    self.player.tracks = list(entries)
                    if self.player.play(self.selection):
                        self.screen = "playing"
        else:
            if action == "a":
                paused = self.player.toggle_pause()
                self.status = "Paused" if paused else "Playing"
                self.status_error = False
            elif action == "left":
                self.player.seek(-10)
            elif action == "right":
                self.player.seek(10)

    def _quick_menu_entries(self):
        entries = [
            ("lyrics", "Lyrics"),
            ("sleep", "Sleep Timer: %s" % self.sleep_timer.label),
            ("screen_off", "Screen-off Playback"),
        ]
        if self.update_manifest:
            entries.append(("update", "Install Update v%s" % self.update_manifest["version"]))
        entries.extend((("diagnostic", "Send Diagnostic"), ("close", "Close Menu")))
        return entries

    def _handle_quick_menu(self, action):
        entries = self._quick_menu_entries()
        if action in ("b", "select"):
            self.quick_menu = False
            return
        if action == "up":
            self.quick_menu_selection = (self.quick_menu_selection - 1) % len(entries)
            return
        if action == "down":
            self.quick_menu_selection = (self.quick_menu_selection + 1) % len(entries)
            return
        selected = entries[self.quick_menu_selection][0]
        if selected == "sleep" and action in ("left", "right"):
            self._cycle_sleep_timer(-1 if action == "left" else 1)
            return
        if action != "a":
            return
        if selected == "lyrics":
            if not self.player.current:
                self.status = "Play a song before opening Lyrics"
                self.status_error = True
            else:
                self.screen = "lyrics"
                self.status = ""
            self.quick_menu = False
        elif selected == "sleep":
            self._cycle_sleep_timer(1)
        elif selected == "screen_off":
            self.quick_menu = False
            if not self.player.current:
                self.status = "Play a song before turning the screen off"
                self.status_error = True
            elif not self.display.screen_off():
                self.status = "Screen-off playback is unavailable on this firmware"
                self.status_error = True
        elif selected == "update":
            self.quick_menu = False
            self._install_update()
        elif selected == "diagnostic":
            self.quick_menu = False
            self._send_diagnostic()
        else:
            self.quick_menu = False

    def _cycle_sleep_timer(self, step):
        track = self.player.current
        next_index = (self.sleep_timer.preset_index + step) % 7
        if next_index == 6 and not track:
            self.status = "Play a song before choosing End of track"
            self.status_error = True
            return
        label = self.sleep_timer.set(next_index, track.path if track else "")
        self.status = "Sleep Timer: %s" % label
        self.status_error = False
        get_logger().info("sleep timer set=%s", label)

    def _update_sleep_timer(self):
        if not self.sleep_timer.active or not self.player:
            return
        track = self.player.current
        paused = bool(self.player.music and self.runtime.Mix_PausedMusic())
        playing = bool(self.player.music and self.runtime.Mix_PlayingMusic())
        if self.sleep_timer.expired(track.path if track else "", playing, paused):
            label = self.sleep_timer.label
            self.sleep_timer.cancel()
            self.player.fade_stop()
            self.status = "Sleep Timer finished (%s)" % label
            self.status_error = False

    def _lyrics_document(self):
        track = self.player.current
        if not track:
            return None
        if track.path not in self.lyrics_cache:
            try:
                self.lyrics_cache[track.path] = load_lyrics(track.path)
                lyrics = self.lyrics_cache[track.path]
                get_logger().info(
                    "lyrics loaded lines=%d translations=%d",
                    len(lyrics.lines), len(lyrics.languages),
                )
            except OSError as error:
                get_logger().warning("cannot load lyrics: %s", error)
                self.lyrics_cache[track.path] = None
        return self.lyrics_cache[track.path]

    def _cycle_lyrics_translation(self):
        lyrics = self._lyrics_document()
        if not lyrics or not lyrics.languages:
            self.status = "No translation file found"
            self.status_error = True
            return
        values = [""] + lyrics.languages
        current = self.settings.get("lyrics_language")
        index = values.index(current) if current in values else 0
        language = values[(index + 1) % len(values)]
        self.settings.set("lyrics_language", language)
        self.status = "Translation: %s" % (language.upper() if language else "Off")
        self.status_error = False
        get_logger().info("lyrics translation=%s", language or "off")

    def _library_entries(self):
        if self.library_mode == "favorites":
            return [track for track in self.tracks if self.collections.is_track_favorite(track.path)]
        if self.library_mode == "playlists":
            return self.collections.playlists(self.tracks)
        if self.library_mode == "favorite_playlists":
            return self.collections.playlists(self.tracks, favorites_only=True)
        if self.library_mode == "playlist_tracks":
            return [track for track in self.tracks if track.folder == self.active_playlist]
        return self.tracks

    def _cycle_library_mode(self):
        modes = ("all", "favorites", "playlists", "favorite_playlists")
        current = self.playlist_parent_mode if self.library_mode == "playlist_tracks" else self.library_mode
        self.library_mode = modes[(modes.index(current) + 1) % len(modes)]
        self.active_playlist = ""
        self.selection = 0
        self.scroll = 0
        get_logger().info("library mode=%s", self.library_mode)

    def _toggle_favorite(self):
        if self.screen == "playing":
            track = self.player.current
            if not track:
                return
            enabled = self.collections.toggle_track(track.path)
            self.status = "Added to Favorite Songs" if enabled else "Removed from Favorite Songs"
            self.status_error = False
        else:
            entries = self._library_entries()
            if not entries:
                return
            self.selection = min(self.selection, len(entries) - 1)
            selected = entries[self.selection]
            if self.library_mode in ("playlists", "favorite_playlists"):
                enabled = self.collections.toggle_playlist(selected)
                self.status = "Favorite playlist added" if enabled else "Favorite playlist removed"
            else:
                enabled = self.collections.toggle_track(selected.path)
                self.status = "Favorite song added" if enabled else "Favorite song removed"
        self.collections.save()
        self.status_error = False
        entries = self._library_entries()
        self.selection = min(self.selection, max(0, len(entries) - 1))

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
        self.text(self._screen_title(), 28, 15, "title")
        subtitle = "%s | %d tracks" % (self.paths.os_name.upper(), len(self._library_tracks()))
        subtitle_width = self.measure(subtitle, "small")[0]
        self.text(subtitle, self.width - 28 - subtitle_width, 23, "small", self.MUTED)
        if self.screen == "library":
            self._render_library()
        elif self.screen == "lyrics":
            self._render_lyrics()
        else:
            self._render_playing()
        self._render_footer()
        if self.exit_confirmation:
            self._render_exit_confirmation()
        if self.quick_menu:
            self._render_quick_menu()
        self.runtime.SDL_RenderPresent(self.renderer)

    def _render_library(self):
        entries = self._library_entries()
        if not entries:
            message = {
                "favorites": "No favorite songs yet",
                "playlists": "No playlist folders found",
                "favorite_playlists": "No favorite playlists yet",
                "playlist_tracks": "This playlist is empty",
            }.get(self.library_mode, "No supported music found")
            self.text(message, self.width // 2, self.height // 2 - 35, "hero", center=True)
            detail = "Press Y to change view" if self.tracks else self.paths.music_dir
            self.text(detail, self.width // 2, self.height // 2 + 25, "small", self.MUTED, center=True)
            return
        rows = self.visible_rows()
        self.scroll = min(self.scroll, self.selection)
        if self.selection >= self.scroll + rows:
            self.scroll = self.selection - rows + 1
        y = 82
        for index in range(self.scroll, min(len(entries), self.scroll + rows)):
            selected = index == self.selection
            if selected:
                self.fill(18, y - 5, self.width - 36, 48, self.ACCENT)
            color = self.BG if selected else self.TEXT
            folder_color = self.BG if selected else self.MUTED
            entry = entries[index]
            if self.library_mode in ("playlists", "favorite_playlists"):
                favorite = self.collections.is_playlist_favorite(entry)
                title = ("* " if favorite else "") + entry
                count = len([track for track in self.tracks if track.folder == entry])
                detail = "%d tracks" % count
            else:
                favorite = self.collections.is_track_favorite(entry.path)
                title = ("* " if favorite else "") + entry.title
                detail = entry.folder
            self.text(self.ellipsize(title, self.width - 330), 32, y, "body", color)
            detail = self.ellipsize(detail, 245, "small")
            detail_width = self.measure(detail, "small")[0]
            self.text(detail, self.width - 32 - detail_width, y + 5, "small", folder_color)
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
        button = "A  RESUME" if self.runtime.Mix_PausedMusic() else "A  PAUSE"
        button_width = 210
        self.fill(self.width // 2 - button_width // 2, center_y + 145, button_width, 48, self.ACCENT)
        self.text(button, self.width // 2, center_y + 154, "body", self.BG, center=True)

    def _render_lyrics(self):
        track = self.player.current
        if not track:
            self.text("Nothing is playing", self.width // 2, self.height // 2, "hero", center=True)
            return
        self.text(self.ellipsize(track.title, self.width - 100, "title"), self.width // 2, 86, "title", center=True)
        lyrics = self._lyrics_document()
        if not lyrics or not lyrics.lines:
            self.text("No synchronized lyrics found", self.width // 2, self.height // 2 - 35, "hero", center=True)
            self.text("Add Song.lrc next to Song.mp3", self.width // 2, self.height // 2 + 25, "body", self.MUTED, center=True)
            return
        position = self.player.position()
        current = lyrics.current_index(position)
        focus = max(0, current)
        start = max(0, min(focus - 2, max(0, len(lyrics.lines) - 5)))
        language = self.settings.get("lyrics_language")
        if language not in lyrics.languages:
            language = ""
        y = 155
        for index in range(start, min(len(lyrics.lines), start + 5)):
            line = lyrics.lines[index]
            active = index == current
            font = "title" if active else "body"
            color = self.ACCENT if active else self.MUTED
            self.text(self.ellipsize(line.text or "...", self.width - 100, font), self.width // 2, y, font, color, center=True)
            translation = lyrics.translation(index, language)
            if translation:
                self.text(self.ellipsize(translation, self.width - 120, "small"), self.width // 2, y + 39, "small", self.TEXT if active else self.MUTED, center=True)
                y += 82
            else:
                y += 65

    def _render_quick_menu(self):
        entries = self._quick_menu_entries()
        width = min(680, self.width - 80)
        height = 120 + len(entries) * 58
        x = (self.width - width) // 2
        y = (self.height - height) // 2
        self.fill(x - 4, y - 4, width + 8, height + 8, self.ACCENT)
        self.fill(x, y, width, height, self.PANEL)
        self.text("QUICK MENU", self.width // 2, y + 28, "title", center=True)
        for index, (_, label) in enumerate(entries):
            row_y = y + 86 + index * 58
            selected = index == self.quick_menu_selection
            if selected:
                self.fill(x + 24, row_y - 8, width - 48, 48, self.ACCENT)
            color = self.BG if selected else self.TEXT
            self.text(self.ellipsize(label, width - 90), x + 45, row_y, "body", color)

    def _render_footer(self):
        footer_height = 62
        y = self.height - footer_height
        self.fill(0, y, self.width, footer_height, self.PANEL)
        state = "SHUFFLE %s   REPEAT %s   VOL %d%%" % (
            "ON" if self.settings.get("shuffle") else "OFF",
            str(self.settings.get("repeat")).upper(), self.settings.get("volume"),
        )
        if self.sleep_timer.active:
            state += "   SLEEP %s" % self.sleep_timer.status()
        self.text(state, 24, y + 18, "small", self.MUTED)
        if self.screen == "library":
            hint = "A OPEN/PLAY  X FAVORITE  Y VIEW"
        elif self.screen == "lyrics":
            hint = "A PAUSE  X TRANSLATION  SELECT MENU"
        else:
            hint = "A PAUSE/RESUME  X FAVORITE  SELECT MENU"
        hint_width = self.measure(hint, "small")[0]
        self.text(hint, self.width - 24 - hint_width, y + 18, "small")
        if self.status:
            color = self.ERROR if self.status_error else self.ACCENT
            self.fill(0, y - 38, self.width, 38, color)
            text_color = self.TEXT if self.status_error else self.BG
            self.text(self.ellipsize(self.status, self.width - 40, "small"), 20, y - 31, "small", text_color)

    def _render_exit_confirmation(self):
        width = min(620, self.width - 80)
        height = 190
        x = (self.width - width) // 2
        y = (self.height - height) // 2
        self.fill(x - 4, y - 4, width + 8, height + 8, self.ACCENT)
        self.fill(x, y, width, height, self.PANEL)
        self.text("Exit Music Player?", self.width // 2, y + 38, "hero", center=True)
        self.text("A  EXIT", self.width // 2 - 120, y + 120, "body", self.ACCENT, center=True)
        self.text("B  CANCEL", self.width // 2 + 120, y + 120, "body", center=True)

    def _screen_title(self):
        if self.screen == "playing":
            return "NOW PLAYING"
        if self.screen == "lyrics":
            return "LYRICS"
        return {
            "all": "ALL SONGS",
            "favorites": "FAVORITE SONGS",
            "playlists": "PLAYLISTS",
            "favorite_playlists": "FAVORITE PLAYLISTS",
            "playlist_tracks": self.active_playlist.upper(),
        }.get(self.library_mode, "LIBRARY")

    def _library_tracks(self):
        entries = self._library_entries()
        if self.library_mode in ("playlists", "favorite_playlists"):
            names = set(entries)
            return [track for track in self.tracks if track.folder in names]
        return entries

    @staticmethod
    def _format_time(seconds):
        seconds = max(0, int(seconds))
        return "%d:%02d" % (seconds // 60, seconds % 60)
