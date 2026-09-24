import argparse
import ctypes
import json
import os
import time

from .logger import get_logger

try:
    import fcntl
except ImportError:
    fcntl = None


DISP_LCD_SET_BRIGHTNESS = 0x102


class DisplayController:
    def __init__(self, paths=None, device_path="/dev/disp", recovery_file=None):
        self.paths = paths
        self.device_path = device_path
        self.recovery_file = recovery_file or (
            os.path.join(paths.data_dir, "display-restore.json") if paths else ""
        )
        self.original_brightness = None
        self.is_off = False

    @property
    def supported(self):
        return fcntl is not None and os.path.exists(self.device_path)

    def _ioctl(self, command, value=0):
        descriptor = os.open(self.device_path, os.O_RDWR)
        parameters = (ctypes.c_ulong * 4)(0, int(value), 0, 0)
        try:
            result = fcntl.ioctl(descriptor, command, parameters)
            return True
        finally:
            os.close(descriptor)

    def _saved_brightness(self):
        candidates = [
            "/mnt/SDCARD/Saves/trim-ui-brick-pro-system.json",
            "/mnt/UDISK/system.json",
            "/appconfigs/system.json",
        ]
        for path in candidates:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    values = json.load(handle)
                    value = int(values.get("backlight", values.get("brightness")))
                if 1 <= value <= 10:
                    return round((value - 1) * 254 / 9 + 1)
                if 1 <= value <= 255:
                    return value
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return 128

    def _write_recovery(self, brightness):
        if not self.recovery_file:
            return
        os.makedirs(os.path.dirname(self.recovery_file), exist_ok=True)
        temporary = self.recovery_file + ".tmp"
        with open(temporary, "w", encoding="ascii", newline="\n") as handle:
            json.dump({"brightness": int(brightness)}, handle)
            handle.write("\n")
        os.replace(temporary, self.recovery_file)

    def _clear_recovery(self):
        if self.recovery_file:
            try:
                os.unlink(self.recovery_file)
            except FileNotFoundError:
                pass

    def prepare(self):
        if not self.supported:
            return False
        try:
            self.original_brightness = self._saved_brightness()
            self._write_recovery(self.original_brightness)
            get_logger().info(
                "display recovery prepared brightness=%d", self.original_brightness
            )
            return True
        except (OSError, ValueError) as error:
            get_logger().warning("cannot prepare display recovery: %s", error)
            self.original_brightness = None
            self._clear_recovery()
            return False

    def screen_off(self):
        if self.is_off:
            return True
        if not self.supported:
            return False
        started = time.monotonic()
        try:
            brightness = self.original_brightness
            if brightness is None:
                brightness = self._saved_brightness()
                self._write_recovery(brightness)
            self._ioctl(DISP_LCD_SET_BRIGHTNESS, 0)
            self.original_brightness = brightness
            self.is_off = True
            get_logger().info(
                "screen-off playback enabled restore_brightness=%d elapsed_ms=%.1f",
                brightness, (time.monotonic() - started) * 1000.0,
            )
            return True
        except (OSError, ValueError) as error:
            get_logger().warning("cannot turn screen off: %s", error)
            self._clear_recovery()
            return False

    def restore(self):
        brightness = self.original_brightness
        if brightness is None and self.recovery_file:
            try:
                with open(self.recovery_file, "r", encoding="ascii") as handle:
                    brightness = int(json.load(handle)["brightness"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                brightness = None
        if brightness is None:
            return True
        started = time.monotonic()
        try:
            if not self.supported:
                return False
            self._ioctl(DISP_LCD_SET_BRIGHTNESS, max(1, min(255, brightness)))
            get_logger().info(
                "display brightness restored=%d elapsed_ms=%.1f",
                brightness, (time.monotonic() - started) * 1000.0,
            )
            self.original_brightness = None
            self.is_off = False
            self._clear_recovery()
            return True
        except OSError as error:
            get_logger().error("cannot restore display brightness: %s", error)
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", metavar="FILE", required=True)
    args = parser.parse_args()
    controller = DisplayController(recovery_file=args.restore)
    return 0 if controller.restore() else 1


if __name__ == "__main__":
    raise SystemExit(main())
