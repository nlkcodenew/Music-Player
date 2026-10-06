import logging
import os
import time
from logging.handlers import RotatingFileHandler


LOGGER_NAME = "musicplayer"
MAX_LOG_BYTES = 512 * 1024
BACKUP_COUNT = 2
MAX_BACKUP_BYTES = 1024 * 1024
MAX_BACKUP_AGE_DAYS = 14


def init_logging(path, session_path=None, append_session=False):
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(threadName)s] %(name)s - %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        path, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if session_path:
        os.makedirs(os.path.dirname(session_path), exist_ok=True)
        session_handler = logging.FileHandler(
            session_path, mode="a" if append_session else "w", encoding="utf-8"
        )
        session_handler.setFormatter(formatter)
        logger.addHandler(session_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def get_logger():
    return logging.getLogger(LOGGER_NAME)


def log_backup_paths(paths):
    """Rotated backups that are safe to delete (live logs excluded)."""
    candidates = []
    for path in (
        getattr(paths, "log_file", ""),
        getattr(paths, "stdio_log_file", ""),
    ):
        if not isinstance(path, str) or not path:
            continue
        candidates.append(path + ".1")
        candidates.append(path + ".2")
    seen = []
    for path in candidates:
        if path not in seen:
            seen.append(path)
    return seen


def clear_log_backups(paths):
    """Delete rotated log backups; returns freed bytes."""
    freed = 0
    for path in log_backup_paths(paths):
        try:
            freed += os.path.getsize(path)
            os.unlink(path)
        except OSError:
            pass
    if freed:
        get_logger().info("cleared log backups bytes=%d", freed)
    return freed

def prune_log_backups(paths, now=None, max_age_days=MAX_BACKUP_AGE_DAYS,
                      max_total_bytes=MAX_BACKUP_BYTES):
    """Remove stale backups, then keep newest backups within the byte cap."""
    current_time = time.time() if now is None else float(now)
    maximum_age = max(0, int(max_age_days)) * 24 * 60 * 60
    entries = []
    freed = 0
    for path in log_backup_paths(paths):
        try:
            size = os.path.getsize(path)
            modified = os.path.getmtime(path)
        except OSError:
            continue
        if maximum_age and current_time - modified > maximum_age:
            try:
                os.unlink(path)
                freed += size
            except OSError:
                entries.append((modified, size, path))
        else:
            entries.append((modified, size, path))
    total = sum(size for _modified, size, _path in entries)
    for _modified, size, path in sorted(entries):
        if total <= max(0, int(max_total_bytes)):
            break
        try:
            os.unlink(path)
            total -= size
            freed += size
        except OSError:
            pass
    if freed:
        get_logger().info("automatically pruned log backups bytes=%d", freed)
    return freed


def log_backup_bytes(paths):
    """Total bytes currently held by rotated log backups."""
    total = 0
    for path in log_backup_paths(paths):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total
