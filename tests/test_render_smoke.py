# -*- coding: utf-8 -*-
"""Smoke test cho _render: chay THAT moi man hinh va moi trang thai.

Ly do: mot loi cong sai kieu duy nhat trong code ve (measure() tra tuple
nhung duoc cong nhu so) da lam app crash ngay khi mo thu muc nhac Drive -
va khong test nao bat duoc vi chung deu bo qua _render. Bai nay ve thu
trong khi chi stub SDL, nen bat duoc dung loi do.

Stub khong gia lap so ngau nhien: measure() tra (width, height) nhu TTF that,
fill/text chi ghi lai, con moi ham ve cua app chay nguyen ban.
"""
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
if FILES not in sys.path:
    sys.path.insert(0, FILES)

from musicplayer import drive as drive_module  # noqa: E402
from musicplayer.drive import DriveEntry  # noqa: E402
from musicplayer.library import Track  # noqa: E402
from musicplayer.ui import MusicPlayerApp  # noqa: E402

FONTS = ("giant", "hero", "title", "body", "small")


def track(title="Bai hat", path="/music/song.mp3", folder="Album"):
    return Track(path=path, title=title, folder=folder, extension=".mp3")


class RenderSmokeTests(unittest.TestCase):
    """Moi man hinh phai ve duoc ma khong nem."""

    def setUp(self):
        with drive_module._JOBS_LOCK:
            drive_module._JOBS.clear()
        paths = mock.Mock(
            os_name="StockOS", os_version="1.0", app_dir="/app",
            data_dir="/data", music_dir="/music", settings_file="s.json",
            collections_file="c.json", identity_file="i.json",
            cache_dir="/data/cache", log_file="/data/music-player.log",
        )
        tracks = [track(), track("Bai 2", "/music/song2.mp3"),
                  track("Drive", "drive://F1/song.mp3", "Drive/Album")]
        # Dung __init__ THAT (chi stub phan I/O) de app co day du thuoc tinh,
        # tranh bo sot truong moi them vao lam man hinh render no.
        with mock.patch("musicplayer.ui.Settings"), \
                mock.patch("musicplayer.ui.installation_id",
                           return_value="ABCD1234"), \
                mock.patch("musicplayer.ui.Collections"), \
                mock.patch("musicplayer.ui.DisplayController"), \
                mock.patch("musicplayer.ui.InputState"), \
                mock.patch("musicplayer.ui.SleepTimer"):
            app = MusicPlayerApp(paths, tracks)
        app.settings = mock.Mock()
        app.settings.get.side_effect = {
            "drive_folder_id": "FOLDERID1234567890", "drive_api_key": "",
            "intro": False, "shuffle": False, "repeat": "off",
        }.get
        app.sleep_timer = mock.Mock(active=False, status=mock.Mock(return_value=""))
        app.display = mock.Mock(is_off=False)
        app.runtime = mock.Mock()
        app.renderer = mock.Mock()
        app.width, app.height = 1024, 768
        app.fonts = {name: mock.Mock() for name in FONTS}
        # Giong het TTF that: (width, height), khong phai so.
        app.measure = mock.Mock(side_effect=lambda t, font: (len(t) * 9, 14))
        app.fill = mock.Mock(side_effect=lambda *a: None)
        self.drawn = []
        app.text = mock.Mock(side_effect=lambda t, *a, **k: self.drawn.append(t))
        app.library_mode = "all"
        app.selection = 0
        app.scroll = 0
        app.status = ""
        app.status_error = False
        app.drive_loaded = True
        app._saved_rows = {}
        app.player = mock.Mock(
            audio_ready=True, output_device="System / Bluetooth",
            error="", current=tracks[0], index=0, tracks=tracks,
        )
        app.player.position.return_value = 12.0
        app.player.duration.return_value = 180.0
        app.player.spectrum.return_value = [0.5, 0.2, 0.8, 0.1] * 12
        self.app = app

    def _render(self, screen):
        self.app.screen = screen
        self.app._render()

    def test_library_screen_all_modes(self):
        for mode in ("all", "source", "drive", "collections"):
            self.app.library_mode = mode
            with self.subTest(mode=mode):
                self._render("library")

    def test_drive_rows_with_saved_badge_and_toast(self):
        self.app.library_mode = "drive"
        # drive_stack la danh sach (folder_id, ten) - dung kieu cua app that.
        self.app.drive_stack = [("F1", "Drive 2")]
        self.app.drive_entries = [
            DriveEntry(file_id="slot:0", name="Drive 1", mime_type="",
                       size=0, is_folder=True, title="Drive 1", extension=""),
            DriveEntry(file_id="F1", name="Bai toi lau.mp3", mime_type="",
                       size=3 * 1024 * 1024, is_folder=False,
                       title="Bai toi lau", extension=".mp3"),
            DriveEntry(file_id="F2", name="Bai ke tiep.flac", mime_type="",
                       size=0, is_folder=False, title="Bai ke tiep",
                       extension=".flac"),
        ]
        self.app.drive_page_token = "next-token"
        with mock.patch("musicplayer.ui.drive_find_offline_copy",
                        return_value="/music/Drive/A/Bai toi lau.mp3"):
            self._render("library")
        self.assertIn("ON DEVICE", self.drawn)
        # Co toast thi breadcrumb phai rut ngan, khong duoc nem.
        self.drawn.clear()
        self.app._saved_toast = ("Album / Bai toi lau", time.monotonic())
        with mock.patch("musicplayer.ui.drive_find_offline_copy", return_value=""):
            self._render("library")
        self.assertTrue(self.drawn)

    def test_drive_empty_and_loading_states(self):
        self.app.library_mode = "drive"
        self.app.drive_entries = []
        self.app.drive_page_token = ""
        self._render("library")
        self.app.drive_busy = True
        self.app.drive_loaded = False
        self._render("library")

    def test_playing_with_and_without_track(self):
        self._render("playing")
        self.app.player.current = None
        self._render("playing")

    def test_other_screens(self):
        for screen in ("addrive", "lyrics"):
            with self.subTest(screen=screen):
                self._render(screen)

    def test_quick_menu_and_exit_confirmation_overlays(self):
        for page in ("main", "drive", "settings", "about"):
            self.app.quick_menu = True
            self.app.quick_menu_page = page
            with self.subTest(page=page):
                self._render("library")
        self.app.quick_menu = False
        self.app.exit_confirmation = True
        self._render("library")

    def test_download_progress_over_every_screen(self):
        """Thanh % phai che duoc tren ca man hinh ma khong nem."""
        job = drive_module.StreamJob("F1", "Bai hat", 1000, "stream")
        job.update(400)
        for screen in ("library", "playing", "lyrics", "addrive"):
            with self.subTest(screen=screen):
                self.app.download_job = job
                self._render(screen)
        self.app.download_job = None

    def test_saved_toast_on_every_screen(self):
        self.app._saved_toast = ("Album / Bai hat rat co ten dai hon", time.monotonic())
        for screen in ("library", "playing", "lyrics", "addrive"):
            with self.subTest(screen=screen):
                self._render(screen)

    def test_tiny_and_wide_screens(self):
        """Kich thuoc toi thieu cua may + man hinh rat rong phai khong nem."""
        for width, height in ((1024, 768), (1280, 720), (480, 272)):
            self.app.width, self.app.height = width, height
            with self.subTest(size=(width, height)):
                self._render("library")
                self._render("playing")

    def test_title_with_very_long_names(self):
        long_name = "Bai hat tieng Viet co dau rat la day va lai rat dai " * 4
        self.app.tracks = [track(long_name)]
        self.app.player.current = self.app.tracks[0]
        self._render("playing")
        self.app.library_mode = "drive"
        self.app.drive_stack = [("F1", long_name)]
        self.app.drive_entries = [
            DriveEntry(file_id="F1", name=long_name + ".mp3", mime_type="",
                       size=1, is_folder=False, title=long_name, extension=".mp3"),
        ]
        self._render("library")


if __name__ == "__main__":
    unittest.main(verbosity=2)