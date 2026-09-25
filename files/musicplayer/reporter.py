import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import APP_VERSION
from .identity import device_model, installation_id, safe_model
from .logger import get_logger, init_logging
from .paths import RuntimePaths
from .settings import Settings, atomic_json_write
from .ssl_context import verified_context


MAX_ISSUE_CHUNK = 42 * 1024
MAX_LOG_CHUNKS = 8
MAX_PENDING = 32
TOKEN_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)[^\s]+"),
    re.compile(r"\b(?:ghp|github_pat|gho|ghu|ghs|ghr)_[A-Za-z0-9_]+\b"),
)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _redact(text, paths, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            text,
        )
    music_dir = getattr(paths, "music_dir", "")
    if music_dir:
        text = text.replace(music_dir, "$MUSIC")
    text = text.replace(paths.app_dir, "$APP").replace(paths.sdcard_path, "$SDCARD")
    text = re.sub(r"\$MUSIC[^\r\n]*", "$MUSIC/[PATH REDACTED]", text)
    text = re.sub(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "[MAC]", text)
    return text.replace("\x00", "")


def _read_log(path, max_bytes):
    if not isinstance(path, (str, bytes, os.PathLike)) or not path:
        return ""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read(max_bytes).decode("utf-8", "replace")
    except OSError:
        return ""


def _session_log(paths):
    limit = MAX_ISSUE_CHUNK * MAX_LOG_CHUNKS
    for path in (
        getattr(paths, "session_stdio_log_file", ""),
        getattr(paths, "session_log_file", ""),
    ):
        value = _read_log(path, limit)
        if value:
            return value
    chunks = [
        _read_log(path, limit // 2)
        for path in (paths.log_file, getattr(paths, "stdio_log_file", ""))
    ]
    return "\n".join(value for value in chunks if value)[-limit:]


def queue_report(paths, reason, detail="", unique=False):
    pending = _read_json(paths.pending_reports_file, [])
    if not isinstance(pending, list):
        pending = []
    identity = "%s:%s" % (APP_VERSION, reason)
    if unique:
        identity += ":%s:%s" % (time.time_ns(), os.urandom(4).hex())
    existing = next(
        (
            item for item in pending
            if not unique and isinstance(item, dict) and item.get("identity") == identity
        ),
        None,
    )
    if existing:
        return existing.get("fingerprint", "")
    session_log = _session_log(paths)
    fingerprint_source = "%s\n%s\n%s" % (identity, detail, session_log[-8000:])
    fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8", "replace")
    ).hexdigest()
    pending.append({
        "reason": reason[:80],
        "detail": detail[:2000],
        "fingerprint": fingerprint,
        "identity": identity,
        "session_log": session_log,
    })
    atomic_json_write(paths.pending_reports_file, pending[-MAX_PENDING:])
    return fingerprint


def _report_configuration(paths):
    values = _read_json(os.path.join(paths.app_dir, "reporting.json"), {})
    if not isinstance(values, dict):
        values = {}
    relay_url = os.environ.get("MUSIC_PLAYER_ISSUE_RELAY_URL") or values.get(
        "issue_relay_url", ""
    )
    return str(relay_url).strip()


def _reporting_enabled(paths):
    return bool(Settings(paths.settings_file).load().get("auto_report_errors"))


def _post_json(paths, relay_url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        relay_url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "trimui-music-player/%s" % APP_VERSION,
        },
    )
    with urllib.request.urlopen(
        request, timeout=25, context=verified_context(paths.app_dir)
    ) as response:
        result = json.loads(response.read(128 * 1024).decode("utf-8"))
    if result.get("accepted") is not True:
        raise ValueError("issue relay did not accept report")


def _post_relay(paths, relay_url, title, body, comments, fingerprint):
    parsed = urllib.parse.urlsplit(relay_url)
    if (
        parsed.scheme != "https" or not parsed.netloc or parsed.username
        or parsed.password or parsed.query or parsed.fragment
    ):
        raise ValueError("issue relay URL must be HTTPS without credentials or query")
    _post_json(paths, relay_url, {
        "schema": 1,
        "app": "trimui-music-player",
        "version": APP_VERSION,
        "fingerprint": fingerprint,
        "title": title,
        "body": body,
        "comments": comments,
    })


def _submit(paths, item, relay_url):
    model = safe_model(device_model())
    install_id = installation_id(paths)
    raw_fingerprint = str(item.get("fingerprint", ""))
    if re.fullmatch(r"[a-f0-9]{64}", raw_fingerprint):
        fingerprint = raw_fingerprint
    else:
        fingerprint = hashlib.sha256(raw_fingerprint.encode("utf-8", "replace")).hexdigest()
    title = "[device-log][%s][%s] v%s %s %s" % (
        model, install_id, APP_VERSION, item.get("reason", "unknown")[:80], fingerprint[:12],
    )
    log_text = _redact(item.get("session_log") or _session_log(paths), paths)
    chunks = [
        log_text[index:index + MAX_ISSUE_CHUNK].replace("```", "` ` `")
        for index in range(0, len(log_text), MAX_ISSUE_CHUNK)
    ][:MAX_LOG_CHUNKS] or [""]
    body = "\n".join((
        "Automatic diagnostic report from TrimUI Music Player.",
        "",
        "| Field | Value |",
        "|---|---|",
        "| App | trimui-music-player v%s |" % APP_VERSION,
        "| OS | `%s` |" % paths.os_name,
        "| Model | `%s` |" % model,
        "| Device ID | `%s` |" % install_id,
        "| Python | `%s` |" % sys.version.split()[0],
        "| Reason | `%s` |" % item.get("reason", "unknown")[:80],
        "| Detail | `%s` |" % _redact(item.get("detail", ""), paths).replace("`", ""),
        "| Session log parts | `%d` |" % len(chunks),
        "| Fingerprint | `%s` |" % fingerprint[:16],
        "",
        "> Tokens, private paths, MAC addresses and raw device identifiers are filtered.",
        "",
        "### Session log part 1/%d" % len(chunks),
        "```text",
        chunks[0],
        "```",
    ))
    comments = [
        "Session log part %d/%d\n\n```text\n%s\n```" % (index, len(chunks), chunk)
        for index, chunk in enumerate(chunks[1:], 2)
    ]
    _post_relay(paths, relay_url, title, body, comments, fingerprint)


def retry_pending(paths, force=False):
    pending = _read_json(paths.pending_reports_file, [])
    if not isinstance(pending, list) or not pending:
        return False
    if not force and not _reporting_enabled(paths):
        return False
    relay_url = _report_configuration(paths)
    if not relay_url:
        return False
    remaining = []
    for item in pending:
        try:
            _submit(paths, item, relay_url)
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
    if "--retry-only" not in sys.argv:
        queue_report(paths, reason)
    retry_pending(paths)


if __name__ == "__main__":
    main()
