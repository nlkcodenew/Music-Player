#!/usr/bin/env python3

import glob
import hashlib
import json
import os
import stat
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = {
    "stock": "Apps/Music Player",
    "spruce": "App/Music Player",
}
EXCLUDED = {
    "secrets.json", "settings.json", "pending-reports.json", "identity.json",
    "music-player.log", "music-player-stdio.log", "music-player-diagnostics.json",
}


def verify_archive(path, package_root, manifest):
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {
            "%s/app.py" % package_root,
            "%s/launch.sh" % package_root,
            "%s/config.json" % package_root,
            "%s/icon.png" % package_root,
            "%s/LICENSE.txt" % package_root,
            "%s/certs/cacert.pem" % package_root,
            "%s/musicplayer/ui.py" % package_root,
        }
        missing = required - names
        if missing:
            raise SystemExit("%s missing: %s" % (os.path.basename(path), ", ".join(sorted(missing))))
        outside = [name for name in names if not name.startswith(package_root + "/")]
        if outside:
            raise SystemExit("files outside app directory in %s: %s" % (os.path.basename(path), outside))
        forbidden = [
            name for name in names
            if "__pycache__" in name or name.endswith(".pyc") or os.path.basename(name) in EXCLUDED
        ]
        if forbidden:
            raise SystemExit("private/runtime files present: %s" % forbidden)
        launcher = "%s/launch.sh" % package_root
        if not archive.getinfo(launcher).external_attr >> 16 & stat.S_IXUSR:
            raise SystemExit("not executable: %s" % launcher)
        for item in manifest["files"]:
            name = "%s/%s" % (package_root, item["path"])
            if name not in names:
                raise SystemExit("manifest file missing from %s: %s" % (os.path.basename(path), name))
            data = archive.read(name)
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise SystemExit("manifest mismatch in %s: %s" % (os.path.basename(path), name))
        if len(names) != len(manifest["files"]):
            raise SystemExit("untracked package files in %s" % os.path.basename(path))
    print("verified %s (%d entries)" % (path, len(names)))


def main():
    manifest_path = os.path.join(ROOT, "dist", "ota-manifest.json")
    if not os.path.isfile(manifest_path):
        raise SystemExit("ota-manifest.json release asset is missing")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest_paths = {item["path"] for item in manifest["files"]}
    if any(os.path.basename(path) in EXCLUDED for path in manifest_paths):
        raise SystemExit("user data appears in OTA manifest")

    archives = glob.glob(os.path.join(ROOT, "dist", "*.zip"))
    expected_names = {
        "trimui-music-player-v%s-%s.zip" % (manifest["version"], platform)
        for platform in PACKAGES
    }
    if {os.path.basename(path) for path in archives} != expected_names:
        raise SystemExit("expected Stock OS and Spruce OS release ZIPs")
    for platform, package_root in PACKAGES.items():
        filename = "trimui-music-player-v%s-%s.zip" % (manifest["version"], platform)
        verify_archive(os.path.join(ROOT, "dist", filename), package_root, manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
