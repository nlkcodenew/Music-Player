# -*- coding: utf-8 -*-
"""Test cho luong tai Drive moi: job dung chung, % , khong treo man hinh,
va nhan dien bai da co san tren may (ke ca khi nam o thu muc khac)."""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
if FILES not in sys.path:
    sys.path.insert(0, FILES)

from musicplayer import drive as drive_module  # noqa: E402
from musicplayer.drive import (  # noqa: E402
    DriveEntry,
    DriveError,
    StreamJob,
    find_offline_copy,
    offline_index,
    offline_path,
    start_offline_job,
    start_stream_job,
)
from musicplayer.ui import MusicPlayerApp  # noqa: E402


def entry(file_id="FILEID1234567890", name="song.mp3", size=3 * 1024 * 1024):
    return DriveEntry(
        file_id=file_id, name=name, mime_type="", size=size, is_folder=False,
        title=name.rsplit(".", 1)[0], extension=os.path.splitext(name)[1].lower(),
    )


def reset_jobs():
    with drive_module._JOBS_LOCK:
        drive_module._JOBS.clear()
    drive_module.refresh_offline_index()


class StreamJobTests(unittest.TestCase):
    def setUp(self):
        reset_jobs()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.music = os.path.join(self.root, "music")
        os.makedirs(self.music, exist_ok=True)
        self.app_dir = os.path.join(self.root, "app")
        os.makedirs(self.app_dir, exist_ok=True)
        self.data_dir = os.path.join(self.root, "data")
        os.makedirs(self.data_dir, exist_ok=True)

    def tearDown(self):
        reset_jobs()
        self.tmp.cleanup()

    def _fake_download(self, payload=b"x" * 4096, delay=0.0, chunks=1):
        def fake(app_dir, url, destination, expected_size=0, progress=None,
                 should_cancel=None):
            total = 0
            for _ in range(chunks):
                if delay:
                    time.sleep(delay)
                if should_cancel is not None and should_cancel():
                    raise DriveError("Download cancelled")
                total += len(payload)
                if progress is not None:
                    progress(total)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "wb") as handle:
                handle.write(b"x" * total)
            return destination
        return fake

    def test_job_reports_progress_and_finishes(self):
        with mock.patch.object(drive_module, "_download_to_path",
                               side_effect=self._fake_download(chunks=4)):
            job = start_stream_job(self.app_dir, self.data_dir, entry(), "")
        for _ in range(100):
            if job.done:
                break
            time.sleep(0.02)
        self.assertTrue(job.done)
        self.assertFalse(job.error)
        self.assertTrue(os.path.isfile(job.path))
        self.assertGreater(job.bytes, 0)

    def test_percent_is_accurate_when_size_known(self):
        job = StreamJob("F1", "song", 1000)
        job.update(250)
        self.assertAlmostEqual(job.percent, 0.25, places=3)
        job.update(1000)
        self.assertAlmostEqual(job.percent, 1.0, places=3)

    def test_percent_never_reaches_full_before_done(self):
        job = StreamJob("F1", "song", 0)
        job.update(50 * 1024 * 1024)
        self.assertLess(job.percent, 1.0)
        self.assertIn("%", job.label())

    def test_same_file_shares_one_job(self):
        """Hai noi (prefetch + man hinh chinh) chi tao MOT job cho mot file."""
        started = []
        gate = threading.Event()

        def slow(app_dir, url, destination, expected_size=0, progress=None,
                 should_cancel=None):
            started.append(url)
            gate.wait(5)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "wb") as handle:
                handle.write(b"data")
            if progress is not None:
                progress(4)
            return destination

        with mock.patch.object(drive_module, "_download_to_path", side_effect=slow):
            first = start_stream_job(self.app_dir, self.data_dir, entry(), "")
            second = start_stream_job(self.app_dir, self.data_dir, entry(), "")
            self.assertIs(first, second, "phai dung chung mot job")
            self.assertEqual(len(started), 1, "khong duoc tai trung")
            gate.set()
            for _ in range(100):
                if first.done:
                    break
                time.sleep(0.02)
        self.assertTrue(first.done)

    def test_cached_file_returns_finished_job(self):
        target = drive_module.stream_path(self.data_dir, "FILEID1234567890", ".mp3")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(b"cached")
        with mock.patch.object(drive_module, "_download_to_path",
                               side_effect=AssertionError("khong duoc tai lai")):
            job = start_stream_job(self.app_dir, self.data_dir, entry(size=0), "")
        self.assertTrue(job.done)
        self.assertEqual(job.path, target)

    def test_failed_download_reports_error(self):
        def fail(*args, **kwargs):
            raise DriveError("Drive network: offline")
        with mock.patch.object(drive_module, "_download_to_path", side_effect=fail):
            job = start_stream_job(self.app_dir, self.data_dir, entry(), "")
        for _ in range(100):
            if job.done:
                break
            time.sleep(0.02)
        self.assertTrue(job.done)
        self.assertIn("offline", job.error)

    def test_cancel_stops_download(self):
        job = StreamJob("F1", "song", 0)
        job.cancel()
        self.assertTrue(job.is_cancelled())


