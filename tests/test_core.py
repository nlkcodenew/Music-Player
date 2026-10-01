import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
sys.path.insert(0, FILES)

from musicplayer.audio import AudioPlayer
from musicplayer.background import load_resume, save_background_session
from musicplayer import APP_VERSION
from musicplayer.audio_output import choose_audio_device, is_usb_audio_device
from musicplayer.collections import Collections
from musicplayer.display import DisplayController
from musicplayer.diagnostics import library_directories
from musicplayer.equalizer import Equalizer, preset_gains
from musicplayer.identity import installation_id
from musicplayer.library import natural_key, scan_library
from musicplayer.lyrics import load_lyrics, parse_lrc
from musicplayer.paths import RuntimePaths, detect_os
from musicplayer.reporter import _post_relay, _redact, _submit, queue_report, retry_pending
from musicplayer.settings import Settings
from musicplayer.sleep_timer import SleepTimer
from musicplayer.updater import apply_update, update_available, validate_manifest, version_tuple
from musicplayer.ui import MusicPlayerApp
from musicplayer import drive as drive_module
from musicplayer.drive import (
    DEFAULT_FOLDER_ID,
    DriveError,
    build_list_url,
    extract_folder_id,
    is_audio_name,
    media_url,
    offline_path,
    parse_list_response,
    public_download_url,
    sanitize_component,
)


class LibraryTests(unittest.TestCase):
    def test_scan_filters_hidden_and_unsupported_files(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "Album"))
            os.makedirs(os.path.join(root, ".cache"))
            for relative in (
                "10 song.mp3", "2 song.FLAC", "Album/track.ogg", "notes.txt",
                ".hidden.mp3", ".cache/cache.mp3",
            ):
                path = os.path.join(root, *relative.split("/"))
                with open(path, "wb") as handle:
                    handle.write(b"test")
            tracks = scan_library(root)
        self.assertEqual([track.title for track in tracks], ["2 song", "10 song", "track"])

    def test_natural_sort_orders_numbers_as_people_expect(self):
        values = ["track 10", "track 2", "track 1"]
        self.assertEqual(sorted(values, key=natural_key), ["track 1", "track 2", "track 10"])


class PathTests(unittest.TestCase):
    def test_infers_sd_root_from_stock_apps_directory(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "Apps", "MusicPlayer")
            os.makedirs(app_dir)
            os.makedirs(os.path.join(root, "Music"))
            paths = RuntimePaths.discover(app_dir=app_dir, environ={})
        self.assertEqual(paths.sdcard_path, root)

    def test_infers_sd_root_from_spruce_app_directory(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "App", "MusicPlayer")
            os.makedirs(app_dir)
            os.makedirs(os.path.join(root, "Music"))
            paths = RuntimePaths.discover(app_dir=app_dir, environ={})
        self.assertEqual(paths.sdcard_path, root)

    def test_detects_spruce_from_environment(self):
        self.assertEqual(detect_os("/missing", {"MUSIC_PLAYER_OS": "spruce"}), "spruce")

    def test_defaults_to_stock_without_markers(self):
        self.assertEqual(detect_os("/missing", {}), "stock")

    def test_launcher_log_path_is_preserved_for_issue_reports(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "Apps", "MusicPlayer")
            os.makedirs(app_dir)
            os.makedirs(os.path.join(root, "Music"))
            launcher_log = os.path.join(root, "Logs", "MusicPlayer.txt")
            paths = RuntimePaths.discover(
                app_dir=app_dir,
                environ={"MUSIC_PLAYER_STDIO_LOG": launcher_log},
            )
        self.assertEqual(paths.stdio_log_file, launcher_log)

    def test_spruce_prefers_native_sdl_runtime_over_mali_runtime(self):
        paths = mock.Mock(
            app_dir="/sd/App/MusicPlayer",
            sdcard_path="/sd",
            os_name="spruce",
        )
        directories = library_directories(paths)
        native_sdl = os.path.join("/sd", "spruce", "brick", "sdl2")
        mali_runtime = os.path.join("/sd", "App", "PyUI", "dll-mali")
        self.assertLess(directories.index(native_sdl), directories.index(mali_runtime))
        self.assertLess(directories.index("/usr/lib"), directories.index(mali_runtime))


class SettingsTests(unittest.TestCase):
    def test_invalid_values_are_normalized_and_saved_atomically(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"volume": 999, "repeat": "bad", "shuffle": 1}, handle)
            settings = Settings(path).load()
            self.assertEqual(settings.get("volume"), 100)
            self.assertEqual(settings.get("repeat"), "off")
            self.assertTrue(settings.get("shuffle"))
            settings.set("volume", 55)
            settings.save()
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["volume"], 55)

    def test_equalizer_and_output_values_are_normalized(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "eq_preset": "Unknown", "eq_bass": 99,
                    "eq_mid": -99, "audio_output": "invalid",
                }, handle)
            settings = Settings(path).load()
        self.assertEqual(settings.get("eq_preset"), "Flat")
        self.assertEqual(settings.get("eq_bass"), 6)
        self.assertEqual(settings.get("eq_mid"), -6)
        self.assertEqual(settings.get("audio_output"), "auto")

class AudioOutputTests(unittest.TestCase):
    def test_auto_and_usb_modes_prefer_usb_dac(self):
        devices = ["ALSA Default", "FiiO USB DAC"]
        self.assertTrue(is_usb_audio_device(devices[1]))
        self.assertEqual(choose_audio_device(devices, "auto"), devices[1])
        self.assertEqual(choose_audio_device(devices, "usb"), devices[1])
        self.assertIsNone(choose_audio_device(devices, "system"))

    def test_usb_mode_falls_back_when_dac_is_absent(self):
        self.assertIsNone(choose_audio_device(["ALSA Default"], "usb"))

class EqualizerTests(unittest.TestCase):
    def test_presets_and_custom_gains_are_bounded(self):
        self.assertEqual(preset_gains("Bass Boost"), (5, 0, 0))
        self.assertEqual(preset_gains("Custom", (20, -20, 2)), (6, -6, 2))

    def test_flat_does_not_install_audio_callback(self):
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        settings = mock.Mock()
        values = {"eq_preset": "Flat", "eq_bass": 0, "eq_mid": 0, "eq_treble": 0}
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        equalizer = Equalizer(runtime, settings)
        self.assertTrue(equalizer.sync())
        self.assertFalse(equalizer.installed)
        runtime.Mix_SetPostMix.assert_not_called()

    def test_non_flat_installs_and_processes_pcm(self):
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        settings = mock.Mock()
        values = {"eq_preset": "Rock", "eq_bass": 0, "eq_mid": 0, "eq_treble": 0}
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        equalizer = Equalizer(runtime, settings)
        self.assertTrue(equalizer.sync())
        self.assertTrue(equalizer.installed)
        source = (b"\x00\x10\x00\x10") * 128
        output = equalizer.process(source)
        self.assertEqual(len(output), len(source))
        self.assertNotEqual(output, source)

    def test_custom_adjustment_inherits_active_preset(self):
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        settings = mock.Mock()
        values = {"eq_preset": "Rock", "eq_bass": 0, "eq_mid": 0, "eq_treble": 0}
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        equalizer = Equalizer(runtime, settings)
        equalizer.adjust("mid", 1)
        self.assertEqual(equalizer.preset, "Custom")
        self.assertEqual(equalizer.gains, (4, 2, 3))

class CollectionTests(unittest.TestCase):
    def test_favorites_and_folder_playlists_persist(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "collections.json")
            collections = Collections(path)
            self.assertTrue(collections.toggle_track(os.path.join(root, "song.mp3")))
            self.assertTrue(collections.toggle_playlist("Album One"))
            collections.save()
            loaded = Collections(path).load()
            tracks = [
                mock.Mock(path=os.path.join(root, "song.mp3"), folder="Music"),
                mock.Mock(path=os.path.join(root, "album.mp3"), folder="Album One"),
            ]
            self.assertTrue(loaded.is_track_favorite(os.path.join(root, "song.mp3")))
            self.assertEqual(loaded.playlists(tracks), ["Album One"])
            self.assertEqual(loaded.playlists(tracks, favorites_only=True), ["Album One"])


