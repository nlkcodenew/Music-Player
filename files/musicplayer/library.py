import os
import re
from dataclasses import dataclass


SUPPORTED_EXTENSIONS = frozenset((".wav", ".mp3", ".ogg", ".flac", ".opus"))
_PARTS = re.compile(r"(\d+)")


def natural_key(value):
    return tuple(int(part) if part.isdigit() else part.casefold() for part in _PARTS.split(value))


@dataclass(frozen=True)
class Track:
    path: str
    title: str
    folder: str
    extension: str


def scan_library(root):
    if not os.path.isdir(root):
        return []
    tracks = []
    for current, directories, filenames in os.walk(root):
        directories[:] = sorted(
            (name for name in directories if not name.startswith(".")), key=natural_key
        )
        for filename in sorted(filenames, key=natural_key):
            extension = os.path.splitext(filename)[1].lower()
            if filename.startswith(".") or extension not in SUPPORTED_EXTENSIONS:
                continue
            path = os.path.abspath(os.path.join(current, filename))
            folder = os.path.relpath(current, root)
            tracks.append(Track(
                path=path,
                title=os.path.splitext(filename)[0],
                folder="Music" if folder == "." else folder,
                extension=extension,
            ))
    tracks.sort(key=lambda track: natural_key(os.path.relpath(track.path, root)))
    return tracks

