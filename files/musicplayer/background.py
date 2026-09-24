import json
import os
import signal
import time

from .audio import AudioPlayer
from .library import Track
from .logger import get_logger
from .reporter import queue_report
from .settings import Settings, atomic_json_write
from .sleep_timer import SleepTimer
from .sdl_runtime import SDL_INIT_AUDIO, SDLRuntime


BACKGROUND_EXIT = 20
SESSION_NAME = "background-session.json"
COMMAND_NAME = "background-command"
PID_NAME = "background.pid"
STATUS_NAME = "background-status.json"
RESUME_NAME = "background-resume.json"


def background_path(paths, name):
    return os.path.join(paths.data_dir, name)


def _remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _track(path, music_dir):
    folder = os.path.relpath(os.path.dirname(path), music_dir)
    return Track(
        path=path,
        title=os.path.splitext(os.path.basename(path))[0],
        folder="Music" if folder == "." else folder,
        extension=os.path.splitext(path)[1].lower(),
    )


def save_background_session(paths, player, sleep_timer):
    current = player.current
    if not current or not player.music:
        return False
    sleep_value = None
    if sleep_timer.active:
        remaining = sleep_timer.remaining()
        sleep_value = {
            "preset": sleep_timer.preset_index,
            "remaining": remaining,
            "track_path": sleep_timer.track_path,
        }
    session = {
        "tracks": [track.path for track in player.tracks if os.path.isfile(track.path)],
        "current_path": current.path,
        "position": player.position(),
        "paused": bool(player.runtime.Mix_PausedMusic()),
        "sleep_timer": sleep_value,
    }
    atomic_json_write(background_path(paths, SESSION_NAME), session)
    _remove(background_path(paths, RESUME_NAME))
    return True


def load_resume(paths):
    path = background_path(paths, RESUME_NAME)
    fallback = background_path(paths, STATUS_NAME)
    value = None
    for candidate in (path, fallback):
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, dict):
                break
        except (OSError, ValueError, TypeError):
            value = None
    _remove(path)
    _remove(fallback)
    return value if isinstance(value, dict) else None