class ReporterTests(unittest.TestCase):
    def test_redacts_token_paths_and_mac(self):
        paths = mock.Mock(
            app_dir="/sd/Apps/MusicPlayer", sdcard_path="/sd", music_dir="/sd/Music"
        )
        text = "Authorization: Bearer secret /sd/Music/private-song.mp3\naa:bb:cc:dd:ee:ff github_pat_ABC"
        redacted = _redact(text, paths, ("secret",))
        self.assertNotIn("secret", redacted)
        self.assertNotIn("github_pat_ABC", redacted)
        self.assertIn("$MUSIC/[PATH REDACTED]", redacted)
        self.assertNotIn("private-song", redacted)
        self.assertIn("[MAC]", redacted)

    def test_queue_deduplicates_same_reason(self):
        with tempfile.TemporaryDirectory() as root:
            paths = mock.Mock(
                data_dir=root,
                pending_reports_file=os.path.join(root, "pending.json"),
                log_file=os.path.join(root, "log.txt"),
            )
            first = queue_report(paths, "same_reason", "first")
            second = queue_report(paths, "same_reason", "second")
            with open(paths.pending_reports_file, encoding="utf-8") as handle:
                pending = json.load(handle)
            self.assertEqual(first, second)
            self.assertEqual(len(pending), 1)

    def test_installation_id_is_stable(self):
        with tempfile.TemporaryDirectory() as root:
            paths = mock.Mock(data_dir=root)
            first = installation_id(paths)
            second = installation_id(paths)
        self.assertRegex(first, r"^MP-[A-F0-9]{8}$")
        self.assertEqual(first, second)

    def test_manual_reports_are_unique_and_snapshot_session_log(self):
        with tempfile.TemporaryDirectory() as root:
            session_log = os.path.join(root, "session.log")
            with open(session_log, "w", encoding="utf-8") as handle:
                handle.write("complete current session")
            paths = mock.Mock(
                pending_reports_file=os.path.join(root, "pending.json"),
                session_log_file=session_log,
                log_file=os.path.join(root, "app.log"),
                stdio_log_file="",
            )
            first = queue_report(paths, "manual_diagnostic", unique=True)
            second = queue_report(paths, "manual_diagnostic", unique=True)
            with open(paths.pending_reports_file, encoding="utf-8") as handle:
                pending = json.load(handle)
        self.assertNotEqual(first, second)
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["session_log"], "complete current session")

    def test_long_session_log_continues_in_relay_comments(self):
        with tempfile.TemporaryDirectory() as root:
            paths = mock.Mock(
                app_dir=os.path.join(root, "MusicPlayer"),
                sdcard_path=root,
                music_dir=os.path.join(root, "Music"),
                data_dir=os.path.join(root, "data"),
                os_name="stock",
            )
            os.makedirs(paths.app_dir)
            item = {
                "reason": "manual_diagnostic",
                "detail": "Submitted with SELECT",
                "fingerprint": "123456789abc",
                "session_log": "x" * (90 * 1024),
            }
            with mock.patch("musicplayer.reporter.installation_id", return_value="MP-A1B2C3D4"), \
                    mock.patch("musicplayer.reporter._post_json") as request:
                _submit(paths, item, "https://reports.example.test/report")

        calls = request.call_args_list
        self.assertEqual(len(calls), 1)
        payload = calls[0].args[2]
        self.assertEqual(len(payload["comments"]), 2)
        self.assertIn("Session log part 3/3", payload["comments"][1])
        self.assertIn("MP-A1B2C3D4", payload["title"])

    def test_relay_request_has_no_github_authorization(self):
        paths = mock.Mock(app_dir="/app")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"accepted": true}'
        response.__exit__.return_value = False
        with mock.patch("musicplayer.reporter.verified_context", return_value=None), \
                mock.patch("musicplayer.reporter.urllib.request.urlopen", return_value=response) as open_url:
            _post_relay(
                paths, "https://reports.example.test/report", "[device-log] test",
                "body", [], "a" * 64,
            )
        request = open_url.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["app"], "trimui-music-player")

    def test_automatic_retry_requires_opt_in(self):
        with tempfile.TemporaryDirectory() as root:
            paths = mock.Mock(
                app_dir=root,
                settings_file=os.path.join(root, "settings.json"),
                pending_reports_file=os.path.join(root, "pending.json"),
            )
            with open(paths.pending_reports_file, "w", encoding="utf-8") as handle:
                json.dump([{"reason": "error"}], handle)
            with mock.patch("musicplayer.reporter._submit") as submit:
                self.assertFalse(retry_pending(paths))
            submit.assert_not_called()


class UpdaterTests(unittest.TestCase):
    def test_rejects_path_traversal_and_protected_files(self):
        base = {"version": "9.0", "base_url": "https://example.test/files"}
        for path in ("../escape", "/absolute", "secrets.json", "data/settings.json"):
            manifest = dict(base, files=[{"path": path, "sha256": "0" * 64, "size": 1}])
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

        manifest["files"][0]["path"] = "data/display-restore.json"
        with self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_version_comparison(self):
        self.assertEqual(version_tuple("v1.10.2"), (1, 10, 2))
        self.assertTrue(update_available({"version": "99.0.0"}))

    def test_update_stays_inside_installed_app_directory(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "Apps", "MusicPlayer")
            data_dir = os.path.join(app_dir, "data")
            os.makedirs(data_dir)
            paths = mock.Mock(app_dir=app_dir, data_dir=data_dir)
            manifest = {
                "version": "1.1.0",
                "base_url": "https://example.test/files",
                "files": [{"path": "config.json", "sha256": "0" * 64, "size": 3}],
            }

            def stage_file(unused_paths, unused_manifest, unused_item, staging):
                destination = os.path.join(staging, "config.json")
                with open(destination, "wb") as handle:
                    handle.write(b"new")
                return "config.json"

            with mock.patch("musicplayer.updater._download_file", side_effect=stage_file):
                apply_update(paths, manifest)

            with open(os.path.join(app_dir, "config.json"), "rb") as handle:
                self.assertEqual(handle.read(), b"new")
            self.assertTrue(os.path.isfile(os.path.join(app_dir, ".restart")))
            self.assertFalse(os.path.exists(os.path.join(root, "App", "MusicPlayer")))

