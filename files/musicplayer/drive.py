"""Google Drive public-folder browsing for Buoc B.

Works out of the box with no API key: public folder pages are read through
Drive's keyless embedded folder view and single tracks download through the
keyless ``uc?export=download`` endpoint -- no OAuth, no Authorization
header, no tokens. If the user puts a public (restricted) API key in
``drive_api_key``, listing upgrades to ``files.list`` with a small
``pageSize`` and minimal ``fields`` so the device never scans the whole
(~5TB) share into RAM. Per-track playback downloads a single file to disk
in small chunks (RAM-safe) and plays the local cached copy with SDL_mixer.
Offline copies go to ``Music/Drive/<Album>/`` so they appear in the normal
local library.
"""

import html as html_module
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .library import SUPPORTED_EXTENSIONS
from .logger import get_logger
from .ssl_context import verified_context

DEFAULT_FOLDER_ID = "1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a"
PAGE_SIZE = 25
CACHE_FILENAME = "drive-cache.json"
STREAM_SUBDIR = "drive-cache"
OFFLINE_SUBDIR = "Drive"
MAX_TRACK_BYTES = 700 * 1024 * 1024
MAX_STREAM_CACHE_BYTES = 1024 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
FOLDER_MIME = "application/vnd.google-apps.folder"
EMBED_VIEW_URL = "https://drive.google.com/embeddedfolderview?id=%s#list"
MAX_EMBED_BYTES = 4 * 1024 * 1024
MAX_PUBLIC_ENTRIES = 500

_FOLDER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{10,}")


@dataclass(frozen=True)
class DriveEntry:
    """One Drive file or folder visible in the DRIVE screen."""

    file_id: str
    name: str
    mime_type: str
    size: int
    is_folder: bool
    title: str
    extension: str


class DriveError(RuntimeError):
    pass


def extract_folder_id(value):
    """Accept a raw folder ID or a full Drive share URL, return the ID."""
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text
    for pattern in (
        r"[?&]id=([A-Za-z0-9_-]{10,})",
        r"/folders/([A-Za-z0-9_-]{10,})",
        r"/drive/([A-Za-z0-9_-]{10,})",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    candidates = _FOLDER_ID_PATTERN.findall(text)
    if len(text) < 60 and candidates:
        return max(candidates, key=len)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text) else ""


def is_audio_name(name, mime_type=""):
    extension = os.path.splitext(str(name or ""))[1].lower()
    if extension in SUPPORTED_EXTENSIONS:
        return True
    return str(mime_type or "").lower().startswith("audio/")


def sanitize_component(value, fallback="Unknown"):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return fallback
    return cleaned[:80]


def build_list_url(folder_id, api_key, page_token="", page_size=PAGE_SIZE):
    if not folder_id:
        raise DriveError("Drive folder is not configured")
    if not api_key:
        raise DriveError("Drive API key is missing (settings drive_api_key)")
    query = "'%s' in parents and trashed=false" % folder_id
    params = {
        "q": query,
        "fields": "nextPageToken,files(id,name,mimeType,size)",
        "pageSize": str(max(1, min(int(page_size or PAGE_SIZE), 100))),
        "orderBy": "folder,name",
        "supportsAllDrives": "false",
        "key": api_key,
    }
    if page_token:
        params["pageToken"] = page_token
    return "https://www.googleapis.com/drive/v3/files?%s" % urllib.parse.urlencode(params)


