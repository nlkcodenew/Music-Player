import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from . import APP_VERSION
from .logger import get_logger
from .reporter import queue_report
from .ssl_context import verified_context


MANIFEST_ASSET = "ota-manifest.json"
PROTECTED = {
    "secrets.json", "settings.json", "collections.json", "pending-reports.json", "identity.json",
    "display-restore.json", "music-player.log", "music-player-stdio.log",
    "music-player-diagnostics.json",
}


def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts[:4]) or (0,)


def _fetch(paths, url, limit=16 * 1024 * 1024):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("OTA only accepts HTTPS URLs")
    request = urllib.request.Request(url, headers={"User-Agent": "trimui-music-player/%s" % APP_VERSION})
    with urllib.request.urlopen(request, timeout=25, context=verified_context(paths.app_dir)) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("OTA response exceeds size limit")
    return data


def _release_repo(paths):
    try:
        with open(os.path.join(paths.app_dir, "release.json"), "r", encoding="utf-8") as handle:
            repo = json.load(handle).get("github_repo", "")
    except (OSError, ValueError, AttributeError):
        repo = ""
    repo = os.environ.get("MUSIC_PLAYER_GITHUB_REPO", repo).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("OTA repository is not configured")
    return repo


def _manifest_urls(paths):
    explicit = os.environ.get("MUSIC_PLAYER_MANIFEST_URL")
    if explicit:
        yield explicit
    repo = _release_repo(paths)
    latest_api = "https://api.github.com/repos/%s/releases/latest" % repo
    try:
        release = json.loads(_fetch(paths, latest_api).decode("utf-8"))
        for asset in release.get("assets", []):
            if asset.get("name") == MANIFEST_ASSET:
                yield asset.get("browser_download_url")
    except (OSError, ValueError, urllib.error.URLError) as error:
        get_logger().info("latest release lookup unavailable: %s", error)
    yield "https://raw.githubusercontent.com/%s/main/manifest.json" % repo


def fetch_manifest(paths):
    errors = []
    for url in _manifest_urls(paths):
        if not url:
            continue
        try:
            manifest = json.loads(_fetch(paths, url, 1024 * 1024).decode("utf-8"))
            validate_manifest(manifest)
            return manifest
        except (OSError, ValueError, TypeError, urllib.error.URLError) as error:
            errors.append("%s: %s" % (url, error))
    raise RuntimeError("all OTA manifest sources failed: %s" % "; ".join(errors))


def _safe_relative(path):
    normalized = str(path).replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("unsafe OTA path: %s" % path)
    if os.path.basename(normalized) in PROTECTED:
        raise ValueError("protected OTA path: %s" % path)
    return normalized


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("invalid OTA manifest")
    base_url = manifest.get("base_url", "")
    if urllib.parse.urlparse(base_url).scheme != "https":
        raise ValueError("invalid OTA base URL")
    seen = set()
    for item in manifest["files"]:
        path = _safe_relative(item.get("path", ""))
        if path in seen:
            raise ValueError("duplicate OTA path: %s" % path)
        seen.add(path)
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise ValueError("invalid OTA hash: %s" % path)
        if int(item.get("size", -1)) < 0:
            raise ValueError("invalid OTA size: %s" % path)
        item_url = item.get("url", "")
        if item_url and urllib.parse.urlparse(item_url).scheme != "https":
            raise ValueError("invalid OTA file URL: %s" % path)


def update_available(manifest):
    return version_tuple(manifest.get("version")) > version_tuple(APP_VERSION)


def _download_file(paths, manifest, item, staging):
    relative = _safe_relative(item["path"])
    url = item.get("url") or (
        manifest["base_url"].rstrip("/") + "/" + urllib.parse.quote(relative, safe="/")
    )
    data = _fetch(paths, url, max(int(item["size"]) + 1, 1024))
    if len(data) != int(item["size"]):
        raise ValueError("OTA size mismatch for %s" % relative)
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("OTA hash mismatch for %s" % relative)
    destination = os.path.join(staging, *relative.split("/"))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return relative


def apply_update(paths, manifest):
    validate_manifest(manifest)
    staging = tempfile.mkdtemp(prefix="music-update-", dir=paths.data_dir)
    try:
        relative_paths = [_download_file(paths, manifest, item, staging) for item in manifest["files"]]
        relative_paths.sort(key=lambda path: (path.endswith("__init__.py"), path))
        for relative in relative_paths:
            source = os.path.join(staging, *relative.split("/"))
            destination = os.path.abspath(os.path.join(paths.app_dir, *relative.split("/")))
            if os.path.commonpath((paths.app_dir, destination)) != os.path.abspath(paths.app_dir):
                raise ValueError("OTA destination escaped app directory")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            temporary = destination + ".new"
            shutil.copyfile(source, temporary)
            if relative.endswith(".sh"):
                os.chmod(temporary, 0o755)
            with open(temporary, "r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            _fsync_directory(os.path.dirname(destination))
        with open(os.path.join(paths.app_dir, ".restart"), "w", encoding="ascii") as handle:
            handle.write(str(manifest["version"]))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(paths.app_dir)
    except Exception as error:
        queue_report(paths, "ota_apply_failed", str(error))
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _fsync_directory(path):
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass
