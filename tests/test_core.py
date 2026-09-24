import json
import os
import sys
import tempfile
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
from musicplayer.equalizer import Equalizer, preset_gains
from musicplayer.library import natural_key, scan_library
from musicplayer.lyrics import load_lyrics, parse_lrc
from musicplayer.paths import RuntimePaths, detect_os
from musicplayer.reporter import _redact, _submit, queue_report
from musicplayer.settings import Settings
from musicplayer.sleep_timer import SleepTimer
from musicplayer.updater import apply_update, update_available, validate_manifest, version_tuple
from musicplayer.ui import MusicPlayerApp


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

    def test_long_session_log_continues_in_issue_comments(self):
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
            responses = [[], {"comments_url": "https://api.example/comments"}, {}, {}]
            with mock.patch(
                "musicplayer.reporter._request_json", side_effect=responses
            ) as request:
                _submit(paths, item, "token", "owner/repo")

        calls = request.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[1].kwargs["method"], "POST")
        self.assertEqual(calls[2].args[1], "https://api.example/comments")
        self.assertIn("Session log part 3/3", calls[3].kwargs["body"]["body"])


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
        self.assertEqual("v%s" % APP_VERSION, "v1.3.0")

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
        app.running = True

        app._handle("b")
        self.assertTrue(app.exit_confirmation)
        self.assertTrue(app.running)

        app._handle("b")
        self.assertFalse(app.exit_confirmation)
        self.assertTrue(app.running)

        app._handle("b")
        app._handle("a")
        self.assertFalse(app.running)

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


if __name__ == "__main__":
    unittest.main()
