# -*- coding: utf-8 -*-
"""Test cho v1.21.0: xoa Drive link, tai ve theo album, playlist tu tao,
tai ca thu muc (khong gom thu muc con, co kiem tra SD + xac nhan)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
if FILES not in sys.path:
    sys.path.insert(0, FILES)

from musicplayer import drive as drive_module
from musicplayer.collections import Collections
from musicplayer.drive import DriveEntry
from musicplayer.library import Track
from musicplayer.ui import MusicPlayerApp


def audio(file_id, name, size=1024):
    return DriveEntry(
        file_id=file_id, name=name, mime_type="", size=size, is_folder=False,
        title=name.rsplit(".", 1)[0], extension=os.path.splitext(name)[1].lower(),
    )


def folder(file_id, name):
    return DriveEntry(
        file_id=file_id, name=name,
        mime_type="application/vnd.google-apps.folder",
        size=0, is_folder=True, title=name, extension="",
    )


def make_app(slots=None, tracks=None):
    app = MusicPlayerApp.__new__(MusicPlayerApp)
    tmp = tempfile.mkdtemp()
    app.paths = mock.Mock(
        app_dir=tmp, data_dir=os.path.join(tmp, "data"),
        music_dir=os.path.join(tmp, "Music"),
    )
    os.makedirs(app.paths.data_dir, exist_ok=True)
    os.makedirs(app.paths.music_dir, exist_ok=True)
    slots = slots if slots is not None else [
        {"name": "Drive 1", "folder": "AAAAAAAAAAAAAAAAAAAA"},
        {"name": "Drive 2", "folder": "BBBBBBBBBBBBBBBBBBBB"},
    ]
    values = {
        "drive_slots": [dict(s) for s in slots],
        "drive_slot": 0,
        "drive_folder_id": slots[0]["folder"] if slots else "",
        "drive_api_key": "",
    }
    app.settings = mock.Mock()
    app.settings.get.side_effect = values.get
    app.settings.set.side_effect = lambda key, value: values.__setitem__(key, value)
    app.settings.save.side_effect = lambda: None
    app.values = values
    app.tmp = tmp
    app.collections = Collections(os.path.join(tmp, "c.json")).load()
    app.tracks = list(tracks or [])
    app.screen = "library"
    app.library_mode = "drive"
    app.selection = 0
    app.scroll = 0
    app.playlist_parent_mode = "playlists"
    app.active_playlist = ""
    app.drive_stack = []
    app.drive_entries = []
    app.drive_page_token = ""
    app.drive_busy = False
    app.drive_loaded = False
    app.quick_menu = False
    app.quick_menu_page = "main"
    app.quick_menu_selection = 0
    app.quick_menu_scroll = 0
    app.exit_confirmation = False
    app.pending_confirm = None
    app.folder_job = None
    app.download_job = None
    app._saved_toast = ("", 0.0)
    app._saved_rows = {}
    app.status = ""
    app.status_error = False
    app.player = mock.Mock(
        current=None, equalizer=mock.Mock(preset="Flat", gains=(0, 0, 0)),
    )
    app.sleep_timer = mock.Mock(active=False, label="Off")
    app.update_manifest = None
    app.update_busy = False
    app.width, app.height = 1024, 768
    return app


class RemoveSlotTests(unittest.TestCase):
    def test_remove_by_index(self):
        slots = [
            {"name": "Drive 1", "folder": "AAAAAAAAAAAAAAAAAAAA"},
            {"name": "Drive 2", "folder": "BBBBBBBBBBBBBBBBBBBB"},
        ]
        original = [dict(s) for s in slots]
        new, removed = drive_module.remove_slot(slots, 0)
        self.assertEqual(removed["name"], "Drive 1")
        self.assertEqual(len(new), 1)
        self.assertEqual(slots, original)

    def test_remove_by_folder(self):
        slots = [{"name": "Drive 1", "folder": "AAAAAAAAAAAAAAAAAAAA"}]
        new, removed = drive_module.remove_slot(slots, "drive.google.com/drive/folders/AAAAAAAAAAAAAAAAAAAA")
        self.assertEqual(removed["folder"], "AAAAAAAAAAAAAAAAAAAA")
        self.assertEqual(new, [])

    def test_remove_invalid_keeps_list(self):
        slots = [{"name": "Drive 1", "folder": "AAAAAAAAAAAAAAAAAAAA"}]
        new, removed = drive_module.remove_slot(slots, 5)
        self.assertIsNone(removed)
        self.assertEqual(new, slots)

    def test_ui_delete_slot_with_confirm(self):
        app = make_app()
        app._request_delete_drive_slot(0)
        self.assertIsNotNone(app.pending_confirm)
        self.assertIn("Drive 1", app.pending_confirm["title"])
        with mock.patch.object(app, "_drive_refresh", return_value=None):
            app._handle("a")
        self.assertIsNone(app.pending_confirm)
        self.assertEqual(len(app.values["drive_slots"]), 1)
        self.assertIn("Removed", app.status)

    def test_ui_delete_cancel_keeps_slot(self):
        app = make_app()
        app._request_delete_drive_slot(0)
        app._handle("b")
        self.assertEqual(len(app.values["drive_slots"]), 2)
        self.assertIsNone(app.pending_confirm)

    def test_ui_delete_last_resets_default(self):
        app = make_app([{"name": "Drive 1", "folder": "AAAAAAAAAAAAAAAAAAAA"}])
        app._request_delete_drive_slot(0)
        with mock.patch.object(app, "_drive_refresh", return_value=None):
            app._handle("a")
        self.assertEqual(len(app.values["drive_slots"]), 1)
        self.assertEqual(
            app.values["drive_folder_id"], drive_module.DEFAULT_FOLDER_ID)

    def test_x_on_slot_requests_delete_not_download(self):
        app = make_app()
        row = DriveEntry(
            file_id="slot:1", name="Drive 2",
            mime_type="application/vnd.google-apps.folder",
            size=0, is_folder=True, title="Drive 2", extension="",
        )
        with mock.patch.object(app, "_request_delete_drive_slot", return_value=True) as delete:
            with mock.patch.object(app, "_request_download_folder") as folder_dl:
                with mock.patch.object(app, "_drive_download_row") as track_dl:
                    app._drive_x_row(row)
        delete.assert_called_once_with(1)
        folder_dl.assert_not_called()
        track_dl.assert_not_called()

    def test_x_on_audio_still_saves(self):
        app = make_app()
        row = audio("F1AAAAAAAABBBB", "song.mp3")
        with mock.patch.object(app, "_save_entry_offline", return_value="/x") as save:
            app._drive_x_row(row)
        save.assert_called_once()

    def test_x_on_folder_requests_folder_download(self):
        app = make_app()
        app.drive_stack = [("AAAAAAAAAAAAAAAAAAAA", "Drive 1")]
        row = folder("FOLDER1234567890", "Nhac Tre")
        with mock.patch.object(app, "_request_download_folder", return_value=True) as req:
            app._drive_x_row(row)
        req.assert_called_once()


class OfflineLayoutTests(unittest.TestCase):
    def test_album_paths_are_separate_subfolders(self):
        with tempfile.TemporaryDirectory() as music:
            first = drive_module.offline_path(music, "Drive 1/Nhac Tre", "a.mp3")
            second = drive_module.offline_path(music, "Drive 1/Nhac Khac", "a.mp3")
            self.assertNotEqual(first, second)
            self.assertIn(os.path.join("Drive", "Drive 1", "Nhac Tre"), first)
            self.assertIn(os.path.join("Drive", "Drive 1", "Nhac Khac"), second)

    def test_display_dir_is_short(self):
        self.assertEqual(
            drive_module.offline_display_dir("Drive 1/Nhac Tre"),
            "Drive/Drive 1/Nhac Tre",
        )

    def test_finished_save_mentions_destination(self):
        app = make_app()
        job = drive_module.StreamJob(
            "offline:/x/song.mp3", "song", 100, "offline",
            entry=audio("F1AAAAAAAABBBB", "song.mp3"), album="Drive 1/Nhac Tre",
        )
        job.done = True
        job.path = "/music/Drive/Drive 1/Nhac Tre/song.mp3"
        app.download_job = job
        with mock.patch("musicplayer.library.scan_library", return_value=[]):
            app._finish_offline_save(job.entry, job.path)
        self.assertIn("Drive/Drive 1/Nhac Tre", app.status)
        self.assertIn("song.mp3", app.status)


class CustomPlaylistTests(unittest.TestCase):
    def test_create_add_order_and_persist(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "c.json")
            first = Collections(path)
            name = first.create_playlist("")
            self.assertTrue(name.startswith("Playlist"))
            first.add_to_playlist(name, "/m/b.mp3")
            first.add_to_playlist(name, "/m/a.mp3")
            first.add_to_playlist(name, "/m/a.mp3")
            first.save()
            second = Collections(path).load()
            self.assertEqual(
                [os.path.basename(p) for p in second.custom_playlists[name]],
                ["b.mp3", "a.mp3"],
            )

    def test_combined_lists_custom_first(self):
        with tempfile.TemporaryDirectory() as root:
            collections = Collections(os.path.join(root, "c.json"))
            name = collections.create_playlist("")
            tracks = [Track(path="/m/a.mp3", title="a", folder="Album", extension=".mp3")]
            self.assertEqual(collections.combined_playlists(tracks)[0], name)

    def test_custom_tracks_keep_added_order(self):
        with tempfile.TemporaryDirectory() as root:
            collections = Collections(os.path.join(root, "c.json"))
            name = collections.create_playlist("My Mix")
            collections.add_to_playlist(name, "/m/b.mp3")
            collections.add_to_playlist(name, "/m/a.mp3")
            tracks = [
                Track(path="/m/a.mp3", title="a", folder="Album", extension=".mp3"),
                Track(path="/m/b.mp3", title="b", folder="Album", extension=".mp3"),
            ]
            self.assertEqual(
                [t.title for t in collections.custom_tracks(name, tracks)], ["b", "a"])

    def test_drive_tracks_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            collections = Collections(os.path.join(root, "c.json"))
            _label, added = collections.add_to_playlist("Mix", "drive://F1/song.mp3")
            self.assertFalse(added)

    def test_ui_add_and_remove_flow(self):
        app = make_app()
        first = Track(path="/m/a.mp3", title="a", folder="Album", extension=".mp3")
        second = Track(path="/m/b.mp3", title="b", folder="Album", extension=".mp3")
        app.tracks = [first, second]
        name = app._create_playlist_for_target(first)
        self.assertIn("Playlist", name)
        app._add_target_to_playlist(name, second)
        self.assertEqual(len(app.collections.custom_playlists[name]), 2)
        app.library_mode = "playlist_tracks"
        app.active_playlist = name
        app.selection = 0
        self.assertTrue(app._remove_selected_from_playlist())
        self.assertEqual(len(app.collections.custom_playlists[name]), 1)

    def test_ui_delete_playlist_with_confirm(self):
        app = make_app()
        name = app.collections.create_playlist("My Mix")
        app._request_delete_playlist(name)
        self.assertIsNotNone(app.pending_confirm)
        app._handle("a")
        self.assertNotIn(name, app.collections.custom_playlists)


class FolderDownloadTests(unittest.TestCase):
    def test_direct_audio_skips_subfolders(self):
        items = [
            audio("F1AAAAAAAABBBB", "a.mp3"),
            folder("SUBFOLDER12345", "Sub"),
            audio("F2AAAAAAAABBBB", "b.mp3"),
        ]
        direct = drive_module.folder_direct_audio(items)
        self.assertEqual(len(direct), 2)

    def test_estimate_counts_unknown(self):
        count, total, unknown = drive_module.estimate_download([
            audio("F1AAAAAAAABBBB", "a.mp3", 100),
            audio("F2AAAAAAAABBBB", "b.mp3", 0),
        ])
        self.assertEqual(count, 2)
        self.assertTrue(unknown)

    def test_request_builds_confirm_and_skips_subfolders(self):
        app = make_app()
        app.drive_stack = [("AAAAAAAAAAAAAAAAAAAA", "Drive 1")]
        children = [
            audio("F1AAAAAAAABBBB", "a.mp3", 5 * 1024 * 1024),
            folder("SUBFOLDER12345", "Sub"),
            audio("F2AAAAAAAABBBB", "b.mp3", 3 * 1024 * 1024),
        ]
        with mock.patch.object(app, "_fetch_folder_children", return_value=children):
            self.assertTrue(
                app._request_download_folder(folder("FOLDER1234567890", "Nhac Tre")))
        self.assertIsNotNone(app.pending_confirm)
        self.assertIn("2 tracks", app.pending_confirm["lines"][1])
        self.assertIn("subfolders skipped", app.pending_confirm["lines"][1].lower())

    def test_request_rejects_when_no_direct_audio(self):
        app = make_app()
        app.drive_stack = [("AAAAAAAAAAAAAAAAAAAA", "Drive 1")]
        with mock.patch.object(
                app, "_fetch_folder_children",
                return_value=[folder("SUBFOLDER12345", "Sub")]):
            self.assertFalse(
                app._request_download_folder(folder("FOLDER1234567890", "Empty")))
        self.assertTrue(app.status_error)

    def test_request_rejects_when_sd_full(self):
        app = make_app()
        app.drive_stack = [("AAAAAAAAAAAAAAAAAAAA", "Drive 1")]
        big = [audio("F1AAAAAAAABBBB", "a.mp3", 10 * 1024 * 1024 * 1024)]
        with mock.patch.object(app, "_fetch_folder_children", return_value=big):
            with mock.patch("musicplayer.ui.drive_disk_free", return_value=1024):
                self.assertFalse(
                    app._request_download_folder(folder("FOLDER1234567890", "Big")))
        self.assertIn("Not enough space", app.status)

    def test_folder_job_saves_all_and_rescans_once(self):
        app = make_app()
        app.drive_stack = [("AAAAAAAAAAAAAAAAAAAA", "Drive 1")]
        entries = [
            audio("F1AAAAAAAABBBB", "a.mp3", 100),
            audio("F2AAAAAAAABBBB", "b.mp3", 100),
        ]
        started = []

        def fake_offline(app_dir, music_dir, album, entry, api_key=""):
            started.append((album, entry.name))
            job = drive_module.StreamJob(
                "offline:" + entry.file_id, entry.title, entry.size,
                "offline", entry, album,
            )
            job.finish("/music/%s" % entry.name)
            return job

        with mock.patch.object(app, "_fetch_folder_children", return_value=entries):
            app._request_download_folder(folder("FOLDER1234567890", "Nhac Tre"))
        with mock.patch("musicplayer.ui.drive_start_offline_job", side_effect=fake_offline):
            with mock.patch.object(app, "_existing_offline_copy", return_value=""):
                with mock.patch("musicplayer.library.scan_library", return_value=[]) as scan:
                    app._handle("a")
        self.assertIsNone(app.folder_job)
        self.assertEqual(len(started), 2)
        self.assertEqual(started[0][0], "Drive 1/Nhac Tre")
        self.assertEqual(scan.call_count, 1)
        self.assertIn("2/2 saved", app.status)
        self.assertIn("Drive/Drive 1/Nhac Tre", app.status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
