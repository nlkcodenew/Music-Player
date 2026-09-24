import ctypes
import ctypes.util
import json
import os
import platform
import sys


LIBRARIES = {
    "sdl2": ("SDL2", "libSDL2-2.0.so.0", "libSDL2-2.0.so", "libSDL2.so"),
    "sdl2_ttf": ("SDL2_ttf", "libSDL2_ttf-2.0.so.0", "libSDL2_ttf-2.0.so", "libSDL2_ttf.so"),
    "sdl2_mixer": ("SDL2_mixer", "libSDL2_mixer-2.0.so.0", "libSDL2_mixer-2.0.so", "libSDL2_mixer.so"),
}


def library_directories(paths):
    return (
        os.path.join(paths.app_dir, "libs"),
        os.path.join(paths.sdcard_path, "System", "lib"),
        "/usr/trimui/lib",
        os.path.join(paths.sdcard_path, "App", "PyUI", "dll-mali"),
        os.path.join(paths.sdcard_path, "App", "PyUI", "dll"),
        "/usr/lib64",
        "/usr/lib",
        "/lib",
    )


def library_candidates(paths, names):
    candidates = []
    found = ctypes.util.find_library(names[0])
    if found:
        candidates.append(found)
    for directory in library_directories(paths):
        candidates.extend(os.path.join(directory, name) for name in names[1:])
    candidates.extend(names[1:])
    result = []
    for candidate in candidates:
        if candidate not in result:
            result.append(candidate)
    return result


def probe_library(paths, names):
    attempts = []
    for candidate in library_candidates(paths, names):
        try:
            ctypes.CDLL(candidate)
            return {"available": True, "loaded": candidate, "attempts": attempts}
        except OSError as error:
            attempts.append({"path": candidate, "error": str(error)})
    return {"available": False, "loaded": "", "attempts": attempts}


def collect_diagnostics(paths):
    return {
        "app_dir": paths.app_dir,
        "sdcard_path": paths.sdcard_path,
        "music_dir": paths.music_dir,
        "data_dir": paths.data_dir,
        "detected_os": paths.os_name,
        "python": sys.version.replace("\n", " "),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "environment": {
            key: os.environ.get(key, "")
            for key in (
                "SDCARD_PATH", "PLATFORM", "DEVICE", "IS_NEXT", "MUSIC_PLAYER_OS",
                "SDL_AUDIODRIVER", "SDL_VIDEODRIVER", "LD_LIBRARY_PATH",
            )
        },
        "libraries": {
            name: probe_library(paths, candidates)
            for name, candidates in LIBRARIES.items()
        },
    }


def write_diagnostics(paths, report):
    output = os.path.join(paths.app_dir, "music-player-diagnostics.json")
    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return output