class OfflineIndexTests(unittest.TestCase):
    def setUp(self):
        reset_jobs()
        self.tmp = tempfile.TemporaryDirectory()
        self.music = os.path.join(self.tmp.name, "music")
        os.makedirs(self.music)
        self.app_dir = os.path.join(self.tmp.name, "app")
        os.makedirs(self.app_dir, exist_ok=True)

    def tearDown(self):
        reset_jobs()
        self.tmp.cleanup()

    def _save(self, album, filename, size=2048):
        path = offline_path(self.music, album, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"0" * size)
        drive_module.refresh_offline_index()
        return path

    def test_finds_track_saved_in_another_folder(self):
        """Bai da luu o thu muc A van duoc tim thay khi xem o thu muc B."""
        saved = self._save("Album A", "Bai hat.mp3")
        found = find_offline_copy(self.music, "Bai hat.mp3", 2048)
        self.assertEqual(found, saved)

    def test_matches_on_size_when_available(self):
        self._save("Album A", "Trung ten.mp3", size=100)
        self._save("Album B", "Trung ten.mp3", size=200)
        self.assertEqual(find_offline_copy(self.music, "Trung ten.mp3", 200),
                         offline_path(self.music, "Album B", "Trung ten.mp3"))

    def test_different_size_is_not_a_match(self):
        self._save("Album A", "Khac kich thuoc.mp3", size=100)
        self.assertEqual(find_offline_copy(self.music, "Khac kich thuoc.mp3", 999), "")

    def test_unknown_track_returns_empty(self):
        self.assertEqual(find_offline_copy(self.music, "khong-co.mp3"), "")

    def test_index_covers_every_saved_folder(self):
        self._save("A", "a.mp3")
        self._save("B/C", "c.mp3")
        index = offline_index(self.music, 0)
        self.assertIn("a.mp3", index)
        self.assertIn("c.mp3", index)

    def test_offline_job_finishes_and_refreshes_index(self):
        saved = self._save("Album A", "Bai hat.mp3")
        self.assertTrue(os.path.isfile(saved))
        with mock.patch.object(
                drive_module, "_download_to_path",
                return_value=saved) as download:
            job = start_offline_job(self.app_dir, self.music, "Album A",
                                    entry(name="Bai hat.mp3"), "")
            for _ in range(50):
                if job.done:
                    break
                time.sleep(0.02)
        self.assertTrue(job.done)
        self.assertEqual(job.kind, "offline")
        self.assertEqual(job.album, "Album A")


