import os
from dataclasses import dataclass


def _first_existing(candidates):
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(next(candidate for candidate in candidates if candidate))


def _sdcard_from_app(app_dir):
    current = os.path.abspath(app_dir)
    while True:
        parent = os.path.dirname(current)
        if os.path.basename(parent).lower() in ("app", "apps", "tools"):
            return os.path.dirname(parent)
        if parent == current:
            return ""
        current = parent


def detect_os(sdcard_path, environ=None):
    if environ is None:
        environ = os.environ
    values = " ".join(
        environ.get(name, "")
        for name in ("OS", "OS_NAME", "FIRMWARE", "PLATFORM", "SPRUCE_VERSION", "MUSIC_PLAYER_OS")
    ).lower()
    markers = (
        os.path.join(sdcard_path, ".spruce"),
        os.path.join(sdcard_path, "spruce"),
        os.path.join(sdcard_path, "Spruce"),
    )
    if "spruce" in values or any(os.path.exists(path) for path in markers):
        return "spruce"
    if environ.get("IS_NEXT") == "yes":
        return "nextui"
    return "stock"


@dataclass(frozen=True)
class RuntimePaths:
    app_dir: str
    sdcard_path: str
    music_dir: str
    data_dir: str
    settings_file: str
    log_file: str
    stdio_log_file: str
    pending_reports_file: str
    os_name: str

    @classmethod
    def discover(cls, app_dir=None, environ=None):
        if environ is None:
            environ = os.environ
        app_dir = os.path.abspath(app_dir or os.path.dirname(os.path.dirname(__file__)))
        inferred_sdcard = _sdcard_from_app(app_dir)
        sdcard_path = _first_existing([
            environ.get("SDCARD_PATH"), inferred_sdcard, "/mnt/SDCARD",
            "/mnt/mmc", "/userdata", "/roms", app_dir,
        ])
        music_dir = _first_existing([
            environ.get("MUSIC_PLAYER_MUSIC_DIR"),
            os.path.join(sdcard_path, "Music"),
            os.path.join(sdcard_path, "Media", "Music"),
            os.path.join(sdcard_path, "Roms", "MUSIC"),
            os.path.join(sdcard_path, "ROMS", "MUSIC"),
        ])
        data_dir = os.path.join(app_dir, "data")
        return cls(
            app_dir=app_dir,
            sdcard_path=sdcard_path,
            music_dir=music_dir,
            data_dir=data_dir,
            settings_file=os.path.join(data_dir, "settings.json"),
            log_file=os.path.join(app_dir, "music-player.log"),
            stdio_log_file=os.path.join(app_dir, "music-player-stdio.log"),
            pending_reports_file=os.path.join(data_dir, "pending-reports.json"),
            os_name=detect_os(sdcard_path, environ),
        )

    def ensure_writable_dirs(self):
        os.makedirs(self.music_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
