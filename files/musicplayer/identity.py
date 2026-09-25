import json
import os
import platform
import re

from .settings import atomic_json_write


def installation_id(paths):
    identity_path = os.path.join(paths.data_dir, "identity.json")
    try:
        with open(identity_path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, TypeError):
        value = {}
    install_id = value.get("install_id", "") if isinstance(value, dict) else ""
    if re.fullmatch(r"MP-[A-F0-9]{8}", install_id):
        return install_id
    install_id = "MP-" + os.urandom(4).hex().upper()
    atomic_json_write(identity_path, {"install_id": install_id})
    return install_id


def device_model():
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as handle:
                value = handle.read(128).replace(b"\0", b"").decode(
                    "utf-8", "replace"
                ).strip()
            if value:
                return value
        except OSError:
            pass
    return platform.machine() or "unknown"


def safe_model(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40] or "unknown"