class BackgroundPlayback:
    def __init__(self, paths):
        self.paths = paths
        self.running = True
        self.foreground_requested = False
        self.runtime = None
        self.player = None
        self.settings = None
        self.sleep_timer = SleepTimer()
        self.last_status = 0.0

    def _load_session(self):
        with open(background_path(self.paths, SESSION_NAME), "r", encoding="utf-8") as handle:
            session = json.load(handle)
        paths = [path for path in session.get("tracks", []) if os.path.isfile(path)]
        current_path = session.get("current_path", "")
        if current_path not in paths or not paths:
            raise ValueError("background track is no longer available")
        tracks = [_track(path, self.paths.music_dir) for path in paths]
        return session, tracks, paths.index(current_path)

    def _restore_sleep_timer(self, value):
        if not isinstance(value, dict):
            return
        preset = int(value.get("preset", 0))
        if preset == 6:
            self.sleep_timer.set(preset, value.get("track_path", ""))
        elif 0 < preset < 6:
            remaining = max(0, int(value.get("remaining", 0)))
            self.sleep_timer.preset_index = preset
            self.sleep_timer.deadline = time.monotonic() + remaining

    def _read_command(self):
        path = background_path(self.paths, COMMAND_NAME)
        try:
            with open(path, "r", encoding="ascii") as handle:
                command = handle.read(32).strip()
        except OSError:
            return
        _remove(path)
        if command in ("foreground", "stop"):
            self.foreground_requested = command == "foreground"
            self.running = False
            get_logger().info("background command=%s", command)

    def _write_status(self):
        now = time.monotonic()
        if now - self.last_status < 1.0:
            return
        self.last_status = now
        current = self.player.current
        sleep_value = None
        if self.sleep_timer.active:
            sleep_value = {
                "preset": self.sleep_timer.preset_index,
                "remaining": self.sleep_timer.remaining(),
                "track_path": self.sleep_timer.track_path,
            }
        atomic_json_write(background_path(self.paths, STATUS_NAME), {
            "pid": os.getpid(),
            "track_path": current.path if current else "",
            "position": self.player.position(),
            "paused": bool(self.player.music and self.runtime.Mix_PausedMusic()),
            "audio_ready": self.player.audio_ready,
            "sleep_timer": sleep_value,
        })

    def _write_resume(self):
        if not self.foreground_requested or not self.player.current:
            return
        sleep_value = None
        if self.sleep_timer.active:
            sleep_value = {
                "preset": self.sleep_timer.preset_index,
                "remaining": self.sleep_timer.remaining(),
                "track_path": self.sleep_timer.track_path,
            }
        atomic_json_write(background_path(self.paths, RESUME_NAME), {
            "track_path": self.player.current.path,
            "position": self.player.position(),
            "paused": bool(self.player.music and self.runtime.Mix_PausedMusic()),
            "sleep_timer": sleep_value,
        })

    def _cleanup_files(self):
        _remove(background_path(self.paths, SESSION_NAME))
        _remove(background_path(self.paths, COMMAND_NAME))
        _remove(background_path(self.paths, STATUS_NAME))
        pid_path = background_path(self.paths, PID_NAME)
        try:
            with open(pid_path, "r", encoding="ascii") as handle:
                owner = int(handle.read().strip())
        except (OSError, ValueError):
            owner = 0
        if owner in (0, os.getpid()):
            _remove(pid_path)

    def run(self):
        session, tracks, index = self._load_session()
        self.settings = Settings(self.paths.settings_file).load()
        self.runtime = SDLRuntime(self.paths)
        if self.runtime.SDL_Init(SDL_INIT_AUDIO) != 0:
            raise RuntimeError("background SDL audio initialization failed: %s" % self.runtime.error())
        self.player = AudioPlayer(self.runtime, tracks, self.settings)
        try:
            if not self.player.initialize() or not self.player.play(index):
                raise RuntimeError(self.player.error or "background audio is unavailable")
            position = max(0.0, float(session.get("position", 0.0)))
            if position >= 1.0 and not self.player.seek(position - self.player.position()):
                get_logger().warning("background playback could not restore position")
            if session.get("paused"):
                self.player.toggle_pause()
            self._restore_sleep_timer(session.get("sleep_timer"))
            get_logger().info("background playback started pid=%d", os.getpid())
            while self.running:
                if not os.path.exists("/tmp/stay_alive"):
                    try:
                        with open("/tmp/stay_alive", "a", encoding="ascii"):
                            pass
                    except OSError:
                        pass
                self._read_command()
                current = self.player.current
                paused = bool(self.player.music and self.runtime.Mix_PausedMusic())
                playing = bool(self.player.music and self.runtime.Mix_PlayingMusic())
                if self.sleep_timer.active and self.sleep_timer.expired(
                    current.path if current else "", playing, paused
                ):
                    self.player.fade_stop()
                    self.running = False
                if self.running:
                    self.player.update()
                if not self.player.music and not self.player.started:
                    self.running = False
                self._write_status()
                time.sleep(0.08)
            self._write_resume()
            return 0
        finally:
            if self.player:
                self.player.close()
            if self.settings:
                self.settings.save()
            if self.runtime:
                self.runtime.SDL_Quit()
            self._cleanup_files()
            if not self.foreground_requested:
                _remove("/tmp/stay_alive")
            get_logger().info("background playback stopped")


def run_background(paths):
    service = BackgroundPlayback(paths)

    def stop(unused_signum, unused_frame):
        service._read_command()
        service.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return service.run()
    except Exception as error:
        get_logger().exception("background playback failed")
        queue_report(paths, "background_playback_failed", str(error))
        service._cleanup_files()
        _remove("/tmp/stay_alive")
        return 1