def parse_list_response(payload):
    """Parse a files.list JSON payload into (entries, nextPageToken).

    Keeps folders and audio files only; skips everything else so a huge
    shared folder cannot fill the device library with docs/images.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = json.loads(bytes(payload).decode("utf-8"))
    if not isinstance(payload, dict):
        raise DriveError("invalid Drive response")
    if payload.get("error"):
        message = payload["error"].get("message", "Drive request failed")
        raise DriveError("Drive: %s" % message)
    entries = []
    files = payload.get("files", [])
    if not isinstance(files, list):
        raise DriveError("invalid Drive response")
    for item in files:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id", ""))
        name = str(item.get("name", ""))
        if not file_id or not name:
            continue
        mime_type = str(item.get("mimeType", ""))
        is_folder = mime_type == FOLDER_MIME
        if not is_folder and not is_audio_name(name, mime_type):
            continue
        try:
            size = int(item.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        extension = "" if is_folder else os.path.splitext(name)[1].lower()
        entries.append(DriveEntry(
            file_id=file_id,
            name=name,
            mime_type=mime_type,
            size=max(0, size),
            is_folder=is_folder,
            title=os.path.splitext(name)[0],
            extension=extension,
        ))
    token = payload.get("nextPageToken", "")
    return entries, str(token or "")


def media_url(file_id, api_key):
    """Authenticated media download URL (preferred when a key exists)."""
    if not file_id:
        raise DriveError("Drive file ID is missing")
    if not api_key:
        raise DriveError("Drive API key is missing (settings drive_api_key)")
    return "https://www.googleapis.com/drive/v3/files/%s?alt=media&key=%s" % (
        urllib.parse.quote(str(file_id), safe=""),
        urllib.parse.quote(str(api_key), safe=""),
    )


def public_download_url(file_id):
    """Keyless download endpoint used when no API key is configured."""
    if not file_id:
        raise DriveError("Drive file ID is missing")
    return "https://drive.google.com/uc?export=download&id=%s" % urllib.parse.quote(
        str(file_id), safe=""
    )


def _fetch_bytes(app_dir, url, limit=256 * 1024):
    if urllib.parse.urlparse(url).scheme != "https":
        raise DriveError("Drive only accepts HTTPS URLs")
    request = urllib.request.Request(
        url, headers={"User-Agent": "trimui-music-player/drive"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=25, context=verified_context(app_dir)
        ) as response:
            return response.read(limit + 1)
    except urllib.error.HTTPError as error:
        raise DriveError("Drive HTTP %s" % error.code)
    except urllib.error.URLError as error:
        raise DriveError("Drive network: %s" % error.reason)


def list_folder(app_dir, folder_id, api_key, page_token="", page_size=PAGE_SIZE):
    url = build_list_url(folder_id, api_key, page_token, page_size)
    raw = _fetch_bytes(app_dir, url)
    if len(raw) > 256 * 1024:
        raise DriveError("Drive response exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise DriveError("invalid Drive response")
    return parse_list_response(payload)


def parse_embed_page(markup):
    """Parse a keyless embeddedfolderview page into DriveEntry items.

    Keeps folders and audio files only; returns (entries, "") since the
    page already lists the whole folder -- callers fetch one page per
    folder the user actually opens, never the full share.
    """
    if isinstance(markup, (bytes, bytearray)):
        markup = bytes(markup).decode("utf-8", "replace")
    if not isinstance(markup, str) or "flip-entry" not in markup:
        raise DriveError("invalid Drive folder page")
    entries = []
    for block in markup.split('<div class="flip-entry" id="entry-')[1:]:
        file_id = block.split('"', 1)[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", file_id):
            continue
        head = block[:2500]
        href_match = re.search(r'href="([^"]+)"', head)
        title_match = re.search(r'class="flip-entry-title"[^>]*>([^<]*)<', head)
        if not href_match or not title_match:
            continue
        href = href_match.group(1)
        name = html_module.unescape(title_match.group(1)).strip()
        if not name:
            continue
        folder_match = re.search(r"/drive/folders/([A-Za-z0-9_-]{10,})", href)
        file_match = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", href)
        if folder_match:
            real_id = folder_match.group(1)
            is_folder = True
        elif file_match:
            real_id = file_match.group(1)
            is_folder = False
        else:
            continue
        if not is_folder and not is_audio_name(name):
            continue
        extension = "" if is_folder else os.path.splitext(name)[1].lower()
        entries.append(DriveEntry(
            file_id=real_id,
            name=name,
            mime_type=FOLDER_MIME if is_folder else "",
            size=0,
            is_folder=is_folder,
            title=os.path.splitext(name)[0],
            extension=extension,
        ))
        if len(entries) >= MAX_PUBLIC_ENTRIES:
            break
    return entries, ""


def list_folder_public(app_dir, folder_id):
    """List one public folder with no API key (keyless embed view)."""
    if not folder_id:
        raise DriveError("Drive folder is not configured")
    url = EMBED_VIEW_URL % urllib.parse.quote(str(folder_id), safe="")
    raw = _fetch_bytes(app_dir, url, MAX_EMBED_BYTES)
    if len(raw) > MAX_EMBED_BYTES:
        raise DriveError("Drive folder page exceeds size limit")
    return parse_embed_page(raw)


def cache_file(data_dir):
    return os.path.join(data_dir, CACHE_FILENAME)


def load_cache(data_dir):
    try:
        with open(cache_file(data_dir), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(data_dir, data):
    os.makedirs(data_dir, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="drive-cache-", suffix=".tmp", dir=data_dir
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, cache_file(data_dir))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cache_key(folder_id, page_token=""):
    return "%s|%s" % (folder_id, page_token or "")


def get_cached_folder(data_dir, folder_id, page_token=""):
    data = load_cache(data_dir)
    item = data.get(cache_key(folder_id, page_token))
    if not isinstance(item, dict) or not isinstance(item.get("files"), list):
        return None
    entries = []
    for raw in item["files"]:
        try:
            entries.append(DriveEntry(
                file_id=str(raw["file_id"]),
                name=str(raw["name"]),
                mime_type=str(raw.get("mime_type", "")),
                size=int(raw.get("size", 0) or 0),
                is_folder=bool(raw.get("is_folder")),
                title=str(raw.get("title", "")),
                extension=str(raw.get("extension", "")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return entries, str(item.get("nextPageToken", "") or "")


def put_cached_folder(data_dir, folder_id, entries, next_token="", page_token=""):
    data = load_cache(data_dir)
    data[cache_key(folder_id, page_token)] = {
        "files": [
            {
                "file_id": entry.file_id,
                "name": entry.name,
                "mime_type": entry.mime_type,
                "size": entry.size,
                "is_folder": entry.is_folder,
                "title": entry.title,
                "extension": entry.extension,
            }
            for entry in entries
        ],
        "nextPageToken": next_token,
    }
    # Keep the on-disk cache bounded: newest 60 folder pages only.
    while len(data) > 60:
        data.pop(next(iter(data)), None)
    save_cache(data_dir, data)


def clear_cache(data_dir):
    try:
        os.unlink(cache_file(data_dir))
    except OSError:
        pass
    stream_dir = os.path.join(data_dir, STREAM_SUBDIR)
    shutil.rmtree(stream_dir, ignore_errors=True)


def normalize_slots(slots, fallback_folder=""):
    """Clean a drive slot list; seed "Drive 1" when empty.

    Each slot is ``{"name": ..., "folder": ...}``. Duplicated folders are
    dropped, bad entries skipped. Never returns an empty list when a
    fallback folder is available.
    """
    cleaned = []
    for item in slots or []:
        if not isinstance(item, dict):
            continue
        folder = extract_folder_id(item.get("folder", ""))
        if not folder or any(slot["folder"] == folder for slot in cleaned):
            continue
        name = re.sub(r"\s+", " ", str(item.get("name", "") or "")).strip()[:24]
        cleaned.append({"name": name or "Drive", "folder": folder})
    fallback = extract_folder_id(fallback_folder or "")
    if not cleaned and fallback:
        cleaned.append({"name": "Drive 1", "folder": fallback})
    return cleaned


def next_slot_name(slots):
    """First free "Drive N" label for a newly added share."""
    taken = set()
    for slot in slots or []:
        match = re.fullmatch(r"Drive\s+(\d+)", str(slot.get("name", "")).strip(), re.IGNORECASE)
        if match:
            taken.add(int(match.group(1)))
    number = 1
    while number in taken:
        number += 1
    return "Drive %d" % number


def find_slot(slots, folder_id):
    for index, slot in enumerate(slots or []):
        if slot.get("folder") == folder_id:
            return index
    return -1


def forget_folder(data_dir, folder_id):
    """Drop cached listing pages for one folder (keeps stream files)."""
    if not folder_id:
        return 0
    data = load_cache(data_dir)
    doomed = [
        key for key in data
        if key == folder_id or key.startswith(folder_id + "|")
    ]
    for key in doomed:
        data.pop(key, None)
    if doomed:
        save_cache(data_dir, data)
    return len(doomed)


def stream_path(data_dir, file_id, extension):
    directory = os.path.join(data_dir, STREAM_SUBDIR)
    os.makedirs(directory, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(file_id))[:80] or "track"
    return os.path.join(directory, "%s%s" % (safe_id, extension or ".bin"))


def format_bytes(value):
    try:
        total = float(value)
    except (TypeError, ValueError):
        return "0MB"
    if total < 0:
        total = 0.0
    if total >= 1024 * 1024 * 1024:
        return "%.1fGB" % (total / (1024 * 1024 * 1024))
    return "%dMB" % int(total / (1024 * 1024))


def stream_cache_size(data_dir):
    """Total bytes of downloaded-for-playback tracks (offline saves excluded)."""
    try:
        names = os.listdir(os.path.join(data_dir, STREAM_SUBDIR))
    except OSError:
        return 0
    total = 0
    for name in names:
        try:
            total += os.path.getsize(os.path.join(data_dir, STREAM_SUBDIR, name))
        except OSError:
            pass
    return total


def enforce_stream_cache_limit(data_dir, protect=()):
    """Evict least-recently-played cached tracks until under the 1GB cap.

    Only touches the playback stream cache -- offline saves under
    ``Music/Drive/`` are the user's files and are never deleted.
    Returns the remaining cache size in bytes.
    """
    directory = os.path.join(data_dir, STREAM_SUBDIR)
    protected = {os.path.basename(name) for name in (protect or ()) if name}
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    items = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            items.append([os.path.getmtime(path), os.path.getsize(path), path])
        except OSError:
            pass
    total = sum(size for _, size, _ in items)
    items.sort(key=lambda item: item[0])
    for _, size, path in items:
        if total <= MAX_STREAM_CACHE_BYTES:
            break
        if os.path.basename(path) in protected:
            continue
        try:
            os.unlink(path)
        except OSError:
            pass
        else:
            total -= size
    return total


def _download_to_path(app_dir, url, destination, expected_size=0):
    if urllib.parse.urlparse(url).scheme != "https":
        raise DriveError("Drive only accepts HTTPS URLs")
    request = urllib.request.Request(
        url, headers={"User-Agent": "trimui-music-player/drive"},
    )
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="drive-dl-", suffix=".tmp", dir=os.path.dirname(destination)
    )
    try:
        try:
            response = urllib.request.urlopen(
                request, timeout=60, context=verified_context(app_dir)
            )
        except urllib.error.HTTPError as error:
            raise DriveError("Drive download HTTP %s" % error.code)
        except urllib.error.URLError as error:
            raise DriveError("Drive network: %s" % error.reason)
        with response:
            total = 0
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_TRACK_BYTES:
                        raise DriveError("Drive track exceeds size limit")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        if expected_size and total != expected_size:
            get_logger().warning(
                "drive download size mismatch expected=%d actual=%d", expected_size, total
            )
        os.replace(temporary, destination)
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def ensure_stream_file(app_dir, data_dir, entry, api_key=""):
    """Download one track to the disk stream cache (RAM-safe), return path."""
    if entry.is_folder:
        raise DriveError("cannot stream a folder")
    destination = stream_path(data_dir, entry.file_id, entry.extension)
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        if not entry.size or os.path.getsize(destination) == entry.size:
            try:
                os.utime(destination, None)
            except OSError:
                pass
            return destination
    if api_key:
        urls = [media_url(entry.file_id, api_key), public_download_url(entry.file_id)]
    else:
        urls = [public_download_url(entry.file_id)]
    errors = []
    for url in urls:
        try:
            _download_to_path(app_dir, url, destination, entry.size)
            enforce_stream_cache_limit(data_dir, protect=(destination,))
            return destination
        except DriveError as error:
            errors.append(str(error))
    raise DriveError("; ".join(errors) or "Drive download failed")


def offline_path(music_dir, album, filename):
    parts = [sanitize_component(part, "Drive") for part in str(album or "").split("/")]
    parts = [part for part in parts if part] or ["Drive"]
    album_dir = os.path.join(music_dir, OFFLINE_SUBDIR, *parts)
    return os.path.join(album_dir, sanitize_component(filename, "track"))


def download_offline(app_dir, music_dir, album, entry, api_key=""):
    """Save one Drive track under Music/Drive/<Album>/ for offline play."""
    if entry.is_folder:
        raise DriveError("cannot download a folder")
    destination = offline_path(music_dir, album, entry.name)
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        if not entry.size or os.path.getsize(destination) == entry.size:
            return destination
    if api_key:
        urls = [media_url(entry.file_id, api_key), public_download_url(entry.file_id)]
    else:
        urls = [public_download_url(entry.file_id)]
    errors = []
    for url in urls:
        try:
            return _download_to_path(app_dir, url, destination, entry.size)
        except DriveError as error:
            errors.append(str(error))
    raise DriveError("; ".join(errors) or "Drive download failed")
