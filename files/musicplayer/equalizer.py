import ctypes
import math

try:
    import audioop
except ImportError:
    audioop = None


PRESETS = (
    ("Flat", (0, 0, 0)),
    ("Bass Boost", (5, 0, 0)),
    ("Vocal", (-2, 4, 1)),
    ("Rock", (4, 1, 3)),
    ("Pop", (2, 3, 2)),
    ("Classical", (1, -1, 3)),
    ("Jazz", (3, 1, 3)),
    ("Custom", None),
)
PRESET_NAMES = tuple(item[0] for item in PRESETS)
POSTMIX_CALLBACK = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int
)


def clamp_gain(value):
    return max(-6, min(6, int(value)))


def preset_gains(name, custom=(0, 0, 0)):
    for preset_name, gains in PRESETS:
        if preset_name == name:
            return tuple(clamp_gain(value) for value in (custom if gains is None else gains))
    return (0, 0, 0)


class Equalizer:
    def __init__(self, runtime, settings):
        self.runtime = runtime
        self.settings = settings
        self.callback = None
        self.installed = False
        self.low_state = None
        self.mid_state = None
        self.errors = 0

    @property
    def available(self):
        return audioop is not None and bool(self.runtime.Mix_SetPostMix)

    @property
    def preset(self):
        value = self.settings.get("eq_preset")
        return value if value in PRESET_NAMES else "Flat"

    @property
    def gains(self):
        custom = (
            self.settings.get("eq_bass"),
            self.settings.get("eq_mid"),
            self.settings.get("eq_treble"),
        )
        return preset_gains(self.preset, custom)

    def set_preset(self, name):
        if name not in PRESET_NAMES:
            name = "Flat"
        self.settings.set("eq_preset", name)
        gains = preset_gains(name, self.gains)
        if name != "Custom":
            self.settings.set("eq_bass", gains[0])
            self.settings.set("eq_mid", gains[1])
            self.settings.set("eq_treble", gains[2])
        self.sync()
        return name

    def cycle_preset(self, step=1):
        index = PRESET_NAMES.index(self.preset)
        return self.set_preset(PRESET_NAMES[(index + step) % len(PRESET_NAMES)])

    def adjust(self, band, step):
        keys = {"bass": "eq_bass", "mid": "eq_mid", "treble": "eq_treble"}
        current = dict(zip(("bass", "mid", "treble"), self.gains))
        current[band] = clamp_gain(current[band] + step)
        for name, key in keys.items():
            self.settings.set(key, current[name])
        self.settings.set("eq_preset", "Custom")
        self.sync()
        return current[band]

    def reset(self):
        self.low_state = None
        self.mid_state = None

    def sync(self):
        self.reset()
        if self.gains == (0, 0, 0):
            self.uninstall()
            return True
        if self.installed:
            return True
        return self.install()

    def install(self):
        if self.installed:
            return True
        if not self.available:
            return False

        @POSTMIX_CALLBACK
        def process(unused, stream, length):
            try:
                source = ctypes.string_at(stream, length)
                output = self.process(source)
                if output is not source:
                    ctypes.memmove(stream, output, min(length, len(output)))
            except Exception:
                self.errors += 1

        self.callback = process
        self.runtime.Mix_SetPostMix(ctypes.cast(process, ctypes.c_void_p), None)
        self.installed = True
        return True

    def uninstall(self):
        if self.installed and self.runtime.Mix_SetPostMix:
            self.runtime.Mix_SetPostMix(None, None)
        self.callback = None
        self.installed = False
        self.reset()

    def process(self, source):
        bass_db, mid_db, treble_db = self.gains
        if not source or (bass_db, mid_db, treble_db) == (0, 0, 0):
            return source
        low, self.low_state = audioop.ratecv(
            source, 2, 2, 48000, 48000, self.low_state, 32, 968
        )
        low_mid, self.mid_state = audioop.ratecv(
            source, 2, 2, 48000, 48000, self.mid_state, 408, 592
        )
        mid = audioop.add(low_mid, audioop.mul(low, 2, -1.0), 2)
        treble = audioop.add(source, audioop.mul(low_mid, 2, -1.0), 2)
        headroom = -max(0, bass_db, mid_db, treble_db) - 3
        bass_gain = math.pow(10.0, (bass_db + headroom) / 20.0)
        mid_gain = math.pow(10.0, (mid_db + headroom) / 20.0)
        treble_gain = math.pow(10.0, (treble_db + headroom) / 20.0)
        result = audioop.add(
            audioop.mul(low, 2, bass_gain), audioop.mul(mid, 2, mid_gain), 2
        )
        return audioop.add(result, audioop.mul(treble, 2, treble_gain), 2)
