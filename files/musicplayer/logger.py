import logging
import os
from logging.handlers import RotatingFileHandler


LOGGER_NAME = "musicplayer"
MAX_LOG_BYTES = 512 * 1024
BACKUP_COUNT = 2


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


def log_backup_bytes(paths):
    """Total bytes currently held by rotated log backups."""
    total = 0
    for path in log_backup_paths(paths):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total
