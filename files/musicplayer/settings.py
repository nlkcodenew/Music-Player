import json
import os
import tempfile


DEFAULTS = {
    "volume": 80,
    "shuffle": False,
    "repeat": "off",
    "last_track": "",
    "auto_update": True,
    "skipped_version": "",
    "lyrics_language": "",
    "eq_preset": "Flat",
    "eq_bass": 0,
    "eq_mid": 0,
    "eq_treble": 0,
    "audio_output": "auto",
    "auto_report_errors": False,
}


def atomic_json_write(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="write-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Settings:
    def __init__(self, path):
        self.path = path
        self.values = dict(DEFAULTS)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, ValueError, TypeError):
            return self
        if isinstance(loaded, dict):
            self.values.update({key: loaded[key] for key in DEFAULTS if key in loaded})
        self.values["volume"] = max(0, min(100, int(self.values.get("volume", 80))))
        if self.values.get("repeat") not in ("off", "all", "one"):
            self.values["repeat"] = "off"
        self.values["shuffle"] = bool(self.values.get("shuffle"))
        self.values["auto_update"] = bool(self.values.get("auto_update"))
        self.values["auto_report_errors"] = bool(self.values.get("auto_report_errors"))
        self.values["lyrics_language"] = str(self.values.get("lyrics_language", ""))
        if self.values.get("eq_preset") not in (
            "Flat", "Bass Boost", "Vocal", "Rock", "Pop", "Classical", "Jazz", "Custom",
        ):
            self.values["eq_preset"] = "Flat"
        for key in ("eq_bass", "eq_mid", "eq_treble"):
            self.values[key] = max(-6, min(6, int(self.values.get(key, 0))))
        if self.values.get("audio_output") not in ("auto", "system", "usb"):
            self.values["audio_output"] = "auto"
        return self

    def save(self):
        atomic_json_write(self.path, self.values)

    def get(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.values[key] = value
