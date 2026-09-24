import time


PRESETS = (
    ("Off", None),
    ("15 min", 15 * 60),
    ("30 min", 30 * 60),
    ("45 min", 45 * 60),
    ("60 min", 60 * 60),
    ("90 min", 90 * 60),
    ("End of track", "track"),
)


class SleepTimer:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.preset_index = 0
        self.deadline = None
        self.track_path = ""

    @property
    def label(self):
        return PRESETS[self.preset_index][0]

    @property
    def active(self):
        return self.preset_index != 0

    def set(self, preset_index, track_path=""):
        self.preset_index = preset_index % len(PRESETS)
        value = PRESETS[self.preset_index][1]
        self.deadline = self.clock() + value if isinstance(value, int) else None
        self.track_path = track_path if value == "track" else ""
        return self.label

    def cycle(self, step=1, track_path=""):
        return self.set(self.preset_index + step, track_path)

    def cancel(self):
        self.set(0)

    def remaining(self):
        if self.deadline is None:
            return None
        return max(0, int(self.deadline - self.clock() + 0.999))

    def expired(self, track_path="", playing=True, paused=False):
        value = PRESETS[self.preset_index][1]
        if isinstance(value, int):
            return self.clock() >= self.deadline
        if value == "track" and self.track_path:
            return track_path != self.track_path or (not playing and not paused)
        return False

    def status(self):
        remaining = self.remaining()
        if remaining is None:
            return self.label
        minutes, seconds = divmod(remaining, 60)
        return "%d:%02d" % (minutes, seconds)
