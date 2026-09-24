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
from musicplayer.library import natural_key, scan_library
from musicplayer.paths import RuntimePaths, detect_os
from musicplayer.reporter import _redact, queue_report
from musicplayer.settings import Settings
from musicplayer.updater import apply_update, update_available, validate_manifest, version_tuple


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
            app_dir = os.path.join(root, "Apps", "Music Player")
            os.makedirs(app_dir)
            os.makedirs(os.path.join(root, "Music"))
            paths = RuntimePaths.discover(app_dir=app_dir, environ={})
        self.assertEqual(paths.sdcard_path, root)

    def test_infers_sd_root_from_spruce_app_directory(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "App", "Music Player")
            os.makedirs(app_dir)
            os.makedirs(os.path.join(root, "Music"))
            paths = RuntimePaths.discover(app_dir=app_dir, environ={})
        self.assertEqual(paths.sdcard_path, root)

    def test_detects_spruce_from_environment(self):
        self.assertEqual(detect_os("/missing", {"MUSIC_PLAYER_OS": "spruce"}), "spruce")

    def test_defaults_to_stock_without_markers(self):
        self.assertEqual(detect_os("/missing", {}), "stock")


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


class ReporterTests(unittest.TestCase):
    def test_redacts_token_paths_and_mac(self):
        paths = mock.Mock(
            app_dir="/sd/Apps/Music Player", sdcard_path="/sd", music_dir="/sd/Music"
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


class UpdaterTests(unittest.TestCase):
    def test_rejects_path_traversal_and_protected_files(self):
        base = {"version": "9.0", "base_url": "https://example.test/files"}
        for path in ("../escape", "/absolute", "secrets.json", "data/settings.json"):
            manifest = dict(base, files=[{"path": path, "sha256": "0" * 64, "size": 1}])
            with self.assertRaises(ValueError):
                validate_manifest(manifest)

    def test_version_comparison(self):
        self.assertEqual(version_tuple("v1.10.2"), (1, 10, 2))
        self.assertTrue(update_available({"version": "99.0.0"}))

    def test_update_stays_inside_installed_app_directory(self):
        with tempfile.TemporaryDirectory() as root:
            app_dir = os.path.join(root, "Apps", "Music Player")
            data_dir = os.path.join(app_dir, "data")
            os.makedirs(data_dir)
            paths = mock.Mock(app_dir=app_dir, data_dir=data_dir)
            manifest = {
                "version": "1.0.2",
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
            self.assertFalse(os.path.exists(os.path.join(root, "App", "Music Player")))


class FakeRuntime:
    def Mix_VolumeMusic(self, value):
        self.volume = value


class AudioLogicTests(unittest.TestCase):
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
