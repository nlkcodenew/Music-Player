#!/usr/bin/env python3

import glob
import json
import os
import stat
import sys
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    archives = glob.glob(os.path.join(ROOT, "dist", "*.zip"))
    if len(archives) != 1:
        raise SystemExit("expected exactly one release ZIP")
    asset_manifest_path = os.path.join(ROOT, "dist", "portable-manifest.json")
    if not os.path.isfile(asset_manifest_path):
        raise SystemExit("portable-manifest.json release asset is missing")
    with zipfile.ZipFile(archives[0]) as archive:
        names = set(archive.namelist())
        required = {
            ".music-player/app.py",
            ".music-player/launch.sh",
            ".music-player/certs/cacert.pem",
            ".music-player/musicplayer/ui.py",
            "App/Music Player/config.json",
            "App/Music Player/launch.sh",
            "Apps/Music Player/config.json",
            "Apps/Music Player/launch.sh",
        }
        missing = required - names
        if missing:
            raise SystemExit("missing: %s" % ", ".join(sorted(missing)))
        for launcher in (".music-player/launch.sh", "App/Music Player/launch.sh", "Apps/Music Player/launch.sh"):
            mode = archive.getinfo(launcher).external_attr >> 16
            if not mode & stat.S_IXUSR:
                raise SystemExit("not executable: %s" % launcher)
        forbidden = [name for name in names if "__pycache__" in name or name.endswith(".pyc") or os.path.basename(name) in EXCLUDED]
        if forbidden:
            raise SystemExit("private/runtime files present: %s" % forbidden)
        manifest = json.loads(archive.read(".music-player/portable-manifest.json").decode("utf-8"))
        with open(asset_manifest_path, encoding="utf-8") as handle:
            if json.load(handle) != manifest:
                raise SystemExit("release manifest asset differs from ZIP manifest")
        manifest_paths = {item["path"] for item in manifest["files"]}
        if "secrets.json" in manifest_paths or "data/settings.json" in manifest_paths:
            raise SystemExit("user data appears in OTA manifest")
    print("verified %s (%d entries)" % (archives[0], len(names)))
    return 0


EXCLUDED = {
    "secrets.json", "settings.json", "pending-reports.json", "identity.json",
    "music-player.log", "music-player-stdio.log", "music-player-diagnostics.json",
}


if __name__ == "__main__":
    sys.exit(main())