class UiLogicTests(unittest.TestCase):
    def test_release_version_is_visible_in_header_format(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.install_id = "MP-A1B2C3D4"
        self.assertEqual(app._version_label(), "v%s | ID: MP-A1B2C3D4" % APP_VERSION)

    def test_quick_menu_can_enable_automatic_error_reports(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"auto_report_errors": False, "audio_output": "auto"}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        app.quick_menu = True
        app.quick_menu_page = "main"
        app.status = ""
        app.status_error = False
        app.quick_menu_selection = next(
            index for index, entry in enumerate(app._quick_menu_entries())
            if entry[0] == "auto_report"
        )
        app._handle_quick_menu("a")
        self.assertTrue(values["auto_report_errors"])
        app.settings.save.assert_called_once()

    def test_equalizer_menu_changes_preset(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {
            "eq_preset": "Flat", "eq_bass": 0, "eq_mid": 0, "eq_treble": 0,
        }
        settings = mock.Mock()
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        app.player = mock.Mock(equalizer=Equalizer(runtime, settings))
        app.status = ""
        app.status_error = False

        app._handle_equalizer_menu("eq_preset", "right")
        self.assertEqual(app.player.equalizer.preset, "Bass Boost")
        self.assertEqual(app.player.equalizer.gains, (5, 0, 0))
        self.assertFalse(app.status_error)

    def test_audio_output_change_is_saved_for_next_launch(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"audio_output": "auto"}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.status = ""
        app.status_error = False

        app._cycle_audio_output(1)
        self.assertEqual(values["audio_output"], "system")
        app.settings.save.assert_called_once()
        self.assertIn("next launch", app.status)

    def test_select_opens_quick_menu_without_sending_diagnostics(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.update_busy = False
        app.update_manifest = None
        app.quick_menu = False
        app.quick_menu_selection = 0
        app.exit_confirmation = False
        app.screen = "library"

        with mock.patch.object(app, "_send_diagnostic") as send_diagnostic:
            app._handle("select")
        self.assertTrue(app.quick_menu)
        send_diagnostic.assert_not_called()

    def test_quick_menu_cycles_sleep_timer(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.update_manifest = None
        app.quick_menu = True
        app.quick_menu_page = "main"
        app.sleep_timer = SleepTimer(clock=lambda: 100.0)
        app.player = mock.Mock(current=mock.Mock(path="/music/song.mp3"))
        app.player.equalizer.preset = "Flat"
        app.settings = mock.Mock()
        app.settings.get.return_value = "auto"
        app.status = ""
        app.status_error = False

        app.quick_menu_selection = next(
            index for index, entry in enumerate(app._quick_menu_entries()) if entry[0] == "sleep"
        )
        app._handle_quick_menu("a")
        self.assertEqual(app.sleep_timer.label, "15 min")
        self.assertTrue(app.quick_menu)

    def test_library_back_requires_exit_confirmation(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.update_busy = False
        app.update_manifest = None
        app.exit_confirmation = False
        app.screen = "library"
        app.library_mode = "all"
        app.active_playlist = ""
        app.selection = 3
        app.scroll = 2
        app.running = True

        app._handle("b")
        self.assertEqual(app.library_mode, "source")
        self.assertFalse(app.exit_confirmation)
        self.assertTrue(app.running)

        app._handle("b")
        self.assertTrue(app.exit_confirmation)
        self.assertTrue(app.running)

        app._handle("b")
        self.assertFalse(app.exit_confirmation)
        self.assertTrue(app.running)

        app._handle("b")
        app._handle("a")
        self.assertFalse(app.running)

    def test_source_root_offers_local_and_drive(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.update_busy = False
        app.update_manifest = None
        app.exit_confirmation = False
        app.screen = "library"
        app.library_mode = "source"
        app.active_playlist = ""
        app.tracks = [mock.Mock(path="/m/a.mp3")]
        app.selection = 0
        app.scroll = 0
        app.drive_stack = []
        app.drive_entries = []
        app.drive_page_token = ""
        app.drive_loaded = False
        app.drive_busy = False

        self.assertEqual(app._screen_title(), "MUSIC")
        app._handle("a")
        self.assertEqual(app.library_mode, "all")

        app._handle("b")
        self.assertEqual(app.library_mode, "source")

        app.selection = 1
        with mock.patch.object(app, "_drive_refresh") as refresh:
            app._handle("a")
        self.assertEqual(app.library_mode, "drive")
        refresh.assert_called_once()

        app._handle("y")
        self.assertEqual(app.library_mode, "source")
        with mock.patch.object(app, "_drive_refresh"):
            app._handle("y")
        self.assertEqual(app.library_mode, "drive")

    def test_source_rows_ignore_favorite_toggle(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.screen = "library"
        app.library_mode = "source"
        app.collections = mock.Mock()
        app.selection = 0
        app._toggle_favorite()
        app.collections.toggle_track.assert_not_called()
        app.collections.toggle_playlist.assert_not_called()

    def test_library_modes_and_favorite_selection_are_safe(self):
        first = mock.Mock(path="/music/one.mp3", folder="Album", title="One")
        second = mock.Mock(path="/music/two.mp3", folder="Album", title="Two")
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.tracks = [first, second]
        app.collections = Collections("")
        app.screen = "library"
        app.library_mode = "all"
        app.playlist_parent_mode = "playlists"
        app.active_playlist = ""
        app.selection = 1
        app.scroll = 0
        app.status = ""
        app.status_error = False

        with mock.patch.object(app.collections, "save"):
            app._toggle_favorite()
            app.library_mode = "favorites"
            self.assertEqual(app._library_entries(), [second])
            app._toggle_favorite()
        self.assertEqual(app.selection, 0)
        self.assertEqual(app._library_entries(), [])

        app._cycle_library_mode()
        self.assertEqual(app.library_mode, "playlists")
        self.assertEqual(app._library_entries(), ["Album"])

class LyricsTests(unittest.TestCase):
    def test_parses_metadata_offset_duplicate_and_multiple_timestamps(self):
        lines = parse_lrc(
            "[ar:Artist]\n[offset:250]\n[00:01.00][00:02.5]Hello\n[00:01.00]Again\n"
        )
        self.assertEqual(
            [(round(line.timestamp, 2), line.text) for line in lines],
            [(1.25, "Hello"), (1.25, "Again"), (2.75, "Hello")],
        )

    def test_loads_translation_and_selects_current_line(self):
        with tempfile.TemporaryDirectory() as root:
            track = os.path.join(root, "Song.mp3")
            with open(track, "wb") as handle:
                handle.write(b"")
            with open(os.path.join(root, "Song.lrc"), "w", encoding="utf-8") as handle:
                handle.write("[00:01.00]One\n[00:04.00]Two\n")
            with open(os.path.join(root, "Song.vi.lrc"), "w", encoding="utf-8") as handle:
                handle.write("[00:01.00]Mot\n[00:04.00]Hai\n")
            lyrics = load_lyrics(track)
        self.assertEqual(lyrics.current_index(0.5), -1)
        self.assertEqual(lyrics.current_index(4.2), 1)
        self.assertEqual(lyrics.languages, ["vi"])
        self.assertEqual(lyrics.translation(1, "vi"), "Hai")

class SleepTimerTests(unittest.TestCase):
    def test_countdown_expires_and_can_be_cancelled(self):
        now = [100.0]
        timer = SleepTimer(clock=lambda: now[0])
        timer.set(1)
        self.assertEqual(timer.remaining(), 900)
        now[0] = 999.5
        self.assertFalse(timer.expired())
        now[0] = 1000.0
        self.assertTrue(timer.expired())
        timer.cancel()
        self.assertFalse(timer.active)

    def test_end_of_track_uses_the_track_active_when_set(self):
        timer = SleepTimer()
        timer.set(6, "/music/one.mp3")
        self.assertFalse(timer.expired("/music/one.mp3", playing=True))
        self.assertTrue(timer.expired("/music/two.mp3", playing=True))
        self.assertTrue(timer.expired("/music/one.mp3", playing=False, paused=False))

class DisplayTests(unittest.TestCase):
    def test_screen_off_records_and_restores_exact_brightness(self):
        with tempfile.TemporaryDirectory() as root:
            recovery = os.path.join(root, "display-restore.json")
            display = DisplayController(device_path="/dev/test", recovery_file=recovery)
            calls = []
            with mock.patch.object(
                DisplayController, "supported", new_callable=mock.PropertyMock, return_value=True
            ), mock.patch.object(
                display, "_saved_brightness", return_value=87
            ), mock.patch.object(
                display, "_ioctl", side_effect=lambda command, value=0: calls.append(value) or True
            ):
                self.assertTrue(display.screen_off())
                self.assertTrue(os.path.isfile(recovery))
                self.assertTrue(display.restore())
            self.assertEqual(calls, [0, 87])
            self.assertFalse(os.path.exists(recovery))

    def test_prepared_screen_off_does_not_write_recovery_during_playback(self):
        with tempfile.TemporaryDirectory() as root:
            recovery = os.path.join(root, "display-restore.json")
            display = DisplayController(device_path="/dev/test", recovery_file=recovery)
            calls = []
            with mock.patch.object(
                type(display), "supported", new_callable=mock.PropertyMock, return_value=True
            ), mock.patch.object(
                display, "_saved_brightness", return_value=99
            ), mock.patch.object(
                display, "_ioctl", side_effect=lambda command, value=0: calls.append(value) or True
            ):
                self.assertTrue(display.prepare())
                recovery_time = os.path.getmtime(recovery)
                self.assertTrue(display.screen_off())
                self.assertEqual(os.path.getmtime(recovery), recovery_time)
            self.assertEqual(calls, [0])

    def test_reads_stock_brightness_key(self):
        display = DisplayController()
        stock_path = "/mnt/UDISK/system.json"
        real_open = open

        def fake_open(path, *args, **kwargs):
            if path == stock_path:
                return mock.mock_open(read_data='{"brightness": 6}').return_value
            raise FileNotFoundError(path)

        with mock.patch("builtins.open", side_effect=fake_open):
            self.assertEqual(display._saved_brightness(), 142)


class FakeRuntime:
    def __init__(self):
        self.paused = False

    def Mix_VolumeMusic(self, value):
        self.volume = value

    def Mix_PausedMusic(self):
        return self.paused

    def Mix_PauseMusic(self):
        self.paused = True

    def Mix_ResumeMusic(self):
        self.paused = False

class FakeAudioRuntime(FakeRuntime):
    def __init__(self, results):
        super().__init__()
        self.results = list(results)
        self.attempts = []
        self.Mix_Init = lambda flags: flags
        self.Mix_OpenAudioDevice = self.open_audio_device
        self.Mix_SetPostMix = None
        self.Mix_HookMusicFinished = None
        self.Mix_Quit = None

    def audio_devices(self):
        return []

    def open_audio_device(self, frequency, audio_format, channels, buffer_size, device, changes):
        self.attempts.append((frequency, buffer_size, device, changes))
        return self.results.pop(0) if self.results else -1

    def Mix_OpenAudio(self, frequency, audio_format, channels, buffer_size):
        raise AssertionError("Mix_OpenAudioDevice should be preferred")

    def mixer_spec(self):
        return (44100, 0x8010, 2)

    def error(self):
        return "Operation not permitted"

    def Mix_CloseAudio(self):
        self.closed = True


class AudioLogicTests(unittest.TestCase):
    @staticmethod
    def audio_settings():
        values = {
            "volume": 80, "audio_output": "system", "eq_preset": "Flat",
            "eq_bass": 0, "eq_mid": 0, "eq_treble": 0,
        }
        settings = mock.Mock()
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        return settings

    def test_audio_negotiation_uses_next_configuration(self):
        runtime = FakeAudioRuntime([-1, 0])
        player = AudioPlayer(runtime, [], self.audio_settings())
        self.assertTrue(player.initialize())
        self.assertTrue(player.audio_ready)
        self.assertEqual([attempt[:2] for attempt in runtime.attempts], [(44100, 1024), (48000, 1024)])
        self.assertEqual(player.sample_rate, 44100)
        self.assertEqual(player.equalizer.sample_rate, 44100)

    def test_audio_failure_does_not_raise_or_block_ui_startup(self):
        runtime = FakeAudioRuntime([-1] * 10)
        player = AudioPlayer(runtime, [], self.audio_settings())
        self.assertFalse(player.initialize())
        self.assertFalse(player.audio_ready)
        self.assertIn("Audio unavailable", player.output_warning)
        self.assertFalse(player.play(0))

    def test_transient_not_playing_state_does_not_restart_with_finished_hook(self):
        runtime = FakeRuntime()
        runtime.Mix_HookMusicFinished = mock.Mock()
        runtime.Mix_PlayingMusic = mock.Mock(return_value=0)
        player = AudioPlayer(runtime, [mock.Mock(title="Song")], self.audio_settings())
        player.audio_ready = True
        player.started = True
        player.music = object()
        player.index = 0
        player.last_state_log = float("inf")
        player._install_finished_callback()

        with mock.patch.object(player, "advance") as advance:
            player.update()
            advance.assert_not_called()
            player.finished_callback()
            with mock.patch.object(player, "position", return_value=120.0), \
                    mock.patch.object(player, "duration", return_value=120.0):
                player.update()
            advance.assert_called_once_with(True, automatic=True)

    def test_background_session_preserves_queue_position_and_sleep_timer(self):
        with tempfile.TemporaryDirectory() as root:
            first = os.path.join(root, "one.mp3")
            second = os.path.join(root, "two.mp3")
            for path in (first, second):
                with open(path, "wb") as handle:
                    handle.write(b"audio")
            paths = mock.Mock(data_dir=root)
            player = mock.Mock()
            player.current = mock.Mock(path=second)
            player.music = object()
            player.tracks = [mock.Mock(path=first), player.current]
            player.position.return_value = 42.5
            player.runtime.Mix_PausedMusic.return_value = 0
            timer = SleepTimer(clock=lambda: 100.0)
            timer.set(1)

            self.assertTrue(save_background_session(paths, player, timer))
            session_path = os.path.join(root, "background-session.json")
            with open(session_path, encoding="utf-8") as handle:
                session = json.load(handle)

        self.assertEqual(session["tracks"], [first, second])
        self.assertEqual(session["current_path"], second)
        self.assertEqual(session["position"], 42.5)
        self.assertEqual(session["sleep_timer"]["remaining"], 900)

    def test_background_status_is_resume_fallback_after_forced_stop(self):
        with tempfile.TemporaryDirectory() as root:
            paths = mock.Mock(data_dir=root)
            status = {"track_path": "/music/song.mp3", "position": 81.0, "paused": False}
            status_path = os.path.join(root, "background-status.json")
            with open(status_path, "w", encoding="utf-8") as handle:
                json.dump(status, handle)

            self.assertEqual(load_resume(paths), status)
            self.assertFalse(os.path.exists(status_path))

    def test_pause_and_resume(self):
        runtime = FakeRuntime()
        player = AudioPlayer(runtime, [], mock.Mock())
        player.music = object()
        player.started_at = 1.0
        with mock.patch.object(player, "position", return_value=12.5):
            self.assertTrue(player.toggle_pause())
        self.assertTrue(runtime.paused)
        self.assertEqual(player.paused_at, 12.5)
        self.assertFalse(player.toggle_pause())
        self.assertFalse(runtime.paused)

    def test_repeat_navigation(self):
        tracks = [mock.Mock(path=str(index), title=str(index)) for index in range(3)]
        settings = mock.Mock()
        values = {"repeat": "off", "shuffle": False, "volume": 80}
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        player = AudioPlayer(FakeRuntime(), tracks, settings)
        player.index = 2
        self.assertEqual(player.next_index(True, automatic=True), -1)
        values["repeat"] = "all"
        self.assertEqual(player.next_index(True, automatic=True), 0)
        values["repeat"] = "one"
        self.assertEqual(player.next_index(True, automatic=True), 2)


class VisualsTapTests(unittest.TestCase):
    def test_flat_with_analyser_installs_visual_tap(self):
        import struct
        from musicplayer.equalizer import Equalizer
        from musicplayer.visuals import SpectrumAnalyser
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        settings = mock.Mock()
        values = {"eq_preset": "Flat", "eq_bass": 0, "eq_mid": 0, "eq_treble": 0}
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        equalizer = Equalizer(runtime, settings)
        self.assertTrue(equalizer.sync())
        self.assertFalse(equalizer.installed)
        analyser = SpectrumAnalyser()
        equalizer.attach_analyser(analyser)
        self.assertTrue(equalizer.installed)
        runtime.Mix_SetPostMix.assert_called()
        pcm = struct.pack("<512h", *([1200] * 256 + [-1200] * 256))
        equalizer.analyser.offer(pcm)
        levels, rms, _beat = equalizer.analyser.snapshot()
        self.assertEqual(len(levels), 14)
        self.assertGreater(rms, 0.0)
        equalizer.detach_analyser()
        self.assertFalse(equalizer.installed)

    def test_analyser_decay_reduces_levels(self):
        import struct
        from musicplayer.visuals import SpectrumAnalyser
        analyser = SpectrumAnalyser()
        pcm = struct.pack("<512h", *([4000] * 512))
        for _ in range(5):
            analyser.offer(pcm)
            analyser._last_tap = 0.0
        before = list(analyser.snapshot()[0])
        analyser.decay()
        after = list(analyser.snapshot()[0])
        self.assertTrue(any(a < b for a, b in zip(after, before)))

    def test_audio_player_owns_analyser_and_resets(self):
        from musicplayer.audio import AudioPlayer
        from musicplayer.visuals import SpectrumAnalyser
        runtime = mock.Mock(Mix_SetPostMix=mock.Mock())
        values = {
            "volume": 80, "audio_output": "system", "eq_preset": "Flat",
            "eq_bass": 0, "eq_mid": 0, "eq_treble": 0,
        }
        settings = mock.Mock()
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        player = AudioPlayer(runtime, [], settings)
        self.assertIsInstance(player.analyser, SpectrumAnalyser)
        player.analyser.levels = [0.9] * player.analyser.bands
        player.stop()
        self.assertTrue(all(v < 0.9 for v in player.analyser.levels))


class LedControllerTests(unittest.TestCase):
    def test_frame_for_levels_returns_rgb_hex(self):
        from musicplayer.leds import frame_for_levels
        frame = frame_for_levels([0.0, 0.5, 1.0], 0.1, False, 3, slots=3)
        self.assertEqual(len(frame), 21)
        self.assertRegex(frame, r"^[0-9A-F ]+$")
        self.assertTrue(frame.endswith(" "))
        beat_frame = frame_for_levels([0.5] * 4, 0.2, True, 1)
        self.assertIn("FFFFFF", beat_frame)

    def test_full_frame_covers_all_driver_slots(self):
        from musicplayer.leds import FRAME_SLOTS, frame_for_levels
        frame = frame_for_levels([0.5] * 14, 0.2, False, 3)
        parts = frame.split()
        self.assertEqual(len(parts), FRAME_SLOTS)
        self.assertTrue(frame.endswith(" "))
        self.assertEqual(FRAME_SLOTS, 23)

    def test_single_led_frame_lights_one_position(self):
        from musicplayer.leds import FRAME_SLOTS, frame_single
        frame = frame_single(5)
        parts = frame.split()
        self.assertEqual(len(parts), FRAME_SLOTS)
        self.assertEqual(parts[5], "FFFFFF")
        self.assertEqual(parts.count("000000"), FRAME_SLOTS - 1)

    def test_controller_without_nodes_is_unavailable_but_safe(self):
        from musicplayer.leds import LedController
        leds = LedController(frame_path="/missing/frame_hex", effect_path="/missing/effect")
        leds.frame_path = ""
        leds.effect_path = ""
        leds.enabled = False
        self.assertFalse(leds.available)
        self.assertFalse(leds.update([0.5] * 14, 0.1, False))
        self.assertFalse(leds.suspend_engine())

    def test_controller_suspend_restore_with_temp_files(self):
        import tempfile
        from musicplayer.leds import LedController
        with tempfile.TemporaryDirectory() as root:
            frame = os.path.join(root, "frame_hex")
            effect = os.path.join(root, "effect_enable")
            with open(frame, "w") as handle:
                handle.write("")
            with open(effect, "w") as handle:
                handle.write("1")
            leds = LedController(frame_path=frame, effect_path=effect)
            self.assertTrue(leds.available)
            self.assertTrue(leds.suspend_engine())
            with open(effect) as handle:
                self.assertEqual(handle.read(), "0")
            self.assertTrue(leds.update([0.6] * 6, 0.2, False, force=True))
            with open(frame) as handle:
                self.assertEqual(len(handle.read()), leds.slots * 7)
            self.assertTrue(leds.restore_engine())
            self.assertTrue(leds.clear())


class VisualSettingsTests(unittest.TestCase):
    def test_visual_defaults_and_normalization(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"led_mode": "bad", "spectrum": 1}, handle)
            settings = Settings(path).load()
        self.assertEqual(settings.get("led_mode"), "spectrum")
        self.assertTrue(settings.get("spectrum"))
        with tempfile.TemporaryDirectory() as root:
            fresh = Settings(os.path.join(root, "settings.json")).load()
        self.assertEqual(fresh.get("led_mode"), "spectrum")
        self.assertTrue(fresh.get("spectrum"))

    def test_quick_menu_cycles_led_and_spectrum(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {
            "auto_report_errors": False, "audio_output": "auto",
            "led_mode": "spectrum", "spectrum": True,
        }
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        app.status = ""
        app.status_error = False
        labels = [entry[0] for entry in app._quick_menu_entries()]
        self.assertIn("led_mode", labels)
        self.assertIn("spectrum", labels)
        app.quick_menu = True
        app.quick_menu_page = "main"
        app.quick_menu_selection = labels.index("led_mode")
        app._handle_quick_menu("a")
        self.assertEqual(values["led_mode"], "off")
        app.quick_menu_selection = labels.index("spectrum")
        app._handle_quick_menu("a")
        self.assertFalse(values["spectrum"])

    def test_update_visuals_respects_led_off(self):
        from musicplayer.visuals import SpectrumAnalyser
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.player = mock.Mock()
        app.player.analyser = SpectrumAnalyser()
        app.leds = mock.Mock(available=True)
        app.settings = mock.Mock()
        app.settings.get.return_value = "off"
        app._update_visuals()
        app.leds.update.assert_not_called()
        app.settings.get.return_value = "spectrum"
        app._update_visuals()
        app.leds.update.assert_called_once()


    def test_led_frames_are_vivid_and_rotate(self):
        from musicplayer.leds import frame_for_levels
        first = frame_for_levels([0.7] * 6, 0.2, False, 0)
        leds_first = [first[i:i + 6] for i in range(0, len(first), 6)]
        self.assertGreater(len(set(leds_first)), 2)
        second = frame_for_levels([0.7] * 6, 0.2, False, 10)
        self.assertNotEqual(first, second)

    def test_long_titles_shrink_instead_of_overflowing(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.fonts = {}
        widths = {"title": 600, "body": 320, "small": 200}

        def fake_measure(text, font="body"):
            return (widths.get(font, 300), 27)

        def fake_ellipsize(text, max_width, font="body"):
            return text[:10] + "..."

        app.measure = fake_measure
        app.ellipsize = fake_ellipsize
        text, font = app._fit_title("Short", 700)
        self.assertEqual((text, font), ("Short", "title"))
        text, font = app._fit_title("A very long song title that cannot fit", 500)
        self.assertEqual(font, "body")
        text, font = app._fit_title("A very long song title that cannot fit", 100)
        self.assertTrue(text.endswith("..."))


class TruepodStyleTests(unittest.TestCase):
    def test_wav_spec_is_parsed(self):
        import wave
        from musicplayer import audio_format
        audio_format.clear_cache()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "song.wav")
            with wave.open(path, "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 100)
            self.assertEqual(audio_format.track_audio_info(path), (44100, 16))
            self.assertEqual(audio_format.format_spec(path), "44.1k/16")

    def test_flac_spec_is_parsed(self):
        from musicplayer import audio_format
        audio_format.clear_cache()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "song.flac")
            rate, bits = (48000, 24)
            head = b"\x10\x10" + b"\x00" * 8
            tail = bytes([(rate >> 12) & 0xFF, (rate >> 4) & 0xFF,
                          ((rate & 0x0F) << 4) | 0x03,
                          (((bits - 1) & 0x0F) << 4)])
            streaminfo = (head + tail + b"\x00" * 20)
            self.assertEqual(len(streaminfo), 34)
            with open(path, "wb") as handle:
                handle.write(b"fLaC" + b"\x80" + b"\x00\x00\x22" + streaminfo)
            self.assertEqual(audio_format.track_audio_info(path), (48000, 24))
            self.assertEqual(audio_format.format_spec(path), "48.0k/24")

    def test_mp3_and_unknown_specs_fall_back(self):
        from musicplayer import audio_format
        audio_format.clear_cache()
        with tempfile.TemporaryDirectory() as root:
            mp3 = os.path.join(root, "song.mp3")
            with open(mp3, "wb") as handle:
                handle.write(b"\xFF\xFB\x90\x00" + b"\x00" * 100)
            self.assertEqual(audio_format.track_audio_info(mp3)[0], 44100)
            self.assertEqual(audio_format.format_spec(mp3), "44.1k")
            ogg = os.path.join(root, "song.ogg")
            with open(ogg, "wb") as handle:
                handle.write(b"OggS" + b"\x00" * 100)
            self.assertEqual(audio_format.format_spec(ogg), "OGG")

    def test_peaks_hold_above_levels_then_fall(self):
        import struct
        from musicplayer.visuals import SpectrumAnalyser
        analyser = SpectrumAnalyser()
        pcm = struct.pack("<512h", *([4000] * 512))
        for _ in range(5):
            analyser.offer(pcm)
            analyser._last_tap = 0.0
        peaks = analyser.snapshot_peaks()
        levels = analyser.snapshot()[0]
        self.assertEqual(len(peaks), len(levels))
        self.assertTrue(all(p >= v for p, v in zip(peaks, levels)))
        self.assertGreater(max(peaks), 0.0)
        for _ in range(20):
            analyser.decay()
        self.assertLess(max(analyser.snapshot_peaks()), max(peaks))

    def test_quick_menu_labels_split_into_key_and_value(self):
        self.assertEqual(
            MusicPlayerApp._split_label("Equalizer: Rock"), ("Equalizer", "Rock"),
        )
        self.assertEqual(MusicPlayerApp._split_label("Close Menu"), ("Close Menu", ""))

    def test_theme_uses_bright_fresh_tones(self):
        red, green, blue, _alpha = MusicPlayerApp.BG
        self.assertGreater((red + green + blue) / 3.0, 180.0)
        text_red, text_green, text_blue, _alpha = MusicPlayerApp.TEXT
        self.assertLess((text_red + text_green + text_blue) / 3.0, 80.0)
        panel = MusicPlayerApp.PANEL[:3]
        self.assertGreater(sum(panel) / 3.0, 200.0)

    def test_now_playing_hides_direct_converted_lines(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.width = 640
        app.height = 480
        app.settings = mock.Mock()
        app.settings.get.return_value = True
        app.player = mock.Mock()
        app.player.current = mock.Mock(path="/music/song.flac", title="Song", folder="Album")
        app.player.position.return_value = 10.0
        app.player.duration.return_value = 120.0
        app.player.equalizer.sample_rate = 44100
        app.player.output_device = "System"
        drawn = []
        app.text = lambda *args, **kwargs: drawn.append(args[0])
        app.fill = lambda *args: None
        app.measure = lambda *args, **kwargs: (10, 10)
        app.ellipsize = lambda text, *args, **kwargs: text
        app._fit_title = lambda title, max_width: (title, "title")
        app._render_spectrum = lambda *args, **kwargs: None
        app._render_playing()
        blob = "\n".join(str(line) for line in drawn)
        self.assertNotIn("DIRECT", blob)
        self.assertNotIn("CONVERTED", blob)
        self.assertIn("Song", blob)

    def test_intro_splash_draws_nlk_and_is_skippable(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.width = 640
        app.height = 480
        values = {"intro": True}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        drawn = []
        app.text = lambda *args, **kwargs: drawn.append(args[0])
        app.fill = lambda *args: None
        app.measure = lambda *args, **kwargs: (40, 40)
        app.runtime = mock.Mock()
        app.renderer = mock.Mock()
        app._render_intro_frame(1.0)
        letters = [letter for letter in drawn if letter in ("N", "L", "K")]
        self.assertEqual(letters[:3], ["N", "L", "K"])
        app.runtime.SDL_RenderPresent.assert_called_with(app.renderer)
        app.runtime = mock.Mock()
        app.runtime.SDL_PollEvent.return_value = 0
        app.input = mock.Mock()
        app.input.poll.return_value = [{"action": "a"}]
        with mock.patch("musicplayer.ui.time.monotonic", side_effect=[0.0, 0.0, 999.0]):
            app._play_intro()
        app.runtime.SDL_Delay.assert_not_called()
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.leds = mock.Mock(test_index=-1)
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        self.assertIn("intro", [entry[0] for entry in app._quick_menu_entries()])
        self.assertFalse(app._toggle_intro())

    def test_intro_defaults_on_and_toggle_saves(self):
        with tempfile.TemporaryDirectory() as root:
            fresh = Settings(os.path.join(root, "settings.json")).load()
        self.assertTrue(fresh.get("intro"))
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"intro": True, "auto_report_errors": False, "audio_output": "auto",
                  "led_mode": "spectrum", "spectrum": True}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.leds = mock.Mock(test_index=-1)
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        self.assertIn("intro", [entry[0] for entry in app._quick_menu_entries()])
        self.assertFalse(app._toggle_intro())
        app.settings.save.assert_called_once()

    def test_playback_status_line_mentions_controls(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.runtime = mock.Mock()
        app.runtime.Mix_PausedMusic.return_value = 0
        values = {"shuffle": False, "repeat": "all", "volume": 14}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        line = app._playback_status_line()
        self.assertIn("Playing", line)
        self.assertIn("shuffle off", line)
        self.assertIn("repeat all", line)
        self.assertIn("vol 14", line)


    def test_spectrum_gamma_lengthens_mid_levels(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.width = 640
        app.height = 480
        app.settings = mock.Mock()
        app.settings.get.return_value = True
        app.player = mock.Mock()
        app.player.analyser = mock.Mock()
        app.player.analyser.peaks = [0.25] * 14
        app._visual_snapshot = mock.Mock(return_value=([0.25] * 14, 0.1, False))
        calls = []
        app.fill = lambda x, y, w, h, color: calls.append((x, y, w, h))
        app._render_spectrum(400, 160, gain=2.0)
        heights = [call[3] for call in calls]
        linear_total = int(0.25 * 2.0 * 160) + 2
        self.assertGreater(max(heights), int(linear_total * 0.5))

    def test_spectrum_gain_boosts_quiet_levels(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.width = 640
        app.height = 480
        app.settings = mock.Mock()
        app.settings.get.return_value = True
        app.player = mock.Mock()
        app.player.analyser = mock.Mock()
        app.player.analyser.peaks = [0.05] * 14
        app._visual_snapshot = mock.Mock(return_value=([0.05] * 14, 0.02, False))
        calls = []
        app.fill = lambda x, y, w, h, color: calls.append((x, y, w, h))
        app._render_spectrum(400, 160, gain=1.6)
        bars = [call for call in calls if call[3] > 4]
        self.assertTrue(bars)
        app2 = MusicPlayerApp.__new__(MusicPlayerApp)
        app2.width = 640
        app2.height = 480
        app2.settings = mock.Mock()
        app2.settings.get.return_value = False
        app2.player = mock.Mock()
        app2._visual_snapshot = mock.Mock()
        fills = []
        app2.fill = lambda *args: fills.append(args)
        app2._render_spectrum(400, 160)
        self.assertEqual(fills, [])
        app2._visual_snapshot.assert_not_called()


class OtaRecheckTests(unittest.TestCase):
    def _app(self, auto_update=True):
        from musicplayer.sdl_runtime import MIX_INIT_FLAC, MIX_INIT_MP3
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"auto_update": auto_update, "skipped_version": ""}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.update_lock = threading.Lock()
        app.update_busy = False
        app.update_manifest = None
        app.status = ""
        app.status_error = False
        app.next_update_check = 0.0
        app.update_check_interval = 900.0
        app.paths = mock.Mock()
        app.player = mock.Mock(available_decoders=0, output_device="", sample_rate=0)
        return app

    def test_periodic_check_fires_when_due(self):
        import musicplayer.ui as ui_module
        app = self._app()
        with mock.patch.object(ui_module.threading, "Thread") as thread:
            app._maybe_check_update()
        thread.assert_called_once()
        self.assertGreater(app.next_update_check, 0.0)

    def test_periodic_check_skipped_when_disabled_or_not_due(self):
        import musicplayer.ui as ui_module
        app = self._app(auto_update=False)
        with mock.patch.object(ui_module.threading, "Thread") as thread:
            app._maybe_check_update()
        thread.assert_not_called()
        app2 = self._app()
        app2.next_update_check = 999999999.0
        with mock.patch.object(ui_module.threading, "Thread") as thread:
            app2._maybe_check_update()
        thread.assert_not_called()

    def test_manual_check_reports_latest_and_failure(self):
        import musicplayer.ui as ui_module
        app = self._app()
        with mock.patch.object(ui_module, "fetch_manifest", return_value={"version": APP_VERSION}), \
                mock.patch.object(ui_module, "update_available", return_value=False):
            app._check_update(manual=True)
        self.assertIn("Already on latest", app.status)
        self.assertFalse(app.status_error)
        with mock.patch.object(ui_module, "fetch_manifest", side_effect=RuntimeError("offline")):
            app._check_update(manual=True)
        self.assertTrue(app.status_error)
        self.assertIn("Wi-Fi", app.status)

    def test_audio_info_line_lists_decoders_and_output(self):
        from musicplayer.sdl_runtime import MIX_INIT_FLAC, MIX_INIT_MP3, MIX_INIT_OGG
        app = self._app()
        app.player = mock.Mock(
            available_decoders=MIX_INIT_FLAC | MIX_INIT_MP3 | MIX_INIT_OGG,
            output_device="FiiO USB DAC", sample_rate=48000,
        )
        line = app._audio_info_line()
        self.assertIn("FLAC", line)
        self.assertIn("MP3", line)
        self.assertIn("USB DAC", line)
        self.assertIn("48000", line)

    def test_quick_menu_has_update_and_audio_entries(self):
        app = self._app()
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        ids = [entry[0] for entry in app._quick_menu_entries()]
        self.assertIn("check_update", ids)
        self.assertIn("audio_info", ids)


    def test_quick_menu_scrolls_on_small_screens(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {
            "auto_report_errors": False, "audio_output": "auto",
            "led_mode": "spectrum", "spectrum": True,
        }
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        app.width = 640
        app.height = 480
        app.quick_menu_selection = 0
        app.quick_menu_scroll = 0
        entries = app._quick_menu_entries()
        self.assertGreater(len(entries), app._quick_menu_visible_rows())
        app.quick_menu_selection = len(entries) - 1
        scroll = app._quick_menu_clamp_scroll()
        self.assertGreater(scroll, 0)
        self.assertLessEqual(scroll + app._quick_menu_visible_rows(), len(entries))
        app._handle_quick_menu("up")
        self.assertEqual(app.quick_menu_selection, len(entries) - 2)

    def test_update_interval_is_five_minutes(self):
        import musicplayer.ui as ui_module
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"auto_update": True, "skipped_version": ""}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.update_lock = threading.Lock()
        app.update_busy = False
        app.next_update_check = 0.0
        app.update_check_interval = 300.0
        with mock.patch.object(ui_module.threading, "Thread"):
            with mock.patch.object(ui_module.time, "monotonic", return_value=1000.0):
                app._maybe_check_update()
        self.assertEqual(app.next_update_check, 1300.0)


    def test_controller_suspend_enables_frame_node(self):
        import tempfile
        from musicplayer.leds import LedController
        with tempfile.TemporaryDirectory() as root:
            frame = os.path.join(root, "frame_hex")
            effect = os.path.join(root, "effect_enable")
            enable = os.path.join(root, "enable")
            for path in (frame, effect, enable):
                with open(path, "w") as handle:
                    handle.write("")
            leds = LedController(frame_path=frame, effect_path=effect, enable_path=enable)
            self.assertTrue(leds.suspend_engine())
            with open(enable) as handle:
                self.assertEqual(handle.read(), "1")

    def test_led_test_mode_writes_single_position(self):
        import tempfile
        from musicplayer.leds import LedController
        with tempfile.TemporaryDirectory() as root:
            frame = os.path.join(root, "frame_hex")
            with open(frame, "w") as handle:
                handle.write("")
            leds = LedController(frame_path=frame, effect_path="", enable_path="")
            leds.frame_path = frame
            leds.enabled = True
            leds.test_index = 4
            self.assertTrue(leds.update([0.5] * 14, 0.1, False, force=True))
            with open(frame) as handle:
                parts = handle.read().split()
            self.assertEqual(parts[4], "FFFFFF")
            self.assertEqual(parts.count("000000"), leds.slots - 1)

    def test_led_test_toggle_and_step(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.leds = mock.Mock(available=True, test_index=-1, slots=23)
        app.status = ""
        app.status_error = False
        self.assertEqual(app._toggle_led_test(), 0)
        app.leds.test_index = 0
        self.assertEqual(app._step_led_test(1), 1)
        self.assertIn("2/23", app.status)

    def test_quick_menu_lists_led_test(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"auto_report_errors": False, "audio_output": "auto",
                  "led_mode": "spectrum", "spectrum": True}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.leds = mock.Mock(test_index=-1)
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        ids = [entry[0] for entry in app._quick_menu_entries()]
        self.assertIn("led_test", ids)


class DriveTests(unittest.TestCase):
    def test_extract_folder_id_from_id_and_urls(self):
        folder = "1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a"
        self.assertEqual(extract_folder_id(folder), folder)
        self.assertEqual(
            extract_folder_id("https://drive.google.com/drive/folders/%s?usp=sharing" % folder),
            folder,
        )
        self.assertEqual(
            extract_folder_id("https://drive.google.com/open?id=%s" % folder), folder,
        )

    def test_default_folder_is_public_share(self):
        self.assertEqual(DEFAULT_FOLDER_ID, "1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a")

    def test_list_url_uses_paged_parents_query_with_minimal_fields(self):
        url = build_list_url("FOLDER1234567890", "PUBLIC_KEY", page_size=25)
        self.assertIn("googleapis.com/drive/v3/files", url)
        self.assertIn("pageSize=25", url)
        self.assertIn("key=PUBLIC_KEY", url)
        self.assertIn("parents", url)
        self.assertIn("nextPageToken", url)
        self.assertNotIn("Authorization", url)
        with self.assertRaises(DriveError):
            build_list_url("FOLDER1234567890", "")

    def test_parse_filters_to_audio_and_folders_only(self):
        payload = {
            "nextPageToken": "NEXT",
            "files": [
                {"id": "f1", "name": "Album", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "a1", "name": "song.flac", "mimeType": "audio/flac", "size": "123"},
                {"id": "a2", "name": "song.mp3", "mimeType": "application/octet-stream"},
                {"id": "d1", "name": "notes.txt", "mimeType": "text/plain"},
                {"id": "", "name": "bad", "mimeType": "audio/mpeg"},
            ],
        }
        entries, token = parse_list_response(payload)
        self.assertEqual(token, "NEXT")
        by_id = {entry.file_id: entry for entry in entries}
        self.assertIn("f1", by_id)
        self.assertTrue(by_id["f1"].is_folder)
        self.assertIn("a1", by_id)
        self.assertIn("a2", by_id)
        self.assertNotIn("d1", by_id)
        self.assertFalse(any(entry.file_id == "" for entry in entries))

    def test_audio_names_support_local_extensions(self):
        self.assertTrue(is_audio_name("track.FLAC"))
        self.assertTrue(is_audio_name("track.opus", "application/octet-stream"))
        self.assertFalse(is_audio_name("cover.jpg", "image/jpeg"))

    def test_download_urls_prefer_key_but_allow_keyless(self):
        keyed = media_url("FILE1234567890", "PUBLIC_KEY")
        self.assertIn("alt=media", keyed)
        self.assertIn("key=PUBLIC_KEY", keyed)
        keyless = public_download_url("FILE1234567890")
        self.assertIn("uc?export=download", keyless)
        self.assertIn("FILE1234567890", keyless)

    def test_parse_embed_page_reads_folders_and_audio_only(self):
        markup = (
            '<div class="flip-entries">'
            '<div class="flip-entry" id="entry-AAAABBBBCCCCDDDDe1" tabindex="0" role="link">'
            '<a href="https://drive.google.com/drive/folders/AAAABBBBCCCCDDDDe1" target="_blank">'
            '<div class="flip-entry-title">My Album &amp; More</div></a></div>'
            '<div class="flip-entry" id="entry-AAAABBBBCCCCDDDDe2" tabindex="0" role="link">'
            '<a href="https://drive.google.com/file/d/AAAABBBBCCCCDDDDe2/view?usp=drive_web">'
            '<div class="flip-entry-title">01 Song.flac</div></a></div>'
            '<div class="flip-entry" id="entry-AAAABBBBCCCCDDDDe3" tabindex="0" role="link">'
            '<a href="https://drive.google.com/file/d/AAAABBBBCCCCDDDDe3/view?usp=drive_web">'
            '<div class="flip-entry-title">notes.txt</div></a></div>'
            "</div>"
        )
        entries, token = drive_module.parse_embed_page(markup)
        self.assertEqual(token, "")
        by_id = {entry.file_id: entry for entry in entries}
        self.assertTrue(by_id["AAAABBBBCCCCDDDDe1"].is_folder)
        self.assertEqual(by_id["AAAABBBBCCCCDDDDe1"].name, "My Album & More")
        self.assertFalse(by_id["AAAABBBBCCCCDDDDe2"].is_folder)
        self.assertEqual(by_id["AAAABBBBCCCCDDDDe2"].extension, ".flac")
        self.assertNotIn("AAAABBBBCCCCDDDDe3", by_id)
        with self.assertRaises(DriveError):
            drive_module.parse_embed_page("<html>no entries here</html>")

    def test_public_listing_needs_no_api_key(self):
        markup = (
            '<div class="flip-entry" id="entry-AAAABBBBCCCCDDDDe1">'
            '<a href="https://drive.google.com/drive/folders/AAAABBBBCCCCDDDDe1">'
            '<div class="flip-entry-title">Album</div></a></div>'
        ).encode("utf-8")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = markup
        response.__exit__.return_value = False
        with mock.patch("musicplayer.drive.verified_context", return_value=None), \
                mock.patch("musicplayer.drive.urllib.request.urlopen", return_value=response) as open_url:
            entries, token = drive_module.list_folder_public("/app", DEFAULT_FOLDER_ID)
        request = open_url.call_args.args[0]
        self.assertIn("embeddedfolderview", request.full_url)
        self.assertNotIn("key=", request.full_url)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].is_folder)

    def test_drive_refresh_without_key_uses_public_listing(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"drive_folder_id": DEFAULT_FOLDER_ID, "drive_api_key": ""}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.paths = mock.Mock(app_dir="/app", data_dir="/nonexistent-data-dir")
        app.drive_stack = []
        app.drive_entries = []
        app.drive_page_token = ""
        app.drive_busy = False
        app.drive_loaded = False
        app.selection = 0
        app.status = ""
        app.status_error = False
        fake = [mock.Mock(file_id="F1", is_folder=True)]
        with mock.patch("musicplayer.ui.drive_list_public", return_value=(fake, "")) as public, \
                mock.patch("musicplayer.ui.drive_put_cache"):
            app._drive_refresh()
        public.assert_called_once_with("/app", DEFAULT_FOLDER_ID)
        self.assertEqual(app.drive_entries, fake)
        self.assertTrue(app.drive_loaded)
        self.assertFalse(app.drive_busy)
        self.assertNotIn("settings.json", app.status)

    def test_cache_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as root:
            entries, _token = parse_list_response({
                "files": [
                    {"id": "a1", "name": "song.mp3", "mimeType": "audio/mpeg", "size": "10"},
                ],
            })
            drive_module.put_cached_folder(root, "F1", entries, "T1")
            cached = drive_module.get_cached_folder(root, "F1")
            self.assertIsNotNone(cached)
            self.assertEqual(cached[0][0].file_id, "a1")
            self.assertEqual(cached[1], "T1")
            drive_module.clear_cache(root)
            self.assertIsNone(drive_module.get_cached_folder(root, "F1"))

    def test_offline_path_stays_under_music_drive_album(self):
        with tempfile.TemporaryDirectory() as root:
            music = os.path.join(root, "Music")
            path = offline_path(music, "My Album", "01 Title.flac")
            self.assertTrue(path.startswith(os.path.join(music, "Drive")))
            self.assertIn("My Album", path)
        self.assertEqual(sanitize_component('a/b:c*?"<>|', "x"), "a_b_c______")

    def test_settings_normalize_drive_link_and_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "drive_folder_id": "https://drive.google.com/drive/folders/1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a",
                    "drive_api_key": "  KEY123  ",
                }, handle)
            settings = Settings(path).load()
        self.assertEqual(settings.get("drive_folder_id"), DEFAULT_FOLDER_ID)
        self.assertEqual(settings.get("drive_api_key"), "KEY123")
        with tempfile.TemporaryDirectory() as root:
            fresh = Settings(os.path.join(root, "settings.json")).load()
        self.assertEqual(fresh.get("drive_folder_id"), DEFAULT_FOLDER_ID)
        self.assertEqual(fresh.get("drive_api_key"), "")

    def test_audio_resolves_drive_scheme_before_decode(self):
        from musicplayer.library import Track
        runtime = mock.Mock()
        runtime.Mix_LoadMUS.return_value = object()
        runtime.Mix_PlayMusic.return_value = 0
        runtime.Mix_MusicDuration.return_value = 0
        values = {"volume": 80, "repeat": "off", "shuffle": False}
        settings = mock.Mock()
        settings.get.side_effect = values.get
        settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        player = AudioPlayer(runtime, [
            Track(path="drive://FILE1/song.mp3", title="song", folder="Drive", extension=".mp3"),
        ], settings)
        player.audio_ready = True
        player.drive_resolver = lambda track: "/tmp/song.mp3"
        self.assertTrue(player.play(0))
        runtime.Mix_LoadMUS.assert_called_once_with(b"/tmp/song.mp3")

    def test_drive_library_mode_and_quick_menu(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {
            "auto_report_errors": False, "audio_output": "auto",
            "led_mode": "spectrum", "spectrum": True,
            "drive_folder_id": DEFAULT_FOLDER_ID, "drive_api_key": "K",
        }
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
        app.player = mock.Mock()
        app.player.equalizer.preset = "Flat"
        app.sleep_timer = SleepTimer()
        app.update_manifest = None
        app.paths = mock.Mock(app_dir="/app", data_dir="/data", music_dir="/music")
        app.screen = "library"
        app.active_playlist = ""
        app.leds = mock.Mock(test_index=-1)
        app.library_mode = "favorite_playlists"
        app.playlist_parent_mode = "playlists"
        app.selection = 0
        app.scroll = 0
        app.drive_stack = []
        app.drive_entries = []
        app.drive_page_token = ""
        app.drive_loaded = False
        app.drive_busy = False
        with mock.patch.object(app, "_drive_refresh") as refresh:
            app._open_drive()
        self.assertEqual(app.library_mode, "drive")
        refresh.assert_called_once()
        self.assertEqual(app._screen_title(), "DRIVE")
        app._open_source()
        self.assertEqual(app.library_mode, "source")
        self.assertEqual(app._screen_title(), "MUSIC")
        ids = [entry[0] for entry in app._quick_menu_entries()]
        self.assertIn("drive_refresh", ids)
        self.assertIn("drive_download", ids)
        self.assertIn("drive_clear", ids)

    def test_local_view_cycle_stays_local(self):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        app.library_mode = "favorite_playlists"
        app.playlist_parent_mode = "playlists"
        app.active_playlist = ""
        app.selection = 0
        app.scroll = 0
        app.drive_loaded = False
        with mock.patch.object(app, "_drive_refresh") as refresh:
            app._cycle_library_mode()
        self.assertEqual(app.library_mode, "all")
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
