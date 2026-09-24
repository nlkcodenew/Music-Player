import hashlib
import json
import os
import platform
import re
import socket
import sys
import urllib.error
import urllib.request

from . import APP_VERSION
from .logger import get_logger, init_logging
from .paths import RuntimePaths
from .settings import atomic_json_write
from .ssl_context import verified_context


MAX_LOG_TAIL = 48 * 1024
MAX_PENDING = 8
TOKEN_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)[^\s]+"),
    re.compile(r"\b(?:ghp|github_pat|gho|ghu|ghs|ghr)_[A-Za-z0-9_]+\b"),
)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError, TypeError):
        return default


def _installation_id(paths):
    identity_path = os.path.join(paths.data_dir, "identity.json")
    value = _read_json(identity_path, {})
    install_id = value.get("install_id", "") if isinstance(value, dict) else ""
    if re.fullmatch(r"MP-[A-F0-9]{8}", install_id):
        return install_id
    install_id = "MP-" + os.urandom(4).hex().upper()
    atomic_json_write(identity_path, {"install_id": install_id})
    return install_id


def _model():
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as handle:
                value = handle.read(128).replace(b"\0", b"").decode("utf-8", "replace").strip()
            if value:
                return value
        except OSError:
            pass
    return platform.machine() or "unknown"


def _safe_model(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40] or "unknown"


def _redact(text, paths, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    music_dir = getattr(paths, "music_dir", "")
    if music_dir:
        text = text.replace(music_dir, "$MUSIC")
    text = text.replace(paths.app_dir, "$APP").replace(paths.sdcard_path, "$SDCARD")
    text = re.sub(r"\$MUSIC[^\r\n]*", "$MUSIC/[PATH REDACTED]", text)
    text = re.sub(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "[MAC]", text)
    return text


def _log_tail(paths):
    chunks = []
    for path in (paths.log_file, getattr(paths, "stdio_log_file", "")):
        if not path:
            continue
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - MAX_LOG_TAIL // 2))
                chunks.append(handle.read().decode("utf-8", "replace"))
        except OSError:
            pass
    return "\n".join(chunks)[-MAX_LOG_TAIL:]


def queue_report(paths, reason, detail=""):
    pending = _read_json(paths.pending_reports_file, [])
    if not isinstance(pending, list):
        pending = []
    fingerprint = hashlib.sha256(reason.encode("utf-8", "replace")).hexdigest()[:12]
    existing = next(
        (item for item in pending if isinstance(item, dict) and item.get("reason") == reason),
        None,
    )
    if existing:
        return existing.get("fingerprint", fingerprint)
    pending.append({"reason": reason[:80], "detail": detail[:2000], "fingerprint": fingerprint})
    atomic_json_write(paths.pending_reports_file, pending[-MAX_PENDING:])
    return fingerprint


def _credentials(paths):
    values = _read_json(os.path.join(paths.app_dir, "secrets.json"), {})
    if not isinstance(values, dict):
        values = {}
    token = os.environ.get("MUSIC_PLAYER_GITHUB_TOKEN") or values.get("github_token", "")
    repo = os.environ.get("MUSIC_PLAYER_GITHUB_REPO") or values.get("github_repo", "")
    return token.strip(), repo.strip()


def _request_json(paths, url, token, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "trimui-music-player/%s" % APP_VERSION)
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Authorization", "Bearer %s" % token)
    with urllib.request.urlopen(request, timeout=20, context=verified_context(paths.app_dir)) as response:
        return json.loads(response.read().decode("utf-8"))


def _submit(paths, item, token, repo):
    model = _safe_model(_model())
    install_id = _installation_id(paths)
    fingerprint = item["fingerprint"]
    title = "[device-log][%s][%s] v%s %s %s" % (
        model, install_id, APP_VERSION, item["reason"], fingerprint,
    )
    issues_url = "https://api.github.com/repos/%s/issues" % repo
    existing = _request_json(paths, issues_url + "?state=all&per_page=100", token)
    if any(fingerprint in issue.get("title", "") for issue in existing if isinstance(issue, dict)):
        return
    secret_values = (token,)
    body = "\n".join((
        "Automatic diagnostic report.",
        "",
        "- App: `%s`" % APP_VERSION,
        "- OS: `%s`" % paths.os_name,
        "- Model: `%s`" % model,
        "- Install: `%s`" % install_id,
        "- Python: `%s`" % sys.version.split()[0],
        "- Reason: `%s`" % item["reason"],
        "- Detail: `%s`" % _redact(item.get("detail", ""), paths, secret_values),
        "",
        "```text",
        _redact(_log_tail(paths), paths, secret_values),
        "```",
    ))
    _request_json(paths, issues_url, token, method="POST", body={"title": title, "body": body})


def retry_pending(paths):
    pending = _read_json(paths.pending_reports_file, [])
    if not isinstance(pending, list) or not pending:
        return False
    token, repo = _credentials(paths)
    if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return False
    remaining = []
    for item in pending:
        try:
            _submit(paths, item, token, repo)
        except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as error:
            get_logger().warning("report upload failed for %s: %s", item.get("reason"), error)
            remaining.append(item)
    atomic_json_write(paths.pending_reports_file, remaining)
    return not remaining


def main():
    reason = "manual"
    if "--reason" in sys.argv:
        index = sys.argv.index("--reason")
        if index + 1 < len(sys.argv):
            reason = sys.argv[index + 1]
    paths = RuntimePaths.discover()
    paths.ensure_writable_dirs()
    init_logging(paths.log_file)
    queue_report(paths, reason)
    retry_pending(paths)


if __name__ == "__main__":
    main()

