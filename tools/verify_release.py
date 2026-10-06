#!/usr/bin/env python3

import glob
import hashlib
import json
import os
import stat
import sys
import urllib.parse
import zipfile

from vendor_python_runtime import _elf_needed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_ROOTS = ("Apps/MusicPlayer", "App/MusicPlayer")
EXCLUDED = {
    "secrets.json", "settings.json", "collections.json", "pending-reports.json", "identity.json",
    "display-restore.json", "music-player.log", "music-player-stdio.log",
    "music-player-session.log", "music-player-session-stdio.log", "music-player-diagnostics.json",
    "background-session.json", "background-command", "background.pid",
    "background-status.json", "background-resume.json", "crash-handled",
    "drive-cache.json",
}
TOKEN_MARKERS = (b"github_pat_", b"ghp_", b"MUSIC_PLAYER_GITHUB_TOKEN")


def verify_archive(path, manifest):
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = set()
        for package_root in PACKAGE_ROOTS:
            required.update({
                "%s/app.py" % package_root,
                "%s/launch.sh" % package_root,
                "%s/config.json" % package_root,
                "%s/icon.png" % package_root,
                "%s/LICENSE.txt" % package_root,
                "%s/certs/cacert.pem" % package_root,
                "%s/musicplayer/ui.py" % package_root,
                "%s/libs/libSDL2_mixer-2.0.so" % package_root,
                "%s/python/bin/python3" % package_root,
                "%s/python/bin/python3.10" % package_root,
                "%s/python/lib/ld-linux-aarch64.so.1" % package_root,
                "%s/python/lib/libpython3.10.so.1.0" % package_root,
                "%s/python/lib/python310.zip" % package_root,
                "%s/THIRD_PARTY_NOTICES.txt" % package_root,
            })
        missing = required - names
        if missing:
            raise SystemExit("%s missing: %s" % (os.path.basename(path), ", ".join(sorted(missing))))
        outside = [
            name for name in names
            if not any(name.startswith(package_root + "/") for package_root in PACKAGE_ROOTS)
        ]
        if outside:
            raise SystemExit("files outside app directory in %s: %s" % (os.path.basename(path), outside))
        forbidden = [
            name for name in names
            if "__pycache__" in name or name.endswith(".pyc") or os.path.basename(name) in EXCLUDED
        ]
        if forbidden:
            raise SystemExit("private/runtime files present: %s" % forbidden)
        for package_root in PACKAGE_ROOTS:
            launcher = "%s/launch.sh" % package_root
            if not archive.getinfo(launcher).external_attr >> 16 & stat.S_IXUSR:
                raise SystemExit("not executable: %s" % launcher)
            launcher_data = archive.read(launcher)
            for marker in (
                b"AUDIODEV=bluealsa", b"/usr/lib/libasound.so.2",
                b"MUSIC_PLAYER_AUDIO_PROBE=1",
            ):
                if marker not in launcher_data:
                    raise SystemExit("Bluetooth audio fallback missing from %s" % launcher)
            for relative in (
                "python/bin/python3", "python/bin/python3.10",
                "python/lib/ld-linux-aarch64.so.1",
            ):
                name = "%s/%s" % (package_root, relative)
                if not archive.getinfo(name).external_attr >> 16 & stat.S_IXUSR:
                    raise SystemExit("not executable: %s" % name)
            for relative in ("libs/libSDL2_mixer-2.0.so", "python/bin/python3.10"):
                binary = archive.read("%s/%s" % (package_root, relative))
                if not binary.startswith(b"\x7fELF") or binary[4] != 2 or binary[5] != 1:
                    raise SystemExit("not a 64-bit little-endian ELF: %s" % relative)
                if int.from_bytes(binary[18:20], "little") != 183:
                    raise SystemExit("not built for AArch64: %s" % relative)
            mixer = archive.read("%s/libs/libSDL2_mixer-2.0.so" % package_root)
            if b"DRFLAC" not in mixer or b"Mix_SetPostMix" not in mixer:
                raise SystemExit("bundled SDL2_mixer lacks FLAC or post-mix support")
            native_prefixes = (
                "%s/libs/" % package_root,
                "%s/python/bin/python3.10" % package_root,
                "%s/python/lib/" % package_root,
            )
            native_names = {
                os.path.basename(name) for name in names
                if name.startswith(native_prefixes[0]) or name == native_prefixes[1]
                or name.startswith(native_prefixes[2]) and not name.endswith(".zip")
            }
            for name in names:
                if not (
                    name.startswith(native_prefixes[0]) or name == native_prefixes[1]
                    or name.startswith(native_prefixes[2]) and not name.endswith(".zip")
                ):
                    continue
                data = archive.read(name)
                if not data.startswith(b"\x7fELF"):
                    continue
                temporary = os.path.join(ROOT, "dist", ".verify-elf")
                with open(temporary, "wb") as handle:
                    handle.write(data)
                try:
                    missing = [item for item in _elf_needed(temporary) if item not in native_names]
                finally:
                    os.unlink(temporary)
                if missing:
                    raise SystemExit("missing ELF dependencies for %s: %s" % (name, missing))
            for item in manifest["files"]:
                name = "%s/%s" % (package_root, item["path"])
                if name not in names:
                    raise SystemExit("manifest file missing from %s: %s" % (os.path.basename(path), name))
                data = archive.read(name)
                if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise SystemExit("manifest mismatch in %s: %s" % (os.path.basename(path), name))
        if len(names) != len(manifest["files"]) * len(PACKAGE_ROOTS):
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
    if "reporting.json" not in manifest_paths:
        raise SystemExit("reporting.json is missing from OTA manifest")
    reporting_path = os.path.join(ROOT, "files", "reporting.json")
    with open(reporting_path, encoding="utf-8") as handle:
        relay_url = json.load(handle).get("issue_relay_url", "")
    parsed = urllib.parse.urlsplit(relay_url)
    if (
        parsed.scheme != "https" or not parsed.netloc or parsed.username
        or parsed.password or parsed.query or parsed.fragment
    ):
        raise SystemExit("reporting.json must contain a credential-free HTTPS relay URL")
    for item in manifest["files"]:
        source = os.path.join(ROOT, "files", *item["path"].split("/"))
        if os.path.isfile(source):
            with open(source, "rb") as handle:
                data = handle.read()
            if any(marker in data for marker in TOKEN_MARKERS):
                raise SystemExit("GitHub credential marker in release: %s" % item["path"])

    archives = glob.glob(os.path.join(ROOT, "dist", "*.zip"))
    expected_names = {"trimui-music-player-v%s-universal.zip" % manifest["version"]}
    if {os.path.basename(path) for path in archives} != expected_names:
        raise SystemExit("expected one universal Stock + Spruce release ZIP")
    filename = next(iter(expected_names))
    verify_archive(os.path.join(ROOT, "dist", filename), manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
