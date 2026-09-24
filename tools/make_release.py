#!/usr/bin/env python3

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES_DIR = os.path.join(REPO_ROOT, "files")
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
MANIFEST_PATH = os.path.join(REPO_ROOT, "manifest.json")
PACKAGES = {
    "stock": "Apps/MusicPlayer",
    "spruce": "App/MusicPlayer",
}
TEXT_EXTENSIONS = {".json", ".md", ".pem", ".py", ".sh", ".txt"}
EXCLUDED = {
    "secrets.json", "settings.json", "collections.json", "pending-reports.json", "identity.json",
    "display-restore.json", "music-player.log", "music-player-stdio.log",
    "music-player-session.log", "music-player-session-stdio.log", "music-player-diagnostics.json",
    "background-session.json", "background-command", "background.pid",
    "background-status.json", "background-resume.json",
}


def app_version():
    path = os.path.join(FILES_DIR, "musicplayer", "__init__.py")
    with open(path, encoding="utf-8") as handle:
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', handle.read())
    if not match:
        raise SystemExit("APP_VERSION not found")
    return match.group(1)


def release_repo():
    with open(os.path.join(FILES_DIR, "release.json"), encoding="utf-8") as handle:
        repo = json.load(handle).get("github_repo", "")
    return os.environ.get("MUSIC_PLAYER_GITHUB_REPO", repo)


def release_bytes(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if os.path.splitext(path)[1].lower() in TEXT_EXTENSIONS:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def add_file(archive, source, target, executable=False):
    info = zipfile.ZipInfo(target, (2020, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    archive.writestr(info, release_bytes(source))


def payload_files():
    files = []
    for current, directories, filenames in os.walk(FILES_DIR):
        directories[:] = sorted(name for name in directories if name != "__pycache__")
        for filename in sorted(filenames):
            if filename.startswith(".") or filename.endswith(".pyc") or filename in EXCLUDED:
                continue
            source = os.path.join(current, filename)
            relative = os.path.relpath(source, FILES_DIR).replace(os.sep, "/")
            files.append((relative, source))
    files.extend((
        ("certs/cacert.pem", os.path.join(ASSETS_DIR, "cacert.pem")),
        ("config.json", os.path.join(ASSETS_DIR, "config.json")),
        ("icon.png", os.path.join(ASSETS_DIR, "icon.png")),
        ("LICENSE.txt", os.path.join(REPO_ROOT, "LICENSE")),
    ))
    return files


def manifest(version, repo, files):
    release_ref = "v%s" % version
    entries = []
    for relative, source in files:
        data = release_bytes(source)
        entry = {
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        if relative == "certs/cacert.pem":
            entry["url"] = "https://raw.githubusercontent.com/%s/%s/assets/cacert.pem" % (repo, release_ref)
        elif relative in ("config.json", "icon.png"):
            entry["url"] = "https://raw.githubusercontent.com/%s/%s/assets/%s" % (repo, release_ref, relative)
        elif relative == "LICENSE.txt":
            entry["url"] = "https://raw.githubusercontent.com/%s/%s/LICENSE" % (repo, release_ref)
        entries.append(entry)
    return {
        "version": version,
        "app": "trimui-music-player",
        "release_ref": release_ref,
        "base_url": "https://raw.githubusercontent.com/%s/%s/files" % (repo, release_ref),
        "files": entries,
    }


def write_package(version, platform, package_root, files):
    archive_name = "trimui-music-player-v%s-%s.zip" % (version, platform)
    archive_path = os.path.join(DIST_DIR, archive_name)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for relative, source in files:
            target = "%s/%s" % (package_root, relative)
            add_file(archive, source, target, relative.endswith(".sh"))
    digest = hashlib.sha256(release_bytes(archive_path)).hexdigest()
    with open(archive_path + ".sha256", "w", encoding="ascii", newline="\n") as handle:
        handle.write("%s  %s\n" % (digest, archive_name))
    print("created %s" % archive_path)


def main():
    version = app_version()
    repo = release_repo()
    files = payload_files()
    release_manifest = manifest(version, repo, files)
    with open(MANIFEST_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(release_manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    shutil.rmtree(DIST_DIR, ignore_errors=True)
    os.makedirs(DIST_DIR, exist_ok=True)
    shutil.copyfile(MANIFEST_PATH, os.path.join(DIST_DIR, "ota-manifest.json"))
    for platform, package_root in PACKAGES.items():
        write_package(version, platform, package_root, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
