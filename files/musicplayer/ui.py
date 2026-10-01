import ctypes
import threading

from . import APP_VERSION
from .audio import AudioPlayer
from .audio_output import OUTPUT_MODES, output_mode_label
from .background import BACKGROUND_EXIT, load_resume, save_background_session
from .collections import Collections
from .display import DisplayController
from .input import InputState
from .identity import installation_id
from .audio_format import format_rate, format_spec, track_audio_info
from .leds import LedController
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
    BG = (6, 7, 11, 255)
    PANEL = (15, 17, 23, 255)
    ACCENT = (222, 75, 50, 255)
    ACCENT_DIM = (120, 40, 30, 255)
    TEXT = (238, 232, 222, 255)
    MUTED = (140, 135, 125, 255)
    SPEC = (255, 140, 40, 255)
    GOLD = (255, 195, 60, 255)
    ERROR = (105, 32, 42, 255)

    def __init__(self, paths, tracks):
        self.paths = paths
        self.tracks = tracks
        self.settings = Settings(paths.settings_file).load()
        self.install_id = installation_id(paths)
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
        self.quick_menu_page = "main"
        self.sleep_timer = SleepTimer()
        self.display = DisplayController(paths)
        self.lyrics_cache = {}
        self.exit_code = 0
        self.leds = None
        self._visual_state = ([0.0] * 14, 0.0, False)

    def initialize(self):
        self.display.restore()
        self.display.prepare()
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
        try:
            self.leds = LedController()
        except Exception as error:
            get_logger().warning("LED controller unavailable: %s", error)
            self.leds = None
        if self.leds is not None:
            try:
                if self.leds.suspend_engine():
                    get_logger().info("LED effect engine suspended for music visuals")
            except Exception as error:
                get_logger().warning("cannot suspend LED engine: %s", error)
        if self.player.output_warning:
            self.status = self.player.output_warning
            self.status_error = True
        self._restore_selection()
        self._resume_background_playback()
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

    def _resume_background_playback(self):
        resume = load_resume(self.paths)
        if not resume or not self.player.audio_ready:
            return
        track_path = resume.get("track_path", "")
        index = next(
            (index for index, track in enumerate(self.player.tracks) if track.path == track_path),
            -1,
        )
        if index < 0 or not self.player.play(index):
            get_logger().warning("cannot resume background track=%r", track_path)
            return
        position = max(0.0, float(resume.get("position", 0.0)))
        if position >= 1.0 and not self.player.seek(position - self.player.position()):
            get_logger().warning("cannot resume background position=%.3f", position)
        if resume.get("paused"):
            self.player.toggle_pause()
        sleep_value = resume.get("sleep_timer")
        if isinstance(sleep_value, dict):
            preset = int(sleep_value.get("preset", 0))
            if preset == 6:
                self.sleep_timer.set(preset, sleep_value.get("track_path", ""))
            elif 0 < preset < 6:
                self.sleep_timer.preset_index = preset
                self.sleep_timer.deadline = self.sleep_timer.clock() + max(
                    0, int(sleep_value.get("remaining", 0))
                )
        self.screen = "playing"
        self.status = "Background playback resumed"
        get_logger().info(
            "background playback resumed index=%d position=%.3f paused=%s",
            index, position, bool(resume.get("paused")),
        )

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
                get_logger().info(
                    "manual diagnostic requested screen=%s track=%r position=%.3f duration=%.3f "
                    "repeat=%s shuffle=%s background_exit=%s",
                    self.screen, self.player.current.title if self.player.current else "",
                    self.player.position(), self.player.duration(), self.settings.get("repeat"),
                    self.settings.get("shuffle"), self.exit_code == BACKGROUND_EXIT,
                )
                queue_report(
                    self.paths, "manual_diagnostic", "Submitted with SELECT", unique=True
                )
                if retry_pending(self.paths, force=True):
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
        if self.leds is not None:
            try:
                self.leds.restore_engine()
            except Exception as error:
                get_logger().warning("cannot restore LED engine: %s", error)
            try:
                self.leds.clear()
            except Exception:
                pass
            self.leds = None
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
                self._update_visuals()
                if self.player.error:
                    self.status = self.player.error
                    self.status_error = True
                if self.display.is_off:
                    self.runtime.SDL_Delay(80)
                else:
                    self._render()
                    self.runtime.SDL_Delay(16)
            return self.exit_code
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
            self.quick_menu_page = "main"
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
                repeat = values[(current + 1) % len(values)]
                self.settings.set("repeat", repeat)
                self.status = "Repeat: %s" % repeat.title()
                self.status_error = False
                get_logger().info("repeat mode changed=%s", repeat)
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
        if getattr(self, "quick_menu_page", "main") == "equalizer":
            bass, mid, treble = self.player.equalizer.gains
            return [
                ("eq_preset", "Preset: %s" % self.player.equalizer.preset),
                ("eq_bass", "Bass: %+d dB" % bass),
                ("eq_mid", "Mid: %+d dB" % mid),
                ("eq_treble", "Treble: %+d dB" % treble),
                ("eq_back", "Back"),
            ]
        entries = [
            ("lyrics", "Lyrics"),
            ("equalizer", "Equalizer: %s" % self.player.equalizer.preset),
            (
                "audio_output",
                "Audio Output: %s" % output_mode_label(self.settings.get("audio_output")),
            ),
            ("led_mode", "LED Mode: %s" % str(self.settings.get("led_mode")).title()),
            ("spectrum", "Spectrum: %s" % ("On" if self.settings.get("spectrum") else "Off")),
            ("sleep", "Sleep Timer: %s" % self.sleep_timer.label),
            ("screen_off", "Screen-off Playback"),
            ("background", "Background Playback (Return to OS)"),
            (
                "auto_report",
                "Auto-report Errors: %s" % (
                    "On" if self.settings.get("auto_report_errors") else "Off"
                ),
            ),
        ]
        if self.update_manifest:
            entries.append(("update", "Install Update v%s" % self.update_manifest["version"]))
        entries.extend((("diagnostic", "Send Diagnostic"), ("close", "Close Menu")))
        return entries

    def _handle_quick_menu(self, action):
        entries = self._quick_menu_entries()
        if action == "select":
            self.quick_menu = False
            return
        if action == "b":
            if getattr(self, "quick_menu_page", "main") == "equalizer":
                self.quick_menu_page = "main"
                self.quick_menu_selection = 1
            else:
                self.quick_menu = False
            return
        if action == "up":
            self.quick_menu_selection = (self.quick_menu_selection - 1) % len(entries)
            return
        if action == "down":
            self.quick_menu_selection = (self.quick_menu_selection + 1) % len(entries)
            return
        selected = entries[self.quick_menu_selection][0]
        if getattr(self, "quick_menu_page", "main") == "equalizer":
            self._handle_equalizer_menu(selected, action)
            return
        if selected == "sleep" and action in ("left", "right"):
            self._cycle_sleep_timer(-1 if action == "left" else 1)
            return
        if selected == "audio_output" and action in ("left", "right"):
            self._cycle_audio_output(-1 if action == "left" else 1)
            return
        if selected == "led_mode" and action in ("left", "right"):
            self._cycle_led_mode(-1 if action == "left" else 1)
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
        elif selected == "equalizer":
            self.quick_menu_page = "equalizer"
            self.quick_menu_selection = 0
        elif selected == "audio_output":
            self._cycle_audio_output(1)
        elif selected == "led_mode":
            self._cycle_led_mode(1)
        elif selected == "spectrum":
            self._toggle_spectrum()
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
        elif selected == "background":
            if not self.player.current or not self.player.music:
                self.status = "Play a song before starting Background Playback"
                self.status_error = True
            elif save_background_session(self.paths, self.player, self.sleep_timer):
                get_logger().info(
                    "background playback requested track=%r position=%.3f duration=%.3f",
                    self.player.current.title, self.player.position(), self.player.duration(),
                )
                self.exit_code = BACKGROUND_EXIT
                self.quick_menu = False
                self.running = False
        elif selected == "auto_report":
            enabled = not self.settings.get("auto_report_errors")
            self.settings.set("auto_report_errors", enabled)
            self.settings.save()
            self.status = "Automatic error reports: %s" % ("On" if enabled else "Off")
            self.status_error = False
        elif selected == "update":
            self.quick_menu = False
            self._install_update()
        elif selected == "diagnostic":
            self.quick_menu = False
            self._send_diagnostic()
        else:
            self.quick_menu = False

    def _handle_equalizer_menu(self, selected, action):
        step = -1 if action == "left" else 1
        if selected == "eq_back" and action == "a":
            self.quick_menu_page = "main"
            self.quick_menu_selection = 1
            return
        if action not in ("a", "left", "right"):
            return
        equalizer = self.player.equalizer
        if selected == "eq_preset":
            preset = equalizer.cycle_preset(step)
            self.status = "Equalizer: %s" % preset
        elif selected.startswith("eq_"):
            band = selected[3:]
            value = equalizer.adjust(band, step)
            self.status = "%s: %+d dB" % (band.title(), value)
        else:
            return
        self.status_error = False
        if equalizer.gains != (0, 0, 0) and not equalizer.installed:
            self.status = "Equalizer unavailable on this firmware runtime"
            self.status_error = True
        get_logger().info("equalizer preset=%s gains=%s", equalizer.preset, equalizer.gains)

    def _cycle_audio_output(self, step):
        current = self.settings.get("audio_output")
        index = OUTPUT_MODES.index(current) if current in OUTPUT_MODES else 0
        mode = OUTPUT_MODES[(index + step) % len(OUTPUT_MODES)]
        self.settings.set("audio_output", mode)
        self.settings.save()
        self.status = "Audio Output: %s (applies next launch)" % output_mode_label(mode)
        self.status_error = False
        get_logger().info("audio output preference=%s", mode)

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

    def _visual_snapshot(self):
        analyser = getattr(getattr(self, "player", None), "analyser", None)
        if analyser is None:
            return self._visual_state
        try:
            levels, rms, beat = analyser.snapshot()
        except Exception:
            return self._visual_state
        self._visual_state = (tuple(levels), rms, beat)
        return self._visual_state

    def _update_visuals(self):
        levels, rms, beat = self._visual_snapshot()
        leds = getattr(self, "leds", None)
        if leds is None or not getattr(leds, "available", False):
            return
        try:
            mode = self.settings.get("led_mode")
        except Exception:
            mode = "spectrum"
        if mode == "off":
            return
        if mode == "beat" and not beat:
            return
        try:
            leds.update(levels, rms, beat)
        except Exception:
            pass

    def _cycle_led_mode(self, step=1):
        modes = ("off", "beat", "spectrum")
        try:
            current = self.settings.get("led_mode")
        except Exception:
            current = "spectrum"
        if current not in modes:
            current = "spectrum"
        mode = modes[(modes.index(current) + step) % len(modes)]
        self.settings.set("led_mode", mode)
        self.settings.save()
        self.status = "LED Mode: %s" % mode.title()
        self.status_error = False
        get_logger().info("LED mode changed=%s", mode)
        return mode

    def _toggle_spectrum(self):
        try:
            enabled = not self.settings.get("spectrum")
        except Exception:
            enabled = True
        self.settings.set("spectrum", enabled)
        self.settings.save()
        self.status = "Spectrum: %s" % ("On" if enabled else "Off")
        self.status_error = False
        get_logger().info("spectrum display=%s", "on" if enabled else "off")
        return enabled

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
        return max(3, (self.height - 190) // 52)

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
        title = self._screen_title()
        self.text(title, 28, 15, "title")
        title_width = self.measure(title, "title")[0]
        self.text(
            self._version_label(),
            44 + title_width, 24, "small", self.ACCENT,
        )
        if not self.player.audio_ready:
            output = "AUDIO OFF"
        else:
            output = "USB DAC" if self.player.output_device != "System / Bluetooth" else "SYSTEM/BT"
        subtitle = "%s | %d tracks | %s" % (
            self.paths.os_name.upper(), len(self._library_tracks()), output,
        )
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

    def _version_label(self):
        return "v%s | ID: %s" % (APP_VERSION, self.install_id)

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
        try:
            crumb = self.active_playlist or getattr(self.paths, "music_dir", "")
            self.text(
                self.ellipsize(str(crumb), self.width - 56, "small"),
                28, 74, "small", self.MUTED,
            )
        except Exception:
            pass
        rows = self.visible_rows()
        self.scroll = min(self.scroll, self.selection)
        if self.selection >= self.scroll + rows:
            self.scroll = self.selection - rows + 1
        spec_width = 150
        y = 104
        for index in range(self.scroll, min(len(entries), self.scroll + rows)):
            selected = index == self.selection
            if selected:
                self.fill(18, y - 5, self.width - 36, 48, self.ACCENT)
            color = self.TEXT if selected else self.TEXT
            dim_color = self.TEXT if selected else self.MUTED
            spec_color = self.TEXT if selected else self.SPEC
            entry = entries[index]
            if self.library_mode in ("playlists", "favorite_playlists"):
                favorite = self.collections.is_playlist_favorite(entry)
                title = ("* " if favorite else "") + entry
                count = len([track for track in self.tracks if track.folder == entry])
                detail = "%d tracks" % count
                spec = ""
            else:
                favorite = self.collections.is_track_favorite(entry.path)
                title = ("* " if favorite else "") + entry.title
                detail = entry.folder
                try:
                    spec = format_spec(entry.path)
                except Exception:
                    spec = ""
            self.text(
                self.ellipsize(title, self.width - 330 - spec_width, "body"),
                32, y, "body", color,
            )
            detail = self.ellipsize(detail, 245, "small")
            detail_width = self.measure(detail, "small")[0]
            self.text(detail, self.width - 32 - detail_width - spec_width, y + 5, "small", dim_color)
            if spec:
                spec_width_px = self.measure(spec, "small")[0]
                self.text(spec, self.width - 28 - spec_width_px, y + 5, "small", spec_color)
            y += 52

    def _fit_title(self, title, max_width):
        for font in ("title", "body", "small"):
            try:
                if self.measure(title, font)[0] <= max_width:
                    return (title, font)
            except Exception:
                continue
        try:
            return (self.ellipsize(title, max_width, "body"), "body")
        except Exception:
            return (title[:32], "body")

    def _render_playing(self):
        track = self.player.current
        if not track:
            self.text("Nothing is playing", self.width // 2, self.height // 2 - 25, "hero", center=True)
            return
        center_x = self.width // 2
        max_w = max(200, self.width - 80)
        title_text, title_font = self._fit_title(track.title, max_w)
        title_y = 78
        self.text(title_text, center_x, title_y, title_font, center=True)
        try:
            folder_text = self.ellipsize(track.folder or "", max_w, "small")
        except Exception:
            folder_text = track.folder or ""
        self.text(folder_text, center_x, title_y + 42, "small", self.MUTED, center=True)
        position = self.player.position()
        duration = self.player.duration()
        bar_x = 60
        bar_w = max(120, self.width - 120)
        prog_y = title_y + 76
        self.fill(bar_x, prog_y, bar_w, 8, self.PANEL)
        ratio = min(1.0, position / duration) if duration > 0 else 0.0
        self.fill(bar_x, prog_y, int(bar_w * ratio), 8, self.ACCENT)
        elapsed = self._format_time(position)
        total = self._format_time(duration) if duration else "--:--"
        times_y = prog_y + 12
        self.text(elapsed, bar_x, times_y, "small", self.MUTED)
        total_width = self.measure(total, "small")[0]
        self.text(total, bar_x + bar_w - total_width, times_y, "small", self.MUTED)
        try:
            source_rate, source_bits = track_audio_info(track.path)
        except Exception:
            source_rate, source_bits = (0, 0)
        try:
            output_rate = int(getattr(getattr(self.player, "equalizer", None), "sample_rate", 0) or 0)
        except Exception:
            output_rate = 0
        info_y = times_y + 26
        if source_rate and output_rate and source_rate != output_rate:
            self.text(
                "CONVERTED  %d -> %d" % (source_rate, output_rate),
                center_x, info_y, "small", self.GOLD, center=True,
            )
        elif source_rate:
            self.text(
                "DIRECT  %s" % format_spec(track.path),
                center_x, info_y, "small", self.GOLD, center=True,
            )
        format_line = self._format_line(track, source_rate, source_bits, output_rate)
        self.text(format_line, center_x, info_y + 22, "small", self.MUTED, center=True)
        self.text(
            self._playback_status_line(), center_x, info_y + 44, "small", self.MUTED, center=True,
        )
        content_bottom = info_y + 70
        status_top = self.height - 62 - 38
        spec_base = status_top - 20
        max_h = status_top - content_bottom - 32
        max_h = max(64, min(220, max_h))
        self._render_spectrum(spec_base, max_h, gain=1.6)

    def _format_line(self, track, source_rate, source_bits, output_rate):
        try:
            output_label = getattr(self.player, "output_device", "") or ""
        except Exception:
            output_label = ""
        if "USB" in output_label:
            output_name = "USB DAC"
        elif output_label:
            output_name = "Built-in"
        else:
            output_name = "Built-in"
        if source_rate and output_rate:
            source_text = "%d Hz" % source_rate
            if source_bits:
                source_text += "/%d-bit" % source_bits
            return "%s -> %d Hz/16-bit   %s" % (source_text, output_rate, output_name)
        try:
            return "%s   %s" % (format_spec(track.path), output_name)
        except Exception:
            return output_name

    def _playback_status_line(self):
        try:
            paused = bool(self.runtime.Mix_PausedMusic())
        except Exception:
            paused = False
        state = "Paused" if paused else "Playing"
        try:
            shuffle = "on" if self.settings.get("shuffle") else "off"
        except Exception:
            shuffle = "off"
        try:
            repeat = self.settings.get("repeat")
        except Exception:
            repeat = "off"
        try:
            volume = int(self.settings.get("volume"))
        except Exception:
            volume = 0
        return "%s   X shuffle %s   Y repeat %s   vol %d" % (state, shuffle, repeat, volume)

    def _render_spectrum(self, baseline_y, max_h=160, gain=1.6):
        try:
            enabled = bool(self.settings.get("spectrum"))
        except Exception:
            enabled = True
        if not enabled:
            return
        levels, _rms, beat = self._visual_snapshot()
        if not levels:
            return
        try:
            gain_value = max(1.0, min(3.0, float(gain)))
        except (TypeError, ValueError):
            gain_value = 1.6
        if not levels:
            return
        try:
            peaks = tuple(getattr(getattr(self, "player", None), "analyser", None).peaks)
            if len(peaks) != len(levels):
                peaks = tuple(levels)
        except Exception:
            peaks = tuple(levels)
        count = len(levels)
        area_x = 40
        area_w = max(120, self.width - 80)
        gap = 6 if count <= 14 else 4
        bar_w = max(8, (area_w - gap * (count - 1)) // count)
        total_w = bar_w * count + gap * (count - 1)
        start_x = area_x + (area_w - total_w) // 2
        body = self.ACCENT
        dark = self.ACCENT_DIM
        for index, raw in enumerate(levels):
            try:
                level = max(0.0, min(1.0, float(raw) * gain_value))
            except (TypeError, ValueError):
                level = 0.0
            try:
                peak = max(0.0, min(1.0, float(peaks[index]) * gain_value))
            except (IndexError, TypeError, ValueError):
                peak = level
            peak = max(peak, level)
            height = int(level * max_h) + (2 if level > 0.02 else 0)
            x = start_x + index * (bar_w + gap)
            if height > 0:
                low_h = int(height * 0.5)
                if low_h > 0:
                    self.fill(x, baseline_y - low_h, bar_w, low_h, dark)
                if height - low_h > 0:
                    self.fill(x, baseline_y - height, bar_w, height - low_h, body)
            cap_h = int(peak * max_h)
            cap_y = baseline_y - cap_h - 2
            if cap_y < baseline_y - max_h - 6:
                cap_y = baseline_y - max_h - 6
            self.fill(x, cap_y, bar_w, 3, self.TEXT)

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

    @staticmethod
    def _split_label(label):
        if ":" in label:
            key, _, value = label.partition(":")
            key = key.strip()
            value = value.strip()
            if key and value:
                return (key, value)
        return (label, "")

    def _render_quick_menu(self):
        entries = self._quick_menu_entries()
        width = min(680, self.width - 80)
        row_height = 52
        height = 102 + len(entries) * row_height
        x = (self.width - width) // 2
        y = (self.height - height) // 2
        self.fill(x - 4, y - 4, width + 8, height + 8, self.ACCENT)
        self.fill(x, y, width, height, self.PANEL)
        title = "EQUALIZER" if getattr(self, "quick_menu_page", "main") == "equalizer" else "QUICK MENU"
        self.text(title, self.width // 2, y + 22, "title", center=True)
        value_x = x + min(300, width // 2)
        for index, (_, label) in enumerate(entries):
            row_y = y + 70 + index * row_height
            selected = index == self.quick_menu_selection
            if selected:
                self.fill(x + 24, row_y - 8, width - 48, 48, self.ACCENT)
            key_color = self.TEXT if selected else self.ACCENT
            value_color = self.TEXT if selected else self.TEXT
            key, value = self._split_label(label)
            if value:
                self.text(self.ellipsize(key, value_x - x - 60, "body"), x + 45, row_y, "body", key_color)
                self.text(
                    self.ellipsize(value, x + width - value_x - 30, "body"),
                    value_x, row_y, "body", value_color,
                )
            else:
                self.text(self.ellipsize(key, width - 90, "body"), x + 45, row_y, "body", value_color)

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
            text_color = self.TEXT
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
