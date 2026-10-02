#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ve bang thu lai cac man hinh cua Music Player ra PNG de nhin truc tiep.

Dung ham ve THAT cua app; chi thay SDL bang PIL, va do chu dung bang TTF that
(arial). Dung khi sua layout: py -3 tools/preview_render.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "files"))

from musicplayer import drive as drive_module  # noqa: E402
from musicplayer.drive import DriveEntry  # noqa: E402
from musicplayer.library import Track  # noqa: E402
from musicplayer.ui import MusicPlayerApp  # noqa: E402

FONT_PATH = "C:/Windows/Fonts/arial.ttf"
FONT_SIZES = {"giant": 130, "hero": 44, "title": 26, "body": 18, "small": 13}
OUT_DIR = os.path.join(ROOT, "dist", "preview")


def font(name):
    return ImageFont.truetype(FONT_PATH, FONT_SIZES.get(name, 14))


def rgba(color):
    return tuple(color[:3]) + (color[3] if len(color) > 3 else 255,)


class Preview:
    """Thay the SDL renderer bang PIL, giu nguyen ham ve cua app."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = {name: font(name) for name in FONT_SIZES}

    # --- API giong app: do va ve do app goi ---
    def measure(self, text, font_name="body"):
        if not text:
            return 0, FONT_SIZES.get(font_name, 14)
        left, top, right, bottom = self.fonts[font_name].getbbox(str(text))
        return right - left, bottom - top

    def fill(self, x, y, width, height, color):
        if width <= 0 or height <= 0:
            return
        self.draw.rectangle([int(x), int(y), int(x + width), int(y + height)],
                            fill=rgba(color))

    def text(self, text, x, y, font_name="body", color=None, center=False):
        text = str(text)
        if center:
            x = x - self.measure(text, font_name)[0] // 2
        self.draw.text((int(x), int(y)), text, font=self.fonts[font_name],
                       fill=rgba(color or (0, 0, 0, 255)))

    def save(self, name):
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, name)
        self.image.convert("RGB").save(path)
        print("wrote %s" % path)

    # --- SDL stubs: app goi truc tiep mot so ham nay khi ve ---
    def SDL_SetRenderDrawColor(self, *a):
        pass

    def SDL_RenderClear(self, *a):
        self.draw.rectangle([0, 0, self.width, self.height],
                            fill=(255, 255, 255, 255))

    def SDL_RenderPresent(self, *a):
        pass


def build_app(screen="library", mode="drive", width=1024, height=768):
    paths = mock_paths()
    tracks = [
        Track(path="/mnt/SDCARD/Music/Bai hat cua toi.mp3", title="Bai hat cua toi",
              folder="Music", extension=".mp3"),
        Track(path="/mnt/SDCARD/Music/Drive/Nhac Viet/Bai da luu roi.mp3",
              title="Bai da luu roi", folder="Drive/Nhac Viet", extension=".mp3"),
    ]

    class Fake:
        def __init__(self, *a, **k):
            pass

        def load(self):
            return self

        def is_track_favorite(self, path):
            return False

        def is_playlist_favorite(self, name):
            return False

    import musicplayer.ui as ui_module
    saved = {}
    for name in ("Settings", "installation_id", "Collections", "DisplayController",
                 "InputState", "SleepTimer"):
        saved[name] = getattr(ui_module, name)
    ui_module.Settings = Fake
    ui_module.Collections = Fake
    ui_module.installation_id = lambda p: "ABCD1234"
    ui_module.DisplayController = Fake
    ui_module.InputState = Fake
    ui_module.SleepTimer = Fake
    try:
        app = MusicPlayerApp(paths, tracks)
    finally:
        for name, value in saved.items():
            setattr(ui_module, name, value)

    app.settings = FakeSettings()
    app.sleep_timer = FakeTimer()
    app.display = FakeDisplay()
    app.width, app.height = width, height
    app.screen = screen
    app.library_mode = mode
    app.selection = 0
    app.scroll = 0
    app.status = ""
    app.status_error = False
    app.quick_menu = False
    app.exit_confirmation = False
    app.drive_loaded = True
    app.drive_stack = [("F1", "Drive 2")]
    app.drive_entries = [
        DriveEntry(file_id="F1", name="Bai chua luu.mp3", mime_type="",
                   size=7 * 1024 * 1024, is_folder=False, title="Bai chua luu",
                   extension=".mp3"),
        DriveEntry(file_id="F2", name="Bai da luu roi.mp3", mime_type="",
                   size=5 * 1024 * 1024, is_folder=False, title="Bai da luu roi",
                   extension=".mp3"),
        DriveEntry(file_id="F3", name="Vol 2 - Mot bai rat co ten dai.mp3",
                   mime_type="", size=3 * 1024 * 1024, is_folder=False,
                   title="Vol 2 - Mot bai rat co ten dai", extension=".mp3"),
    ]
    app.preview = Preview(width, height)
    app.runtime = app.preview
    app.renderer = app.preview
    # app.fill/text/measure goi sang preview
    app.fill = app.preview.fill
    app.text = app.preview.text
    app.measure = app.preview.measure
    return app


class FakeSettings:
    values = {"drive_folder_id": "FOLDERID1234567890", "drive_api_key": "",
              "intro": False, "shuffle": False, "repeat": "off"}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeTimer:
    active = False

    def status(self):
        return ""


class FakeDisplay:
    is_off = False


class FakePlayer:
    audio_ready = True
    output_device = "System / Bluetooth"
    error = ""

    def __init__(self, track):
        self.current = track
        self.index = 0

    def position(self):
        return 72.0

    def duration(self):
        return 240.0

    def spectrum(self):
        return [0.4, 0.9, 0.2, 0.7, 0.3, 0.5, 0.8, 0.1] * 6


def mock_paths():
    class Paths:
        os_name = "StockOS"
        os_version = "1.0"
        app_dir = "/app"
        data_dir = "/data"
        music_dir = "/mnt/SDCARD/Music"
        settings_file = "s.json"
        collections_file = "c.json"
        identity_file = "i.json"
    return Paths()


def main():
    # 1. Danh sach Drive: co bai dang tai (% tai cho) + bai da co ON DEVICE.
    app = build_app("library", "drive")
    app.player = FakePlayer(app.tracks[0])
    app._saved_toast = ("Bai da luu roi", 9e9)
    entry = app.drive_entries[0]
    job = drive_module.StreamJob("offline:/x/Bai chua luu.mp3", "Bai chua luu",
                                 7 * 1024 * 1024, "offline", entry=entry)
    job.update(2 * 1024 * 1024 + 300 * 1024)
    app.download_job = job
    drive_module._OFFLINE_INDEX["items"] = {"Bai da luu roi.mp3": [("x", 5242880)]}
    drive_module._OFFLINE_INDEX["at"] = 9e9
    app._render()
    app.preview.save("01-drive-list-with-inline-progress.png")

    # 2. Man hinh phat: dang luu bai Drive -> dai nho duoi header.
    app = build_app("playing")
    app.player = FakePlayer(app.tracks[1])
    app.download_job = drive_module.StreamJob(
        "offline:/x/Bai da luu roi.mp3", "Bai da luu roi", 5 * 1024 * 1024,
        "offline", entry=DriveEntry(file_id="F2", name="Bai da luu roi.mp3",
                                    mime_type="", size=5 * 1024 * 1024,
                                    is_folder=False, title="Bai da luu roi",
                                    extension=".mp3"))
    app.download_job.update(3 * 1024 * 1024)
    app._render()
    app.preview.save("02-playing-download-strip.png")

    # 3. Thong bao xong: chi ten bai, khong duong dan.
    app = build_app("playing")
    app.player = FakePlayer(app.tracks[1])
    app._saved_toast = ("Bai da luu roi", 9e9)
    app.status = "Saved: Bai da luu roi"
    app._render()
    app.preview.save("03-saved-toast-name-only.png")

    # 4. Thu vien local + bai vua luu co badge ON DEVICE.
    app = build_app("library", "all")
    app.player = FakePlayer(app.tracks[0])
    drive_module._OFFLINE_INDEX["items"] = {"Bai da luu roi.mp3": [("x", 5242880)]}
    drive_module._OFFLINE_INDEX["at"] = 9e9
    app._render()
    app.preview.save("04-local-library-saved-badge.png")

    # 5. Man hinh rong 1280x720.
    app = build_app("library", "drive", 1280, 720)
    app.player = FakePlayer(app.tracks[0])
    app.drive_entries = [app.drive_entries[0]]
    app.download_job = drive_module.StreamJob(
        "offline:/x/Bai chua luu.mp3", "Bai chua luu", 7 * 1024 * 1024,
        "offline", entry=app.drive_entries[0])
    app.download_job.update(4 * 1024 * 1024)
    app._render()
    app.preview.save("05-drive-list-1280x720.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())