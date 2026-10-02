import ctypes
import os
import threading
import time

from . import APP_VERSION
from .audio import AudioPlayer
from .audio_output import OUTPUT_MODES, output_mode_label
from .background import BACKGROUND_EXIT, load_resume, save_background_session
from .collections import Collections
from .display import DisplayController
from .drive import (
    DEFAULT_FOLDER_ID,
    FOLDER_MIME,
    DriveEntry,
    DriveError,
    StreamJob,
    clear_cache as drive_clear_cache,
    clear_finished_jobs as drive_clear_finished_jobs,
    extract_folder_id as drive_extract_folder_id,
    find_offline_copy as drive_find_offline_copy,
    format_bytes as drive_format_bytes,
    get_cached_folder as drive_get_cached,
    list_folder as drive_list_folder,
    list_folder_public as drive_list_public,
    put_cached_folder as drive_put_cache,
    start_offline_job as drive_start_offline_job,
    start_stream_job as drive_start_stream_job,
    stream_cache_size as drive_cache_size,
    stream_path as drive_stream_path,
)
from .drivelink import DriveLinkServer
from .input import InputState
from .identity import installation_id
from .audio_format import format_spec
from .leds import LedController
from .library import Track
from .logger import clear_log_backups, get_logger, log_backup_bytes
from .lyrics import load_lyrics
from .reporter import queue_report, retry_pending
from .settings import Settings
from .sleep_timer import SleepTimer
from .sdl_runtime import (
    MIX_INIT_FLAC,
    MIX_INIT_MP3,
    MIX_INIT_OGG,
    MIX_INIT_OPUS,
    SDL_Color,
    SDL_DisplayMode,
    SDL_Event,
    SDL_INIT_AUDIO,
    SDL_INIT_GAMECONTROLLER,
    SDL_INIT_JOYSTICK,
    SDL_INIT_VIDEO,
    SDL_QUIT,
    SDLK_ESCAPE,
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
    BG = (226, 232, 240, 255)
    PANEL = (255, 255, 255, 255)
    TRACK = (203, 213, 225, 255)
    ACCENT = (14, 165, 233, 255)
    ACCENT_DIM = (186, 230, 253, 255)
    TEXT = (15, 23, 42, 255)
    ON_ACCENT = (255, 255, 255, 255)
    MUTED = (100, 116, 139, 255)
    SPEC = (249, 115, 22, 255)
    ACCENT_SOFT = (222, 245, 242, 255)
    GOLD = (255, 195, 60, 255)
    ERROR = (220, 50, 50, 255)
    INTRO_BG = (8, 8, 12, 255)
    INTRO_RED = (229, 9, 20, 255)

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
        self.library_mode = "source"
        self.playlist_parent_mode = "playlists"
        self.active_playlist = ""
        self.quick_menu = False
        self.quick_menu_selection = 0
        self.quick_menu_scroll = 0
        self.quick_menu_page = "main"
        self.sleep_timer = SleepTimer()
        self.display = DisplayController(paths)
        self.lyrics_cache = {}
        self.exit_code = 0
        self.leds = None
        self._visual_state = ([0.0] * 14, 0.0, False)
        self.next_update_check = 0.0
        self.update_check_interval = 300.0
        self.drive_stack = []
        self.drive_entries = []
        self.drive_page_token = ""
        self.drive_busy = False
        self.drive_loaded = False
        self._prefetch_base = None
        self._prefetch_target = -1
        self.link_server = None
        self.link_url = ""
        self.link_qr = None
        # Tai Drive: job dang chay (de ve %) + dong "da luu" gan header.
        self.download_job = None
        self._saved_toast = ("", 0.0)
        self._jobs_pruned_at = time.monotonic()

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
        self.player.drive_resolver = self._drive_resolve_track
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
            self.next_update_check = time.monotonic() + self.update_check_interval

    def _load_fonts(self):
        candidates = font_candidates(self.paths)
        if not candidates:
            raise RuntimeError("no TrueType font found on this firmware")
        font_path = candidates[0].encode("utf-8")
        scale = max(0.75, min(self.width / 1024.0, self.height / 768.0))
        for name, size in (("small", 20), ("body", 27), ("title", 36), ("hero", 44),
                           ("giant", 132)):
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

    def _check_update(self, manual=False):
        try:
            manifest = fetch_manifest(self.paths)
            if update_available(manifest) and manifest.get("version") != self.settings.get("skipped_version"):
                with self.update_lock:
                    self.update_manifest = manifest
                    self.status = "Update v%s available - open SELECT menu to install" % manifest["version"]
                    self.status_error = False
            elif manual:
                with self.update_lock:
                    self.status = "Already on latest v%s" % APP_VERSION
                    self.status_error = False
        except Exception as error:
            get_logger().warning("OTA check failed: %s", error)
            if manual:
                with self.update_lock:
                    self.status = "Update check failed; turn Wi-Fi on and retry"
                    self.status_error = True
        finally:
            try:
                self.next_update_check = time.monotonic() + self.update_check_interval
            except Exception:
                pass

    def _maybe_check_update(self):
        try:
            enabled = bool(self.settings.get("auto_update"))
        except Exception:
            enabled = False
        if not enabled or self.update_busy:
            return
        try:
            due = time.monotonic() >= self.next_update_check
        except Exception:
            due = False
        if not due:
            return
        self.next_update_check = time.monotonic() + self.update_check_interval
        threading.Thread(target=self._check_update, name="ota-check", daemon=True).start()

    def _check_update_now(self):
        with self.update_lock:
            if self.update_busy:
                return
        self.status = "Checking for update..."
        self.status_error = False
        threading.Thread(
            target=self._check_update, kwargs={"manual": True},
            name="ota-check-manual", daemon=True,
        ).start()

    def _audio_info_line(self):
        try:
            flags = int(getattr(self.player, "available_decoders", 0) or 0)
        except (TypeError, ValueError):
            flags = 0
        names = []
        for bit, name in (
            (MIX_INIT_FLAC, "FLAC"), (MIX_INIT_MP3, "MP3"),
            (MIX_INIT_OGG, "OGG"), (MIX_INIT_OPUS, "OPUS"),
        ):
            if flags & bit:
                names.append(name)
        decoders = "+".join(names) if names else "no optional decoders"
        try:
            output = getattr(self.player, "output_device", "") or "unknown output"
            rate = int(getattr(self.player, "sample_rate", 0) or 0)
        except (TypeError, ValueError):
            output, rate = "unknown output", 0
        if rate:
            return "Audio: %s | %s %dHz" % (decoders, output, rate)
        return "Audio: %s | %s" % (decoders, output)

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
        try:
            self._close_add_drive(silent=True)
        except Exception:
            pass
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
            self._play_intro()
            event = SDL_Event()
            while self.running:
                while self.runtime.SDL_PollEvent(ctypes.byref(event)):
                    if event.type == SDL_QUIT:
                        get_logger().info("received SDL quit event")
                        self.running = False
                    else:
                        try:
                            self.input.feed(event)
                        except Exception as error:
                            get_logger().warning("ignoring bad input event: %s", error)
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
                self._poll_offline_job()
                self._maybe_prefetch_drive()
                self._maybe_prune_jobs()
                self._poll_drive_link()
                self._maybe_check_update()
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
        if self.screen == "library" and action == "prev":
            action = "up"
        elif self.screen == "library" and action == "next":
            action = "down"
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
            self.quick_menu_scroll = 0
            self.quick_menu_page = "main"
            return
        if action == "start":
            if self.screen == "addrive":
                self._close_add_drive()
            else:
                self.screen = "playing" if self.screen == "library" else "library"
            return
        if action == "b":
            if self.screen == "addrive":
                self._close_add_drive()
                return
            if self.screen == "lyrics":
                self.screen = "playing"
            elif self.screen == "playing":
                self.screen = "library"
            elif self.library_mode == "playlist_tracks":
                self.library_mode = self.playlist_parent_mode
                self.active_playlist = ""
                self.selection = 0
                self.scroll = 0
            elif self.screen == "library" and self.library_mode == "drive" and getattr(self, "drive_stack", None):
                self.drive_stack.pop()
                self.drive_entries = []
                self.drive_page_token = ""
                self.selection = 0
                self.scroll = 0
                if not self.drive_stack:
                    self.drive_loaded = False
                self._drive_refresh()
            elif self.screen == "library" and self.library_mode != "source":
                self._open_source()
            else:
                self.exit_confirmation = True
            return
        if action in ("l1", "r1", "prev", "next"):
            forward = action in ("r1", "next")
            if self.screen == "library" and action in ("l1", "r1"):
                self._page_selection(1 if forward else -1)
                return
            if action in ("l1", "r1"):
                return
            self.player.advance(forward)
            if self.screen == "library":
                self.screen = "playing"
            return
        if action == "l2":
            self._toggle_shuffle()
            return
        if action == "r2":
            self._cycle_repeat()
            return
        if action == "x":
            if self.screen == "lyrics":
                self._cycle_lyrics_translation()
            elif self.screen == "library" and self.library_mode == "drive":
                rows = self._drive_rows()
                if rows:
                    self.selection = min(self.selection, len(rows) - 1)
                    self._drive_download_row(rows[self.selection])
            elif self.screen in ("library", "playing"):
                self._toggle_favorite()
            return
        if action == "y":
            if self.screen == "library":
                if self.library_mode == "drive":
                    self._open_source()
                elif self.library_mode == "source":
                    self._open_drive()
                else:
                    self._cycle_library_mode()
            elif self.screen in ("playing", "lyrics"):
                self._save_current_to_device()
            return
        if self.screen == "library":
            if self.library_mode == "source":
                if action in ("up", "stick_up"):
                    self.selection = max(0, self.selection - 1)
                elif action in ("down", "stick_down"):
                    self.selection = min(2, self.selection + 1)
                elif action == "left":
                    self.selection = 0
                elif action == "right":
                    self.selection = 2
                elif action == "a":
                    if self.selection == 1:
                        self._open_drive()
                    elif self.selection == 2:
                        self._open_add_drive()
                    else:
                        self.library_mode = "all"
                        self.selection = 0
                        self.scroll = 0
                        get_logger().info("library mode=all")
                return
            if self.library_mode == "drive":
                rows = self._drive_rows()
                if not rows:
                    if action in ("up", "down", "left", "right", "a"):
                        self._drive_refresh()
                    return
                if action in ("up", "stick_up"):
                    self.selection = max(0, self.selection - 1)
                elif action in ("down", "stick_down"):
                    self.selection = min(len(rows) - 1, self.selection + 1)
                elif action == "left":
                    self.selection = max(0, self.selection - self.visible_rows())
                elif action == "right":
                    self.selection = min(len(rows) - 1, self.selection + self.visible_rows())
                elif action == "a":
                    self.selection = min(self.selection, len(rows) - 1)
                    self._drive_play_row(rows[self.selection])
                return
            entries = self._library_entries()
            if action in ("up", "stick_up") and entries:
                self.selection = max(0, self.selection - 1)
            elif action in ("down", "stick_down") and entries:
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
        elif self.screen == "addrive":
            if action == "a":
                self._open_add_drive()
        else:
            if action == "a":
                paused = self.player.toggle_pause()
                self.status = "Paused" if paused else "Playing"
                self.status_error = False
            elif action == "left":
                self.player.seek(-10)
            elif action == "right":
                self.player.seek(10)

    def _quick_menu_visible_rows(self):
        return max(3, (self.height - 220) // 52)

    def _quick_menu_clamp_scroll(self):
        entries = self._quick_menu_entries()
        visible = self._quick_menu_visible_rows()
        scroll = getattr(self, "quick_menu_scroll", 0)
        scroll = max(0, min(scroll, max(0, len(entries) - visible)))
        if self.quick_menu_selection < scroll:
            scroll = self.quick_menu_selection
        elif self.quick_menu_selection >= scroll + visible:
            scroll = self.quick_menu_selection - visible + 1
        self.quick_menu_scroll = scroll
        return scroll

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
            ("intro", "Intro: %s" % ("On" if self.settings.get("intro") else "Off")),
            ("drive_refresh", "Drive Refresh"),
            ("drive_download", "Drive Download (offline)"),
            ("drive_clear", "Drive Cache: %s - Clear" % self._drive_cache_label()),
            ("clear_logs", "Clear Logs (%s)" % self._logs_label()),
            ("audio_info", "Audio Info"),
            ("check_update", "Check for Update"),
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
        if action in ("stick_up", "prev"):
            action = "up"
        elif action in ("stick_down", "next"):
            action = "down"
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
            self._quick_menu_clamp_scroll()
            return
        if action == "down":
            self.quick_menu_selection = (self.quick_menu_selection + 1) % len(entries)
            self._quick_menu_clamp_scroll()
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
        elif selected == "intro":
            self._toggle_intro()
        elif selected == "drive_refresh":
            self.quick_menu = False
            self.library_mode = "drive"
            self.screen = "library"
            self.drive_entries = [] if not getattr(self, "drive_stack", None) else self.drive_entries
            self.drive_page_token = ""
            self.selection = 0
            self.scroll = 0
            self._drive_refresh()
        elif selected == "drive_download":
            self.quick_menu = False
            if self.library_mode == "drive" and self.screen == "library":
                rows = self._drive_rows()
                if rows:
                    self.selection = min(self.selection, len(rows) - 1)
                    self._drive_download_row(rows[self.selection])
            else:
                self.status = "Open DRIVE view (Y) first, then download"
                self.status_error = True
        elif selected == "drive_clear":
            try:
                before = drive_cache_size(self.paths.data_dir)
                drive_clear_cache(self.paths.data_dir)
            except Exception as error:
                self.status = "Drive clear: %s" % error
                self.status_error = True
            else:
                self.drive_entries = []
                self.drive_page_token = ""
                self.drive_loaded = False
                self.status = "Drive cache cleared (%s freed)" % drive_format_bytes(before)
                self.status_error = False
        elif selected == "clear_logs":
            try:
                freed = clear_log_backups(self.paths)
            except Exception as error:
                self.status = "Clear logs: %s" % error
                self.status_error = True
            else:
                self.status = "Logs cleared (%s freed)" % drive_format_bytes(freed)
                self.status_error = False
        elif selected == "audio_info":
            self.status = self._audio_info_line()
            self.status_error = False
        elif selected == "check_update":
            self._check_update_now()
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

    def _toggle_shuffle(self):
        try:
            enabled = not self.settings.get("shuffle")
        except Exception:
            enabled = True
        self.settings.set("shuffle", enabled)
        self.settings.save()
        self.status = "Shuffle: %s" % ("On" if enabled else "Off")
        self.status_error = False
        get_logger().info("shuffle=%s", "on" if enabled else "off")
        return enabled

    def _cycle_repeat(self):
        values = ("off", "all", "one")
        try:
            current = self.settings.get("repeat")
        except Exception:
            current = "off"
        repeat = values[(values.index(current) + 1) % len(values)] if current in values else "off"
        self.settings.set("repeat", repeat)
        self.settings.save()
        self.status = "Repeat: %s" % repeat.title()
        self.status_error = False
        get_logger().info("repeat mode changed=%s", repeat)
        return repeat

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

    def _led_test_label(self):
        leds = getattr(self, "leds", None)
        index = getattr(leds, "test_index", -1) if leds is not None else -1
        if index is None or index < 0:
            return "Off"
        try:
            slots = int(getattr(leds, "slots", 23) or 23)
        except (TypeError, ValueError):
            slots = 23
        return "%d/%d" % (index % slots + 1, slots)

    def _toggle_led_test(self):
        leds = getattr(self, "leds", None)
        if leds is None or not getattr(leds, "available", False):
            self.status = "LED hardware not found on this device"
            self.status_error = True
            return -1
        if getattr(leds, "test_index", -1) >= 0:
            leds.test_index = -1
            self.status = "LED Test off"
        else:
            leds.test_index = 0
            self.status = "LED Test: watch which LED is white, LEFT/RIGHT steps"
        self.status_error = False
        get_logger().info("LED test index=%s", getattr(leds, "test_index", -1))
        return leds.test_index

    def _step_led_test(self, step):
        leds = getattr(self, "leds", None)
        if leds is None or getattr(leds, "test_index", -1) < 0:
            return -1
        try:
            slots = int(getattr(leds, "slots", 23) or 23)
        except (TypeError, ValueError):
            slots = 23
        leds.test_index = (leds.test_index + step) % slots
        self.status = "LED Test: pos %d/%d - which LED is white?" % (
            leds.test_index + 1, slots,
        )
        self.status_error = False
        return leds.test_index

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

    def _toggle_intro(self):
        try:
            enabled = not self.settings.get("intro")
        except Exception:
            enabled = True
        self.settings.set("intro", enabled)
        self.settings.save()
        self.status = "Intro: %s" % ("On" if enabled else "Off")
        self.status_error = False
        get_logger().info("intro splash=%s", "on" if enabled else "off")
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

    def _open_source(self):
        self.library_mode = "source"
        self.active_playlist = ""
        self.selection = 0
        self.scroll = 0
        get_logger().info("library mode=source")

    def _open_drive(self):
        try:
            self.settings.load()
        except Exception as error:
            get_logger().warning("cannot reload settings: %s", error)
        self.library_mode = "drive"
        self.screen = "library"
        self.selection = 0
        self.scroll = 0
        get_logger().info("library mode=drive")
        if not getattr(self, "drive_loaded", False):
            self._drive_refresh()

    def _open_add_drive(self):
        self._close_add_drive(silent=True)
        self.screen = "addrive"
        self.selection = 0
        self.scroll = 0
        try:
            server = DriveLinkServer(self.paths)
            url = server.start()
        except Exception as error:
            get_logger().warning("drive link server failed: %s", error)
            self.link_server = None
            self.link_url = ""
            self.link_qr = None
            self.status = "Link server failed - check Wi-Fi, press A to retry"
            self.status_error = True
            return
        self.link_server = server
        self.link_url = url
        try:
            from .qrcode import encode as qr_encode
            self.link_qr = qr_encode(url, ecc="M") if url else None
        except Exception as error:
            get_logger().warning("QR encode failed: %s", error)
            self.link_qr = None
        if url:
            self.status = ""
            get_logger().info("add-drive screen ready url=%s", url)
        else:
            self.status = "Link server failed - check Wi-Fi, press A to retry"
            self.status_error = True

    def _close_add_drive(self, silent=False):
        server, self.link_server = getattr(self, "link_server", None), None
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass
        self.link_qr = None
        self.link_url = ""
        if not silent:
            self.screen = "library"
            self._open_source()

    def _poll_drive_link(self):
        server = getattr(self, "link_server", None)
        if server is None:
            return
        try:
            result = server.poll()
        except Exception:
            return
        if not result:
            return
        if not result.get("ok"):
            self.status = result.get("message", "Drive link failed")
            self.status_error = True
            return
        # Read the fresh values from disk: the web thread saved them, and
        # this process's in-memory settings may still hold the previous
        # folder. Never write the stale memory back over the file.
        try:
            fresh = Settings(self.paths.settings_file).load()
            folder_id = str(fresh.get("drive_folder_id") or "")
            slots = fresh.get("drive_slots")
            slot_index = fresh.get("drive_slot")
        except Exception as error:
            get_logger().warning("cannot reload drive settings: %s", error)
            folder_id, slots, slot_index = "", [], 0
        folder_id = drive_extract_folder_id(folder_id) if folder_id else DEFAULT_FOLDER_ID
        try:
            self.settings.set("drive_folder_id", folder_id)
            if isinstance(slots, list) and slots:
                self.settings.set("drive_slots", slots)
            try:
                self.settings.set("drive_slot", max(0, int(slot_index)))
            except (TypeError, ValueError):
                pass
            self.settings.save()
        except Exception as error:
            get_logger().warning("cannot save drive folder: %s", error)
        self.drive_stack = []
        self.drive_entries = []
        self.drive_page_token = ""
        self.drive_loaded = False
        self._prefetch_base = None
        self._prefetch_target = -1
        self.status = result.get("message", "Drive link saved")
        self.status_error = False
        get_logger().info("drive link applied folder=%s", folder_id)
        self._close_add_drive()
        self._open_drive()

    def _cycle_library_mode(self):
        modes = ("all", "favorites", "playlists", "favorite_playlists")
        current = self.playlist_parent_mode if self.library_mode == "playlist_tracks" else self.library_mode
        if current not in modes:
            current = "all"
        self.library_mode = modes[(modes.index(current) + 1) % len(modes)]
        self.active_playlist = ""
        self.selection = 0
        self.scroll = 0
        get_logger().info("library mode=%s", self.library_mode)

    def _drive_folder_id(self):
        slot = self._drive_slot()
        if slot:
            return slot["folder"]
        try:
            folder = str(self.settings.get("drive_folder_id") or "").strip()
        except Exception:
            folder = ""
        return drive_extract_folder_id(folder) if folder else DEFAULT_FOLDER_ID

    def _drive_slots(self):
        try:
            from .drive import normalize_slots
        except Exception:
            normalize_slots = None
        try:
            raw = self.settings.get("drive_slots")
            fallback = str(self.settings.get("drive_folder_id") or "")
        except Exception:
            raw, fallback = [], ""
        if normalize_slots is None:
            return [{"name": "Drive 1", "folder": fallback or DEFAULT_FOLDER_ID}]
        slots = normalize_slots(raw if isinstance(raw, list) else [], fallback)
        if not slots:
            slots = [{"name": "Drive 1", "folder": fallback or DEFAULT_FOLDER_ID}]
        return slots

    def _drive_slot_index(self):
        slots = self._drive_slots()
        try:
            index = int(self.settings.get("drive_slot"))
        except Exception:
            index = 0
        return max(0, min(index, len(slots) - 1))

    def _drive_slot(self):
        slots = self._drive_slots()
        if not slots:
            return None
        return slots[self._drive_slot_index()]

    def _drive_slot_name(self):
        slot = self._drive_slot()
        name = str(slot.get("name", "")).strip() if slot else ""
        return name or "Drive"

    def _drive_api_key(self):
        try:
            return str(self.settings.get("drive_api_key") or "").strip()
        except Exception:
            return ""

    def _drive_current(self):
        if getattr(self, "drive_stack", None):
            return self.drive_stack[-1]
        return (self._drive_folder_id(), "Drive")

    def _drive_path_label(self):
        names = [name for _, name in (getattr(self, "drive_stack", []) or [])]
        root = self._drive_slot_name()
        if not names:
            return root.upper()
        if len(names) == 1 and names[0] == root:
            return root.upper()
        if len(names) > 1 and names[0] == root:
            names = names[1:]
        return "%s/%s" % (root, "/".join(names))

    def _drive_album_label(self):
        names = [name for _, name in (getattr(self, "drive_stack", []) or [])]
        root = self._drive_slot_name()
        if names and names[0] == root:
            names = names[1:]
        cleaned = [name for name in names if name and name != "Drive"]
        sub = "/".join(cleaned)
        return "%s/%s" % (root, sub) if sub else root

    def _drive_refresh(self, page_token="", append=False):
        if getattr(self, "drive_busy", False):
            return
        self.drive_busy = True
        try:
            self._drive_refresh_inner(page_token, append)
        finally:
            self.drive_busy = False

    def _drive_friendly_error(self, error):
        text = str(error or "Drive failed")
        lowered = text.lower()
        if "network" in lowered or "timed out" in lowered or "url error" in lowered:
            return "Connect Wi-Fi, then try again"
        return text

    def _drive_refresh_inner(self, page_token="", append=False):
        if not getattr(self, "drive_stack", None) and not append:
            try:
                slot_count = len(self._drive_slots())
            except Exception:
                slot_count = 1
            if slot_count > 1:
                self.drive_entries = self._drive_slot_entries()
                self.drive_page_token = ""
                self.drive_loaded = True
                self.selection = min(
                    getattr(self, "selection", 0), max(0, len(self._drive_rows()) - 1))
                self.status = ""
                self.status_error = False
                get_logger().info("drive slot list shown slots=%d", slot_count)
                return
        try:
            folder_id, _name = self._drive_current()
        except Exception:
            folder_id = self._drive_folder_id()
        api_key = self._drive_api_key()
        try:
            data_dir = self.paths.data_dir
        except Exception:
            data_dir = ""
        try:
            app_dir = self.paths.app_dir
        except Exception:
            app_dir = ""
        try:
            if api_key:
                entries, token = drive_list_folder(
                    app_dir, folder_id, api_key, page_token, 25,
                )
            else:
                entries, token = drive_list_public(app_dir, folder_id)
        except DriveError as error:
            cached = drive_get_cached(data_dir, folder_id, page_token) if data_dir else None
            if cached is not None:
                cached_entries, cached_token = cached
                self.drive_entries = (self.drive_entries + cached_entries) if append else cached_entries
                self.drive_page_token = cached_token
                self.drive_loaded = True
                self.status = "OFFLINE - cached copy (%d items)" % len(self.drive_entries)
                self.status_error = False
            elif "network" in str(error).lower():
                self.status = "No cached Drive data - turn Wi-Fi on, then Drive Refresh"
                self.status_error = True
            else:
                self.status = "Drive: %s" % error
                self.status_error = True
            get_logger().warning("drive list failed: %s", error)
            return
        except Exception as error:
            self.status = "Drive: %s" % error
            self.status_error = True
            get_logger().warning("drive list failed: %s", error)
            return
        try:
            if data_dir:
                if append:
                    previous = drive_get_cached(data_dir, folder_id, "") or ([], "")
                    merged = (previous[0] if previous else []) + list(entries)
                    drive_put_cache(data_dir, folder_id, merged, token)
                else:
                    drive_put_cache(data_dir, folder_id, entries, token)
        except Exception as error:
            get_logger().warning("drive cache save failed: %s", error)
        self.drive_entries = (self.drive_entries + list(entries)) if append else list(entries)
        self.drive_page_token = token
        self.drive_loaded = True
        self.selection = min(getattr(self, "selection", 0), max(0, len(self._drive_rows()) - 1))
        self.status = "Drive: %d items - X saves songs to device" % len(self.drive_entries)
        self.status_error = False
        get_logger().info(
            "drive list folder=%s items=%d more=%s", folder_id, len(entries), bool(token),
        )

    def _drive_rows(self):
        rows = list(getattr(self, "drive_entries", []) or [])
        if getattr(self, "drive_page_token", ""):
            rows = rows + ["__more__"]
        return rows

    def _drive_slot_entries(self):
        return [
            DriveEntry(
                file_id="slot:%d" % index,
                name=str(slot.get("name", "Drive")),
                mime_type=FOLDER_MIME,
                size=0,
                is_folder=True,
                title=str(slot.get("name", "Drive")),
                extension="",
            )
            for index, slot in enumerate(self._drive_slots())
        ]

    def _drive_cache_label(self):
        try:
            from .drive import MAX_STREAM_CACHE_BYTES
            return "%s/%s" % (
                drive_format_bytes(drive_cache_size(self.paths.data_dir)),
                drive_format_bytes(MAX_STREAM_CACHE_BYTES),
            )
        except Exception:
            return "Clear"

    def _logs_label(self):
        try:
            return drive_format_bytes(log_backup_bytes(self.paths))
        except Exception:
            return "0MB"

    def _maybe_prefetch_drive(self):
        """Download the upcoming Drive track in the background while playing."""
        try:
            player = self.player
            if player is None or not getattr(player, "audio_ready", False):
                return
            current = player.current
            if current is None or not getattr(current, "path", "").startswith("drive://"):
                return
            tracks = player.tracks
            if not tracks or len(tracks) < 2:
                return
            base = (len(tracks), player.index, current.path)
            if base != getattr(self, "_prefetch_base", None):
                self._prefetch_base = base
                try:
                    shuffled = bool(self.settings.get("shuffle"))
                except Exception:
                    shuffled = False
                try:
                    self._prefetch_target = (
                        -1 if shuffled else player.next_index(True, automatic=True)
                    )
                except Exception:
                    self._prefetch_target = -1
            target = getattr(self, "_prefetch_target", -1)
            if target is None or target < 0 or target == player.index:
                return
            try:
                app_dir = self.paths.app_dir
                data_dir = self.paths.data_dir
            except Exception:
                return
            threading.Thread(
                target=self._prefetch_drive_track,
                args=(tracks[target], self._drive_api_key(), app_dir, data_dir),
                name="drive-prefetch", daemon=True,
            ).start()
            self._prefetch_target = -1
        except Exception as error:
            get_logger().warning("drive prefetch skipped: %s", error)

    @staticmethod
    def _prefetch_drive_track(track, api_key, app_dir, data_dir):
        try:
            path = getattr(track, "path", "")
            if not path.startswith("drive://"):
                return
            remainder = path[len("drive://"):]
            file_id = remainder.split("/", 1)[0]
            filename = remainder.split("/", 1)[1] if "/" in remainder else "track"
            if not file_id:
                return
            import os as _os
            entry = DriveEntry(
                file_id=file_id,
                name=filename,
                mime_type="",
                size=0,
                is_folder=False,
                title=filename.rsplit(".", 1)[0],
                extension=_os.path.splitext(filename)[1].lower(),
            )
            # Dung job dung chung: neu man hinh chinh da bat dau tai file nay
            # thi prefetch chi theo doi, khong tai trung.
            job = drive_start_stream_job(app_dir, data_dir, entry, api_key or "")
            if not job.done:
                while job.running:
                    time.sleep(0.3)
            if job.error:
                get_logger().info("drive prefetch missed: %s", job.error)
            else:
                get_logger().info("drive prefetched %r", filename)
        except Exception as error:
            get_logger().info("drive prefetch missed: %s", error)

    def _drive_resolve_track(self, track):
        """Resolve a drive:// track to a local cached file for SDL_mixer.

        KHONG tai trong thread chinh. Day chay 1 job (dung chung voi prefetch
        neu dang chay) va CHO trong vong lap co Present + hut event, nen app
        van song, hien % tai va bam B de huy. Truoc day tai synchronous o day
        nen app DONG BANG ca luc khong ve khung nao -> "treo cung".
        """
        path = getattr(track, "path", "")
        if not path.startswith("drive://"):
            return path
        remainder = path[len("drive://"):]
        file_id = remainder.split("/", 1)[0]
        filename = remainder.split("/", 1)[1] if "/" in remainder else "track"
        if not file_id:
            raise DriveError("bad Drive track path")
        try:
            from .drive import DriveEntry as _DriveEntry
            entry = _DriveEntry(
                file_id=file_id,
                name=filename,
                mime_type="",
                size=0,
                is_folder=False,
                title=filename.rsplit(".", 1)[0],
                extension=__import__("os").path.splitext(filename)[1].lower(),
            )
        except Exception:
            raise DriveError("bad Drive track path")
        try:
            app_dir = self.paths.app_dir
            data_dir = self.paths.data_dir
        except Exception as error:
            raise DriveError("paths unavailable: %s" % error)
        known = next(
            (item for item in (getattr(self, "drive_entries", []) or [])
             if getattr(item, "file_id", "") == file_id),
            None,
        )
        if known is not None:
            entry = known
        api_key = self._drive_api_key()
        try:
            job = drive_start_stream_job(app_dir, data_dir, entry, api_key)
        except Exception as error:
            raise DriveError(str(error))
        if job.running:
            self.status = ""
            local = self._wait_for_download(job)
        else:
            local = job.path
        if not local:
            raise DriveError(job.error or "Drive download failed")
        self.status = ""
        return local

    def _wait_for_download(self, job, timeout=240.0):
        """Cho job xong nhung van Present + hut phim (B de huy)."""
        event = SDL_Event()
        started = time.monotonic()
        while job.running and time.monotonic() - started < timeout:
            self.download_job = job
            if self._poll_cancel(event):
                job.cancel()
                while job.running:
                    time.sleep(0.1)
                self.download_job = None
                raise DriveError("Download cancelled")
            self._render()
            self.runtime.SDL_Delay(16)
        self.download_job = None
        if job.running:
            job.cancel()
            raise DriveError("Download timed out")
        return job.path

    def _poll_cancel(self, event):
        """Hut event, tra True neu nguoi dung bam B/quit giua luc tai."""
        cancelled = False
        while self.runtime.SDL_PollEvent(ctypes.byref(event)):
            if event.type == SDL_QUIT:
                self.running = False
                cancelled = True
            elif event.type == SDL_KEYDOWN and event.key.keysym.sym == SDLK_ESCAPE:
                cancelled = True
            elif event.type == SDL_CONTROLLERBUTTONDOWN and event.cbutton.button == 0:
                cancelled = True
            elif event.type == SDL_JOYBUTTONDOWN and not self.controllers \
                    and event.jbutton.button == 0:
                cancelled = True
        return cancelled

    def _drive_track_for(self, entry):
        album = self._drive_album_label()
        folder = album if album != "Drive" else "Drive"
        return Track(
            path="drive://%s/%s" % (entry.file_id, entry.name),
            title=entry.title,
            folder=folder,
            extension=entry.extension,
        )

    def _enter_drive_slot(self, index):
        try:
            slots = self._drive_slots()
            slot = slots[index]
        except (TypeError, ValueError, IndexError, KeyError):
            return False
        try:
            self.settings.set("drive_slot", index)
            self.settings.set("drive_folder_id", slot["folder"])
            self.settings.save()
        except Exception as error:
            get_logger().warning("cannot save drive slot: %s", error)
        self.drive_stack = [(slot["folder"], slot["name"])]
        self.drive_entries = []
        self.drive_page_token = ""
        self.selection = 0
        self.scroll = 0
        get_logger().info("drive slot opened=%s folder=%s", slot["name"], slot["folder"])
        self._drive_refresh()
        return True

    def _drive_play_row(self, row):
        from .drive import DriveEntry as _DriveEntry
        if row == "__more__":
            token = getattr(self, "drive_page_token", "")
            self._drive_refresh(page_token=token, append=True)
            return True
        if not isinstance(row, _DriveEntry):
            return False
        if row.file_id.startswith("slot:"):
            try:
                return self._enter_drive_slot(int(row.file_id.split(":", 1)[1]))
            except (TypeError, ValueError):
                return False
        if row.is_folder:
            self.drive_stack.append((row.file_id, row.name))
            self.drive_entries = []
            self.drive_page_token = ""
            self.selection = 0
            self.scroll = 0
            self._drive_refresh()
            return True
        playlist = [self._drive_track_for(item) for item in (self.drive_entries or []) if not item.is_folder]
        target = next(
            (index for index, track in enumerate(playlist) if track.path.startswith("drive://%s/" % row.file_id)),
            -1,
        )
        if target < 0:
            self.status = "Drive track not found"
            self.status_error = True
            return False
        self.player.tracks = playlist
        if self.player.play(target):
            self.screen = "playing"
            return True
        self.status = self._drive_friendly_error(self.player.error or "Drive playback failed")
        self.status_error = True
        return False

    def _drive_download_row(self, row):
        from .drive import DriveEntry as _DriveEntry
        if row == "__more__" or not isinstance(row, _DriveEntry) or row.is_folder:
            self.status = "Select an audio track to download"
            self.status_error = True
            return False
        return self._save_entry_offline(row, self._drive_album_label())

    def _existing_offline_copy(self, entry):
        """Bai da co san trong thu vien local chua (ke ca o thu muc khac)."""
        try:
            return drive_find_offline_copy(self.paths.music_dir, entry.name,
                                           getattr(entry, "size", 0))
        except Exception:
            return ""

    def _save_entry_offline(self, entry, album):
        """Bat dau luu bai xuong may (nen, co %). Tra ve duong dan neu biet."""
        try:
            app_dir = self.paths.app_dir
            music_dir = self.paths.music_dir
        except Exception as error:
            self.status = "Drive paths unavailable: %s" % error
            self.status_error = True
            return None
        existing = self._existing_offline_copy(entry)
        if existing:
            self._note_saved(entry, existing)
            self.status = "Already on this device - %s" % self._short_saved_name(entry, existing)
            self.status_error = False
            get_logger().info("drive offline already present=%s", existing)
            return existing
        try:
            job = drive_start_offline_job(
                app_dir, music_dir, album, entry, self._drive_api_key(),
            )
        except DriveError as error:
            self.status = self._drive_friendly_error("Drive download: %s" % error)
            self.status_error = True
            return None
        self.download_job = job
        if not job.done:
            # Job chay nen: vong lap chinh se ve thanh % va tra ve ngay.
            self.status = ""
        elif job.path:
            self._finish_offline_save(entry, job.path)
        else:
            self.status = self._drive_friendly_error("Drive download: %s" % job.error)
            self.status_error = True
        return job.path or None

    def _short_saved_name(self, entry, destination="", album=""):
        """Ten ngan de hien tren man hinh (duong dan day du qua dai)."""
        title = getattr(entry, "title", "") or (destination and os.path.basename(destination))
        title = str(title).rsplit(".", 1)[0]
        album = album or getattr(entry, "album", "")
        if not album:
            try:
                album = self._drive_album_label()
            except Exception:
                album = ""
        if album and album != "Drive":
            return "%s / %s" % (album, title)
        return title

    def _note_saved(self, entry, destination, album=""):
        self._saved_toast = (self._short_saved_name(entry, destination, album),
                             time.monotonic())

    def _finish_offline_save(self, entry, destination):
        job = getattr(self, "download_job", None)
        self.download_job = None
        self._invalidate_saved_rows()
        self._note_saved(entry, destination, getattr(job, "album", ""))
        self.status = "Saved: %s" % self._short_saved_name(entry, destination)
        self.status_error = False
        get_logger().info("drive offline saved=%s", destination)
        try:
            from .library import scan_library
            self.tracks = scan_library(self.paths.music_dir)
        except Exception as error:
            get_logger().warning("library rescan failed: %s", error)

    def _save_current_to_device(self):
        track = self.player.current if getattr(self, "player", None) else None
        if track is None:
            self.status = "Nothing is playing"
            self.status_error = True
            return False
        if not getattr(track, "path", "").startswith("drive://"):
            self.status = "Already on this device"
            self.status_error = False
            return True
        remainder = track.path[len("drive://"):]
        file_id = remainder.split("/", 1)[0]
        filename = remainder.split("/", 1)[1] if "/" in remainder else "track"
        known = next(
            (item for item in (getattr(self, "drive_entries", []) or [])
             if getattr(item, "file_id", "") == file_id),
            None,
        )
        if known is not None:
            entry = known
        else:
            import os as _os
            entry = DriveEntry(
                file_id=file_id,
                name=filename,
                mime_type="",
                size=0,
                is_folder=False,
                title=filename.rsplit(".", 1)[0],
                extension=_os.path.splitext(filename)[1].lower(),
            )
        self.status = "Downloading %s..." % entry.title
        self.status_error = False
        return self._save_entry_offline(entry, self._drive_album_label()) is not None

    def _maybe_prune_jobs(self):
        """Bom job Drive da xong de bang nho khong phinh to voi lan phat."""
        now = time.monotonic()
        if now - self._jobs_pruned_at < 60.0:
            return
        self._jobs_pruned_at = now
        try:
            drive_clear_finished_jobs()
        except Exception as error:
            get_logger().info("job prune skipped: %s", error)

    def _poll_offline_job(self):
        """Theo doi job luu offline chay nen; xong thi gan ten ngan vao header."""
        job = getattr(self, "download_job", None)
        if job is None or job.kind != "offline":
            return
        if job.running:
            return
        self.download_job = None
        entry = getattr(job, "entry", None)
        if job.error:
            self.status = self._drive_friendly_error("Drive download: %s" % job.error)
            self.status_error = True
            return
        self._finish_offline_save(entry or DriveEntry("", "", "", 0, False, "", ""), job.path)

    def _toggle_favorite(self):
        if getattr(self, "library_mode", "") == "source":
            return
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

    def _page_selection(self, step):
        if getattr(self, "library_mode", "") == "drive":
            count = len(self._drive_rows())
        elif getattr(self, "library_mode", "") == "source":
            count = 3
        else:
            count = len(self._library_entries())
        if count:
            self.selection = max(0, min(count - 1, self.selection + step * self.visible_rows()))
        get_logger().info("library page step=%d selection=%d", step, self.selection)

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
        elif self.screen == "addrive":
            self._render_addrive()
        elif self.screen == "lyrics":
            self._render_lyrics()
        else:
            self._render_playing()
        self._render_footer()
        self._render_saved_toast()
        self._render_download_progress()
        if self.exit_confirmation:
            self._render_exit_confirmation()
        if self.quick_menu:
            self._render_quick_menu()
        self.runtime.SDL_RenderPresent(self.renderer)

    def _toast_width(self):
        """Bề rộng ô "đã lưu" đang hiện (0 nếu không có), để chừa chỗ cho
        các mục khác khỏi bị đè lên nhau."""
        toast = getattr(self, "_saved_toast", None)
        if not toast:
            return 0
        if time.monotonic() - toast[1] > 8.0:
            return 0
        label = str(toast[0])
        if len(label) > 64:
            label = label[:61] + "..."
        return self.measure("SAVED  %s" % label, "small")[0] + 28 + 24 + 8

    def _render_saved_toast(self):
        """Dong 'da luu: <ten ngan>' ngay duoi tieu de (duong dan qua dai)."""
        toast = getattr(self, "_saved_toast", None)
        if not toast:
            return
        label, at = toast
        if time.monotonic() - at > 8.0:
            self._saved_toast = None
            return
        label = str(label)
        if len(label) > 64:
            label = label[:61] + "..."
        text = "SAVED  %s" % label
        font = "small"
        width = self.measure(text, font)[0] + 28
        x = max(8, self.width - width - 24)
        self.fill(x, 72, width, 26, self.PANEL)
        self.fill(x, 72, 3, 26, self.ACCENT)
        self.text(text, x + 14, 76, font, self.TEXT)

    def _render_download_progress(self):
        """Thanh % khi tai tu Drive. Luon co nut B de huy."""
        job = getattr(self, "download_job", None)
        if job is None:
            return
        percent = int(job.percent * 100)
        block_w = max(320, self.width - 160)
        block_h = 74
        x = (self.width - block_w) // 2
        y = self.height - 140
        self.fill(0, 0, self.width, self.height, self.BG)
        self.fill(x, y, block_w, block_h, self.PANEL)
        self.fill(x, y, 4, block_h, self.ACCENT)
        caption = "DOWNLOADING" if job.kind == "offline" else "BUFFERING"
        self.text(caption, x + 18, y + 8, "small", self.MUTED)
        self.text("%d%%" % percent, x + block_w - 70, y + 8, "small", self.ACCENT)
        title = self.ellipsize(job.title or "", block_w - 36, "small")
        self.text(title, x + 18, y + 26, "small", self.TEXT)
        bar_x, bar_y = x + 18, y + 50
        bar_w = block_w - 36
        self.fill(bar_x, bar_y, bar_w, 10, self.TRACK)
        if percent > 0:
            self.fill(bar_x, bar_y, max(10, int(bar_w * job.percent)), 10, self.ACCENT)
        note = "%s / %s   -   B cancel" % (
            drive_format_bytes(job.bytes),
            drive_format_bytes(job.total) if job.total > 0 else "?",
        )
        self.text(note, bar_x, bar_y + 16, "small", self.MUTED)

    def _version_label(self):
        return "v%s | ID: %s" % (APP_VERSION, self.install_id)

    def _play_intro(self):
        try:
            enabled = bool(self.settings.get("intro"))
        except Exception:
            enabled = True
        if not enabled:
            return
        glyphs = self._build_intro_glyphs()
        try:
            duration = 2.2
            start = time.monotonic()
            event = SDL_Event()
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    break
                while self.runtime.SDL_PollEvent(ctypes.byref(event)):
                    if event.type == SDL_QUIT:
                        get_logger().info("quit during intro")
                        self.running = False
                        return
                    try:
                        self.input.feed(event)
                    except Exception:
                        pass
                try:
                    if self.input.poll():
                        break
                except Exception:
                    pass
                self._render_intro_frame(min(1.0, elapsed / duration), glyphs)
                try:
                    self.runtime.SDL_Delay(16)
                except Exception:
                    break
        finally:
            self._free_intro_glyphs(glyphs)

    def _render_glyph(self, letter, font_name, color):
        try:
            font = self.fonts[font_name]
        except (KeyError, TypeError, AttributeError):
            return (None, 0, 0)
        surface = self.runtime.TTF_RenderUTF8_Blended(
            font, letter.encode("utf-8", "replace"), SDL_Color(*color)
        )
        if not surface:
            return (None, 0, 0)
        texture = self.runtime.SDL_CreateTextureFromSurface(self.renderer, surface)
        try:
            width, height = surface.contents.w, surface.contents.h
        except Exception:
            width, height = (0, 0)
        try:
            self.runtime.SDL_FreeSurface(surface)
        except Exception:
            pass
        if not texture:
            return (None, 0, 0)
        return (texture, width, height)

    def _blit_glyph(self, texture, x, y, width, height):
        if not texture or width <= 0 or height <= 0:
            return False
        try:
            target = SDL_Rect(int(x), int(y), int(width), int(height))
            self.runtime.SDL_RenderCopy(self.renderer, texture, None, ctypes.byref(target))
            return True
        except Exception:
            return False

    def _build_intro_glyphs(self):
        cache = {}
        try:
            colors = {
                "dark": (60, 5, 8, 255),
                "bright": self.INTRO_RED,
                "white": self.ON_ACCENT,
            }
        except Exception:
            return cache
        for letter in "NLK":
            for name, color in colors.items():
                try:
                    texture, width, height = self._render_glyph(letter, "giant", color)
                except Exception:
                    texture, width, height = (None, 0, 0)
                if texture:
                    cache[(letter, name)] = (texture, width, height)
        get_logger().info("intro glyphs cached=%d", len(cache))
        return cache

    def _free_intro_glyphs(self, glyphs):
        for texture, _width, _height in (glyphs or {}).values():
            try:
                if texture:
                    self.runtime.SDL_DestroyTexture(texture)
            except Exception:
                pass

    def _intro_letter_layout(self, font_name="hero", spacing=18):
        letters = "NLK"
        try:
            widths = [self.measure(letter, font_name)[0] for letter in letters]
        except Exception:
            widths = [60, 60, 60]
        total = sum(widths) + spacing * (len(letters) - 1)
        cursor = (self.width - total) // 2
        positions = []
        for letter, width in zip(letters, widths):
            positions.append((letter, cursor, width))
            cursor += width + spacing
        return positions

    def _intro_spread(self, progress):
        ease = min(1.0, max(0.0, progress / 0.55))
        return 4 + (30 - 4) * (1 - (1 - ease) * (1 - ease))

    def _render_intro_frame(self, progress, glyphs=None):
        progress = max(0.0, min(1.0, float(progress)))
        self.fill(0, 0, self.width, self.height, self.INTRO_BG)
        center_y = self.height // 2
        if glyphs:
            self._render_intro_glyphs(progress, glyphs)
        else:
            layout = self._intro_letter_layout()
            for index, (letter, x, _width) in enumerate(layout):
                enter_at = 0.05 + index * 0.16
                local = (progress - enter_at) / 0.30
                if local <= 0.0:
                    continue
                local = min(1.0, local)
                rise = int((1.0 - local) * 60)
                dark, bright = (60, 5, 8, 255), self.INTRO_RED
                blend = min(1.0, local * 1.5)
                color = tuple(
                    int(dark[channel] + (bright[channel] - dark[channel]) * blend)
                    for channel in range(3)
                ) + (255,)
                if local < 0.45:
                    font = "small"
                elif local < 0.75:
                    font = "body"
                else:
                    font = "hero"
                self.text(letter, x, center_y - 30 + rise, font, color)
            if progress > 0.72:
                sweep = (progress - 0.72) / 0.28
                for index, (letter, x, _width) in enumerate(layout):
                    center = index / 2.0
                    if abs(sweep - center * 0.9) < 0.18:
                        self.text(letter, x, center_y - 30, "hero", self.ON_ACCENT)
        try:
            self.runtime.SDL_RenderPresent(self.renderer)
        except Exception as error:
            get_logger().warning("intro present failed: %s", error)

    def _render_intro_glyphs(self, progress, glyphs):
        center_y = self.height // 2
        spacing = self._intro_spread(progress)
        try:
            widths = [glyphs[(letter, "bright")][1] for letter in "NLK"]
        except (KeyError, TypeError):
            try:
                widths = [self.measure(letter, "giant")[0] for letter in "NLK"]
            except Exception:
                widths = [180, 180, 180]
        total = sum(widths) + spacing * 2
        fit = min(1.0, (self.width - 80) / total) if total > 0 else 1.0
        cursor = (self.width - total * fit) // 2
        for index, letter in enumerate("NLK"):
            width = widths[index]
            try:
                _texture, tex_w, tex_h = glyphs[(letter, "bright")]
            except (KeyError, TypeError):
                cursor += (width + spacing) * fit
                continue
            if tex_w <= 0 or tex_h <= 0:
                cursor += (width + spacing) * fit
                continue
            dest_w, dest_h = tex_w * fit, tex_h * fit
            x = cursor + (width * fit - dest_w) // 2
            enter_at = 0.05 + index * 0.16
            local = (progress - enter_at) / 0.30
            if local > 0.0:
                local = min(1.0, local)
                rise = int((1.0 - local) * 90)
                if local > 0.65:
                    import math
                    rise += int(-14 * math.sin((local - 0.65) / 0.35 * math.pi))
                y = center_y - dest_h // 2 + rise
                bright = local * 1.5 >= 0.75
                if bright:
                    try:
                        glow, _gw, _gh = glyphs[(letter, "dark")]
                        self._blit_glyph(glow, x + 4 * fit, y + 6 * fit, dest_w, dest_h)
                    except (KeyError, TypeError):
                        pass
                    key = "bright"
                else:
                    key = "dark"
                try:
                    texture, _tw, _th = glyphs[(letter, key)]
                except (KeyError, TypeError):
                    texture = None
                self._blit_glyph(texture, x, y, dest_w, dest_h)
            cursor += (width + spacing) * fit
        if progress > 0.72:
            sweep = (progress - 0.72) / 0.28
            cursor = (self.width - total * fit) // 2
            for index, letter in enumerate("NLK"):
                width = widths[index]
                try:
                    texture, tex_w, tex_h = glyphs[(letter, "white")]
                except (KeyError, TypeError):
                    cursor += (width + spacing) * fit
                    continue
                center = index / 2.0
                if abs(sweep - center * 0.9) < 0.18:
                    self._blit_glyph(
                        texture, cursor + (width * fit - tex_w * fit) // 2,
                        center_y - tex_h * fit // 2, tex_w * fit, tex_h * fit,
                    )
                cursor += (width + spacing) * fit

    def _render_library(self):
        if getattr(self, "library_mode", "") == "drive":
            self._render_drive()
            return
        if getattr(self, "library_mode", "") == "source":
            self._render_source()
            return
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
            color = self.ON_ACCENT if selected else self.TEXT
            dim_color = self.ON_ACCENT if selected else self.MUTED
            spec_color = self.ON_ACCENT if selected else self.SPEC
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

    def _render_source(self):
        rows = [
            ("LOCAL", "%d tracks on this device" % len(getattr(self, "tracks", []) or [])),
            ("DRIVE", "%s (online)" % self._drive_slot_name()),
            ("+ Add Drive", "Link your own Drive folder"),
        ]
        try:
            self.text(
                self.ellipsize("Choose where your music plays from", self.width - 56, "small"),
                28, 74, "small", self.MUTED,
            )
        except Exception:
            pass
        y = 104
        for index, (title, detail) in enumerate(rows):
            selected = index == getattr(self, "selection", 0)
            if selected:
                self.fill(18, y - 5, self.width - 36, 48, self.ACCENT)
            color = self.ON_ACCENT if selected else self.TEXT
            dim_color = self.ON_ACCENT if selected else self.MUTED
            self.text(title, 32, y, "title", color)
            detail_width = self.measure(detail, "small")[0]
            self.text(detail, self.width - 32 - detail_width, y + 8, "small", dim_color)
            y += 52

    def _render_addrive(self):
        center_x = self.width // 2
        try:
            self.text("Scan with your phone", center_x, 78, "small", self.MUTED, center=True)
        except Exception:
            pass
        qr = getattr(self, "link_qr", None)
        url = getattr(self, "link_url", "") or ""
        size = int(getattr(qr, "size", 0) or 0)
        if qr is not None and size > 0:
            box = min(220, max(120, self.height - 340))
            cell = max(2, box // (size + 8))
            side = cell * (size + 8)
            left = center_x - side // 2
            top = 104
            self.fill(left, top, side, side, self.ON_ACCENT)
            pad = cell * 4
            for y in range(size):
                for x in range(size):
                    if qr.get(x, y):
                        self.fill(left + pad + x * cell, top + pad + y * cell, cell, cell, self.TEXT)
            text_top = top + side + 8
        else:
            text_top = 120
        try:
            self.text(
                self.ellipsize(url or "Starting link server...", self.width - 60, "small"),
                center_x, text_top, "small", self.ACCENT, center=True,
            )
            lines = (
                "1. Phone joins the same Wi-Fi as this player",
                "2. Scan the code or open the address above",
                "3. Paste your Drive folder link, press Save",
            )
            line_y = text_top + 24
            for line in lines:
                self.text(
                    self.ellipsize(line, self.width - 60, "small"),
                    center_x, line_y, "small", self.MUTED, center=True,
                )
                line_y += 22
        except Exception:
            pass

    def _render_drive(self):
        rows = self._drive_rows()
        try:
            crumb = self._drive_path_label()
            self.text(
                self.ellipsize(
                    str(crumb),
                    max(120, self.width - 56 - self._toast_width()),
                    "small",
                ),
                28, 74, "small", self.MUTED,
            )
        except Exception:
            pass
        if not rows:
            if getattr(self, "drive_busy", False):
                message, detail = "Loading Drive...", ""
            elif getattr(self, "drive_loaded", False):
                message, detail = "This Drive folder is empty", "This share has no audio files"
            else:
                message, detail = (
                    "No cached Drive data",
                    "Turn Wi-Fi on, then SELECT menu: Drive Refresh",
                )
            self.text(message, self.width // 2, self.height // 2 - 35, "hero", center=True)
            if detail:
                self.text(detail, self.width // 2, self.height // 2 + 25, "small", self.MUTED, center=True)
            return
        visible_rows = self.visible_rows()
        self.scroll = min(self.scroll, self.selection)
        if self.selection >= self.scroll + visible_rows:
            self.scroll = self.selection - visible_rows + 1
        spec_width = 150
        y = 104
        for index in range(self.scroll, min(len(rows), self.scroll + visible_rows)):
            selected = index == self.selection
            if selected:
                self.fill(18, y - 5, self.width - 36, 48, self.ACCENT)
            color = self.ON_ACCENT if selected else self.TEXT
            dim_color = self.ON_ACCENT if selected else self.MUTED
            spec_color = self.ON_ACCENT if selected else self.SPEC
            row = rows[index]
            if row == "__more__":
                title, detail, spec = "More... (next page)", "", ""
            elif getattr(row, "is_folder", False):
                title = "[%s]" % row.name
                detail = "folder"
                spec = ""
            else:
                title = row.title
                detail = row.name.rsplit(".", 1)[-1].upper() if "." in row.name else "AUDIO"
                try:
                    size_mb = float(row.size) / (1024 * 1024) if row.size else 0.0
                    spec = "%.1f MB" % size_mb if size_mb else ""
                except (TypeError, ValueError):
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
            if row != "__more__" and not getattr(row, "is_folder", False) \
                    and self._drive_row_is_saved(row):
                # Bai da co san tren may (ke ca o thu muc khac) -> danh dau
                # de khong tai trung.
                badge = "ON DEVICE"
                badge_w = self.measure(badge, "small")[0] + 16
                # measure() tra (width, height) -> phai lay [0] truoc khi cong.
                title_px = self.measure(
                    self.ellipsize(title, self.width - 400 - spec_width, "body"), "body",
                )[0]
                badge_x = 32 + title_px + 14
                if badge_x + badge_w < self.width - 300 - spec_width:
                    self.fill(badge_x, y + 3, badge_w, 20, self.ACCENT_SOFT)
                    self.text(badge, badge_x + 8, y + 5, "small", self.ACCENT)
            y += 52

    def _drive_row_is_saved(self, row):
        """Bai nay da duoc luu vao may chua (quet theo ten + kich thuoc)."""
        cache = getattr(self, "_saved_rows", None)
        if cache is None:
            cache = {}
            self._saved_rows = cache
        key = (getattr(row, "file_id", ""), getattr(row, "size", 0))
        if key in cache:
            return cache[key]
        value = bool(self._existing_offline_copy(row))
        cache[key] = value
        return value

    def _invalidate_saved_rows(self):
        self._saved_rows = {}
        try:
            from .drive import refresh_offline_index
            refresh_offline_index()
        except Exception:
            pass

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
        title_y = 70
        self.text(title_text, center_x, title_y, title_font, center=True)
        try:
            folder_text = self.ellipsize(track.folder or "", max_w, "small")
        except Exception:
            folder_text = track.folder or ""
        self.text(folder_text, center_x, title_y + 36, "small", self.MUTED, center=True)
        position = self.player.position()
        duration = self.player.duration()
        bar_x = 60
        bar_w = max(120, self.width - 120)
        prog_y = title_y + 64
        self.fill(bar_x, prog_y, bar_w, 8, self.TRACK)
        ratio = min(1.0, position / duration) if duration > 0 else 0.0
        self.fill(bar_x, prog_y, int(bar_w * ratio), 8, self.ACCENT)
        elapsed = self._format_time(position)
        total = self._format_time(duration) if duration else "--:--"
        times_y = prog_y + 10
        self.text(elapsed, bar_x, times_y, "small", self.MUTED)
        total_width = self.measure(total, "small")[0]
        self.text(total, bar_x + bar_w - total_width, times_y, "small", self.MUTED)
        self.text(
            self._audio_status_line(), center_x, times_y + 24, "small", self.MUTED, center=True,
        )
        content_bottom = times_y + 24 + 22
        status_top = self.height - 62 - 38
        spec_base = status_top - 20
        max_h = status_top - content_bottom - 32
        max_h = max(80, min(260, max_h))
        self._render_spectrum(spec_base, max_h, gain=3.0)

    def _drive_cached_path(self, track):
        try:
            path = getattr(track, "path", "")
            if not path.startswith("drive://"):
                return ""
            remainder = path[len("drive://"):]
            file_id = remainder.split("/", 1)[0]
            filename = remainder.split("/", 1)[1] if "/" in remainder else "track"
            import os as _os
            candidate = drive_stream_path(
                self.paths.data_dir, file_id, _os.path.splitext(filename)[1].lower()
            )
            return candidate if _os.path.isfile(candidate) else ""
        except Exception:
            return ""

    def _audio_status_line(self):
        track = self.player.current if getattr(self, "player", None) else None
        spec = ""
        if track is not None:
            try:
                codec = (getattr(track, "extension", "") or "").upper().lstrip(".")
            except Exception:
                codec = ""
            if not isinstance(codec, str):
                codec = ""
            probe = getattr(track, "path", "")
            if not isinstance(probe, str):
                probe = ""
            if probe.startswith("drive://"):
                probe = self._drive_cached_path(track) or probe
            try:
                spec = format_spec(probe)
            except Exception:
                spec = ""
            if not isinstance(spec, str):
                spec = ""
            if spec and codec and spec != codec and not spec.startswith(codec + " "):
                spec = "%s %s" % (codec, spec)
            elif not spec:
                spec = codec
        try:
            output_label = getattr(self.player, "output_device", "") or ""
        except Exception:
            output_label = ""
        if not isinstance(output_label, str):
            output_label = ""
        output_name = "USB DAC" if "USB" in output_label else "Built-in"
        if spec:
            return "%s   %s" % (spec, output_name)
        return output_name

    def _render_spectrum(self, baseline_y, max_h=160, gain=3.0):
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
            gain_value = max(1.0, min(4.0, float(gain)))
        except (TypeError, ValueError):
            gain_value = 3.0
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
                boosted = max(0.0, float(raw) * gain_value) ** 0.6
                level = max(0.0, min(1.0, boosted))
            except (TypeError, ValueError):
                level = 0.0
            try:
                boosted_peak = max(0.0, float(peaks[index]) * gain_value) ** 0.6
                peak = max(0.0, min(1.0, boosted_peak))
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
        visible = self._quick_menu_visible_rows()
        scroll = self._quick_menu_clamp_scroll()
        shown = entries[scroll:scroll + visible]
        width = min(680, self.width - 80)
        row_height = 52
        height = 102 + len(shown) * row_height
        x = (self.width - width) // 2
        y = (self.height - height) // 2
        self.fill(x - 4, y - 4, width + 8, height + 8, self.ACCENT)
        self.fill(x, y, width, height, self.PANEL)
        title = "EQUALIZER" if getattr(self, "quick_menu_page", "main") == "equalizer" else "QUICK MENU"
        self.text(title, self.width // 2, y + 22, "title", center=True)
        value_x = x + min(300, width // 2)
        for row, (_, label) in enumerate(shown):
            index = scroll + row
            row_y = y + 70 + row * row_height
            selected = index == self.quick_menu_selection
            if selected:
                self.fill(x + 24, row_y - 8, width - 48, 48, self.ACCENT)
            key_color = self.ON_ACCENT if selected else self.ACCENT
            value_color = self.ON_ACCENT if selected else self.TEXT
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
        self.fill(0, y, self.width, 2, self.ACCENT)
        state = "L2 SHUFFLE %s   R2 REPEAT %s" % (
            "ON" if self.settings.get("shuffle") else "OFF",
            str(self.settings.get("repeat")).upper(),
        )
        if self.sleep_timer.active:
            state += "   SLEEP %s" % self.sleep_timer.status()
        self.text(state, 24, y + 18, "small", self.MUTED)
        if self.screen == "library":
            if getattr(self, "library_mode", "") == "drive":
                hint = "A PLAY  X SAVE TO DEVICE  Y MUSIC"
            elif getattr(self, "library_mode", "") == "source":
                hint = "A OPEN  Y DRIVE"
            else:
                hint = "A OPEN/PLAY  X FAVORITE  Y VIEW"
        elif self.screen == "addrive":
            hint = "A RETRY  B BACK"
        elif self.screen == "lyrics":
            hint = "A PAUSE  X TRANSLATION  Y SAVE  SELECT MENU"
        else:
            hint = "A PAUSE  X FAVORITE  Y SAVE  SELECT MENU"
        hint_width = self.measure(hint, "small")[0]
        self.text(hint, self.width - 24 - hint_width, y + 18, "small")
        if self.status:
            color = self.ERROR if self.status_error else self.ACCENT
            self.fill(0, y - 38, self.width, 38, color)
            text_color = self.ON_ACCENT
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
        if self.screen == "addrive":
            return "ADD DRIVE"
        return {
            "all": "ALL SONGS",
            "favorites": "FAVORITE SONGS",
            "playlists": "PLAYLISTS",
            "favorite_playlists": "FAVORITE PLAYLISTS",
            "playlist_tracks": self.active_playlist.upper(),
            "drive": "DRIVE",
            "source": "MUSIC",
        }.get(self.library_mode, "LIBRARY")

    def _library_tracks(self):
        if getattr(self, "library_mode", "") == "drive":
            return [self._drive_track_for(item) for item in (getattr(self, "drive_entries", []) or []) if not item.is_folder]
        if getattr(self, "library_mode", "") == "source":
            return list(getattr(self, "tracks", []) or [])
        entries = self._library_entries()
        if self.library_mode in ("playlists", "favorite_playlists"):
            names = set(entries)
            return [track for track in self.tracks if track.folder in names]
        return entries

    @staticmethod
    def _format_time(seconds):
        seconds = max(0, int(seconds))
        return "%d:%02d" % (seconds // 60, seconds % 60)
