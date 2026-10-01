import os
import time

FRAME_PATHS = (
    "/sys/class/led_anim/frame_hex",
)
EFFECT_PATHS = (
    "/sys/class/led_anim/effect_enable",
    "/sys/class/led_anim/enable",
)
WRITE_INTERVAL = 0.06
IDLE_TIMEOUT = 1.5


def _first_existing(paths):
    for path in paths:
        try:
            if os.path.exists(path):
                return path
        except OSError:
            continue
    return ""


def _wheel(position):
    position = int(position) % 96
    if position < 32:
        red = 255 - position * 8
        green = position * 8
        blue = 0
    elif position < 64:
        position -= 32
        red = 0
        green = 255 - position * 8
        blue = position * 8
    else:
        position -= 64
        red = position * 8
        green = 0
        blue = 255 - position * 8
    return (max(0, min(255, red)), max(0, min(255, green)), max(0, min(255, blue)))


def frame_for_levels(levels, rms, beat, tick):
    count = max(1, len(levels)) if levels else 1
    parts = []
    for i in range(count):
        level = 0.0
        try:
            level = float(levels[i])
        except (IndexError, TypeError, ValueError):
            level = 0.0
        level = max(0.0, min(1.0, level))
        boost = 1.25 if beat else 1.0
        brightness = max(0.0, min(1.0, (0.08 + level * 0.92) * boost))
        hue = (tick * 2 + i * (96 // max(1, count))) % 96
        red, green, blue = _wheel(hue)
        red = int(red * brightness)
        green = int(green * brightness)
        blue = int(blue * brightness)
        parts.append("%02X%02X%02X" % (red, green, blue))
    if beat:
        parts = [("FFFFFF" if (i + tick) % count == 0 else part) for i, part in enumerate(parts)]
    if not parts:
        dim = int(max(0.0, min(1.0, rms)) * 40)
        parts = ["%02X%02X%02X" % (dim, dim, dim)]
    return "".join(parts)


class LedController:
    def __init__(self, frame_path="", effect_path=""):
        self.frame_path = frame_path or _first_existing(FRAME_PATHS)
        self.effect_path = effect_path or _first_existing(EFFECT_PATHS)
        self._last_write = 0.0
        self._tick = 0
        self._last_levels = ()
        self.enabled = bool(self.frame_path)
        self.suspended = False
        self.errors = 0

    @property
    def available(self):
        return self.enabled

    def suspend_engine(self):
        if not self.effect_path:
            return False
        try:
            with open(self.effect_path, "w", encoding="ascii") as handle:
                handle.write("0")
            self.suspended = True
            return True
        except OSError:
            return False

    def restore_engine(self):
        if not self.effect_path or not self.suspended:
            return False
        try:
            with open(self.effect_path, "w", encoding="ascii") as handle:
                handle.write("1")
            return True
        except OSError:
            return False
        finally:
            self.suspended = False

    def update(self, levels, rms, beat, force=False):
        if not self.available:
            return False
        now = time.monotonic()
        if not force and now - self._last_write < WRITE_INTERVAL:
            return False
        if not force and tuple(levels) == self._last_levels and now - self._last_write < IDLE_TIMEOUT:
            if (rms or 0.0) < 0.01:
                return False
        self._tick += 1
        frame = frame_for_levels(levels, rms, beat, self._tick)
        try:
            with open(self.frame_path, "w", encoding="ascii") as handle:
                handle.write(frame)
            self._last_write = now
            self._last_levels = tuple(levels)
            return True
        except OSError:
            self.errors += 1
            if self.errors > 8:
                self.enabled = False
            return False

    def clear(self):
        if not self.frame_path:
            return False
        try:
            count = max(1, len(self._last_levels))
            with open(self.frame_path, "w", encoding="ascii") as handle:
                handle.write("000000" * count)
            self._last_levels = ()
            return True
        except OSError:
            return False