class AppDownloadUiTests(unittest.TestCase):
    def _app(self, music_dir=None, app_dir="/app", data_dir="/data"):
        app = MusicPlayerApp.__new__(MusicPlayerApp)
        values = {"drive_folder_id": "FOLDERID1234567890", "drive_api_key": ""}
        app.settings = mock.Mock()
        app.settings.get.side_effect = values.get
        app.paths = mock.Mock(app_dir=app_dir, data_dir=data_dir,
                              music_dir=music_dir)
        app.screen = "playing"
        app.download_job = None
        app._saved_toast = ("", 0.0)
        app._saved_rows = {}
        app.drive_entries = []
        app.status = ""
        app.status_error = False
        app.tracks = []
        return app

    def test_save_starts_background_job_instead_of_blocking(self):
        app = self._app()
        job = StreamJob("offline:/x/song.mp3", "song", 100, "offline")
        job.done = True
        job.path = "/music/Drive/A/song.mp3"
        with mock.patch("musicplayer.ui.drive_start_offline_job",
                        return_value=job) as start, \
                mock.patch("musicplayer.ui.drive_find_offline_copy", return_value=""):
            app._save_entry_offline(entry(), "A")
        start.assert_called_once()
        self.assertEqual(app.download_job, None)

    def test_saved_toast_shows_short_name_not_full_path(self):
        app = self._app()
        job = StreamJob("offline:/very/long/path/song.mp3", "song", 100, "offline",
                     album="Album")
        job.done = True
        job.path = "/mnt/SDCARD/Music/Drive/Album/song.mp3"
        with mock.patch("musicplayer.ui.drive_start_offline_job",
                        return_value=job), \
                mock.patch("musicplayer.ui.drive_find_offline_copy", return_value=""), \
                mock.patch("musicplayer.library.scan_library", return_value=[]):
            app._save_entry_offline(entry(), "Album")
        self.assertTrue(app._saved_toast[0])
        self.assertNotIn("/mnt/SDCARD", app._saved_toast[0])
        self.assertIn("Album", app._saved_toast[0])

    def test_existing_copy_skips_download(self):
        app = self._app()
        with mock.patch("musicplayer.ui.drive_find_offline_copy",
                        return_value="/music/Drive/B/song.mp3") as found, \
                mock.patch("musicplayer.ui.drive_start_offline_job") as start:
            app._save_entry_offline(entry(), "A")
        found.assert_called_once()
        start.assert_not_called()
        self.assertIn("Already on this device", app.status)

    def test_resolve_does_not_block_on_download(self):
        """Khong duoc tai trong thread chinh: phai start job roi CHO co ve khung."""
        app = self._app()
        app.controllers = []
        app.running = True
        rendered = []

        def slow_job(a, d, e, k=""):
            job = StreamJob(e.file_id, e.title, e.size, "stream")
            def worker():
                for step in range(1, 5):
                    time.sleep(0.01)
                    job.update(step * 25)
                job.done = True
                job.path = "/data/drive-cache/x.mp3"
            threading.Thread(target=worker, daemon=True).start()
            return job

        with mock.patch("musicplayer.ui.drive_start_stream_job", side_effect=slow_job), \
                mock.patch.object(app, "_render", side_effect=lambda: rendered.append(1)), \
                mock.patch.object(app, "runtime", create=True) as runtime:
            runtime.SDL_PollEvent.return_value = 0
            runtime.SDL_Delay.return_value = None
            path = app._drive_resolve_track(
                mock.Mock(path="drive://FILEID1234567890/song.mp3"))
        self.assertEqual(path, "/data/drive-cache/x.mp3")
        self.assertTrue(rendered, "phai ve khung trong luc cho tai (khong treo)")
        self.assertEqual(app.download_job, None, "phai xoa job sau khi xong")

    def test_row_marked_saved_when_copy_exists(self):
        app = self._app()
        row = entry()
        with mock.patch("musicplayer.ui.drive_find_offline_copy",
                        return_value="/music/Drive/Z/song.mp3"):
            self.assertTrue(app._drive_row_is_saved(row))
        app._invalidate_saved_rows()
        with mock.patch("musicplayer.ui.drive_find_offline_copy", return_value=""):
            self.assertFalse(app._drive_row_is_saved(row))

    def test_render_drive_with_badge_does_not_crash(self):
        """Regression: badge 'ON DEVICE' cong measure() nham tuple -> TypeError.

        measure() tra (width, height); code ve duoc chay that voi stub dung
        hinh dang tra ve de bat loi cong so nham tuple.
        """
        app = self._app()
        app.width, app.height = 1024, 768
        app.scroll = 0
        app.selection = 0
        app.drive_page_token = ""
        app.drive_busy = False
        app.drive_loaded = True
        app.drive_stack = []
        app._saved_toast = ("", 0.0)
        app.drive_entries = [
            DriveEntry(file_id="F1", name="Bai hat rat dai va co ten thuong.mp3",
                       mime_type="", size=3 * 1024 * 1024, is_folder=True,
                       title="Bai hat rat dai va co ten thuong", extension=""),
            entry(name="song.mp3"),
            DriveEntry(file_id="F2", name="khac.mp3", mime_type="", size=5,
                       is_folder=False, title="khac", extension=".mp3"),
        ]
        app.fill = mock.Mock(side_effect=lambda *a: None)
        drawn = []
        app.text = mock.Mock(side_effect=lambda t, *a, **k: drawn.append(t))
        # Giong het TTF thật: tra tuple (width, height).
        app.measure = mock.Mock(side_effect=lambda t, font: (len(t) * 9, 14))
        with mock.patch("musicplayer.ui.drive_find_offline_copy",
                        return_value="/music/Drive/A/song.mp3"):
            app._render_drive()  # phai khong nem
        self.assertIn("ON DEVICE", drawn)
        # Render lai khi co toast + khong co badge -> cung phai an toan.
        app._saved_toast = ("Album / song", time.monotonic())
        drawn.clear()
        app._render_drive()
        self.assertTrue(drawn)

    def test_offline_job_poll_reports_failure(self):
        app = self._app()
        job = StreamJob("offline:/x/song.mp3", "song", 0, "offline")
        job.done = True
        job.error = "Drive network: offline"
        app.download_job = job
        app._poll_offline_job()
        self.assertEqual(app.download_job, None)
        self.assertTrue(app.status_error)

    def test_toast_expires_and_reserves_row_space(self):
        """Ô "đã lưu" tự tắt và chừa chỗ để breadcrumb không bị đè."""
        app = self._app()
        app.width, app.height = 1024, 768
        app.runtime = mock.Mock()
        app.renderer = mock.Mock()
        app.fill = mock.Mock(side_effect=lambda *a: None)
        app.text = mock.Mock(side_effect=lambda *a, **k: None)
        app.measure = mock.Mock(return_value=(100, 12))
        self.assertEqual(app._toast_width(), 0)
        app._saved_toast = ("Album / song", time.monotonic() - 30.0)
        self.assertEqual(app._toast_width(), 0, "qua 8 giay phai bien mat")
        app._saved_toast = ("Album / song", time.monotonic())
        self.assertEqual(app._toast_width(), 100 + 28 + 24 + 8)
        app._render_saved_toast()
        self.assertIsNotNone(app._saved_toast)
        app._saved_toast = ("Album / song", time.monotonic() - 9.0)
        app._render_saved_toast()
        self.assertIsNone(app._saved_toast)

    def test_progress_overlay_shows_percent_text(self):
        app = self._app()
        app.width, app.height = 1024, 768
        job = StreamJob("F1", "song", 200, "stream")
        job.update(100)
        app.download_job = job
        drawn = []
        app.fill = mock.Mock(side_effect=lambda *a: None)
        app.text = mock.Mock(side_effect=lambda t, *a, **k: drawn.append(t))
        app.ellipsize = mock.Mock(side_effect=lambda t, *a, **k: t)
        app._render_download_progress()
        self.assertIn("50%", drawn)
        self.assertIn("BUFFERING", drawn)

    def test_progress_overlay_offline_says_downloading(self):
        app = self._app()
        app.width, app.height = 1024, 768
        job = StreamJob("offline:/x/song.mp3", "song", 200, "offline")
        job.update(200)
        app.download_job = job
        drawn = []
        app.fill = mock.Mock(side_effect=lambda *a: None)
        app.text = mock.Mock(side_effect=lambda t, *a, **k: drawn.append(t))
        app.ellipsize = mock.Mock(side_effect=lambda t, *a, **k: t)
        app._render_download_progress()
        self.assertIn("DOWNLOADING", drawn)
        self.assertIn("100%", drawn)
        self.assertIn("B cancel", " ".join(drawn))


if __name__ == "__main__":
    unittest.main(verbosity=2)