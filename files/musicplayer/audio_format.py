import os
import struct
import wave

_CACHE = {}
_CACHE_ORDER = []
MAX_CACHE = 512

_MP3_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}


def _remember(path, value):
    if path in _CACHE:
        return value
    _CACHE[path] = value
    _CACHE_ORDER.append(path)
    while len(_CACHE_ORDER) > MAX_CACHE:
        _CACHE.pop(_CACHE_ORDER.pop(0), None)
    return value


def _wav_info(path):
    try:
        with wave.open(path, "rb") as handle:
            return (int(handle.getframerate() or 0), int(handle.getsampwidth() or 0) * 8)
    except Exception:
        return (0, 0)


def _flac_info(path):
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != b"fLaC":
                return (0, 0)
            while True:
                header = handle.read(4)
                if len(header) < 4:
                    return (0, 0)
                last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                if block_type == 0:
                    data = handle.read(34)
                    if len(data) < 18:
                        return (0, 0)
                    rate = (data[10] << 12) | (data[11] << 4) | (data[12] >> 4)
                    bits = (((data[12] & 0x01) << 4) | (data[13] >> 4)) + 1
                    return (rate, bits)
                handle.seek(length, os.SEEK_CUR)
                if last:
                    return (0, 0)
    except Exception:
        return (0, 0)


def _mp3_info(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except Exception:
        return (0, 0)
    for index in range(len(data) - 4):
        if data[index] != 0xFF or (data[index + 1] & 0xE0) != 0xE0:
            continue
        version = (data[index + 1] >> 3) & 0x03
        layer = (data[index + 1] >> 1) & 0x03
        rate_index = (data[index + 2] >> 2) & 0x03
        if version == 1 or layer == 0 or rate_index == 3:
            continue
        return (_MP3_RATES[version][rate_index], 0)
    return (0, 0)


def track_audio_info(path):
    key = os.path.abspath(path) if isinstance(path, str) else str(path)
    if key in _CACHE:
        return _CACHE[key]
    try:
        extension = os.path.splitext(key)[1].lower()
    except Exception:
        extension = ""
    if extension == ".wav":
        info = _wav_info(key)
    elif extension == ".flac":
        info = _flac_info(key)
    elif extension == ".mp3":
        info = _mp3_info(key)
    else:
        info = (0, 0)
    return _remember(key, info)


def format_rate(rate_hz):
    try:
        rate = int(rate_hz)
    except (TypeError, ValueError):
        return ""
    if rate <= 0:
        return ""
    return "%.1fk" % (rate / 1000.0)


def format_spec(path):
    try:
        extension = os.path.splitext(path)[1].lower().lstrip(".")
    except Exception:
        extension = ""
    try:
        rate, bits = track_audio_info(path)
    except Exception:
        rate, bits = (0, 0)
    rate_text = format_rate(rate)
    if rate_text and bits:
        return "%s/%d" % (rate_text, bits)
    if rate_text:
        return rate_text
    return extension.upper() if extension else "---"


def clear_cache():
    _CACHE.clear()
    del _CACHE_ORDER[:]
