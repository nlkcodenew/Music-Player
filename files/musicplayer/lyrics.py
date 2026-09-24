import bisect
import glob
import os
import re
from dataclasses import dataclass


TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"^\[offset:([+-]?\d+)\]$", re.IGNORECASE)


@dataclass(frozen=True)
class LyricLine:
    timestamp: float
    text: str


def _fraction_seconds(value):
    if not value:
        return 0.0
    return int(value) / (10 ** len(value))


def parse_lrc(value):
    offset = 0.0
    lines = []
    for raw_line in value.splitlines():
        offset_match = OFFSET.match(raw_line.strip().lstrip("\ufeff"))
        if offset_match:
            offset = int(offset_match.group(1)) / 1000.0
            break
    for source_order, raw_line in enumerate(value.splitlines()):
        line = raw_line.strip().lstrip("\ufeff")
        offset_match = OFFSET.match(line)
        if offset_match:
            continue
        matches = list(TIMESTAMP.finditer(line))
        if not matches:
            continue
        text = TIMESTAMP.sub("", line).strip()
        for timestamp_order, match in enumerate(matches):
            seconds = int(match.group(1)) * 60 + int(match.group(2))
            seconds += _fraction_seconds(match.group(3)) + offset
            lines.append((max(0.0, seconds), source_order, timestamp_order, text))
    lines.sort(key=lambda item: (item[0], item[1], item[2]))
    return [LyricLine(item[0], item[3]) for item in lines]


def _read_lrc(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        return parse_lrc(handle.read())


class LyricsDocument:
    def __init__(self, lines, translations=None, source_path=""):
        self.lines = list(lines)
        self.translations = translations or {}
        self.source_path = source_path
        self._timestamps = [line.timestamp for line in self.lines]
        self._translation_maps = {
            language: {round(line.timestamp, 3): line.text for line in translated}
            for language, translated in self.translations.items()
        }

    @property
    def languages(self):
        return sorted(self.translations, key=str.casefold)

    def current_index(self, position):
        if not self.lines:
            return -1
        return bisect.bisect_right(self._timestamps, max(0.0, position)) - 1

    def translation(self, index, language):
        if not language or index < 0 or index >= len(self.lines):
            return ""
        values = self._translation_maps.get(language, {})
        return values.get(round(self.lines[index].timestamp, 3), "")

    def window(self, position, before=2, after=2):
        current = self.current_index(position)
        if current < 0:
            return 0, self.lines[:after + 1]
        start = max(0, current - before)
        return current, self.lines[start:current + after + 1]


def load_lyrics(track_path):
    stem = os.path.splitext(track_path)[0]
    primary_paths = glob.glob(stem + ".[lL][rR][cC]")
    primary_path = primary_paths[0] if primary_paths else stem + ".lrc"
    translation_paths = sorted(glob.glob(stem + ".*.[lL][rR][cC]"), key=str.casefold)
    translations = {}
    for path in translation_paths:
        suffix = path[len(stem) + 1:-4].strip()
        if suffix:
            translations[suffix] = _read_lrc(path)
    if os.path.isfile(primary_path):
        return LyricsDocument(_read_lrc(primary_path), translations, primary_path)
    if translations:
        language = sorted(translations, key=str.casefold)[0]
        lines = translations.pop(language)
        return LyricsDocument(lines, translations, translation_paths[0])
    return LyricsDocument([])
