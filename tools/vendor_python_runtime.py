#!/usr/bin/env python3

import argparse
import os
import shutil
import struct
import sys
import tempfile
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "files", "python")
LIBS_OUTPUT = os.path.join(ROOT, "files", "libs")
DEFAULT_SYSROOT = os.path.abspath(os.path.join(
    ROOT, "..", "sdk-tg5050", "sdk_tg5050_linux_v1.0.0", "host",
    "aarch64-buildroot-linux-gnu", "sysroot",
))
PYTHON_VERSION = "3.10"
SKIP_STDLIB_DIRS = {
    "__pycache__", "config-3.10-aarch64-linux-gnu", "distutils", "ensurepip",
    "idlelib", "site-packages", "test", "tests", "tkinter", "turtledemo", "venv",
}
EXTRA_RUNTIME_LIBS = (
    "libnss_files.so.2", "libnss_dns.so.2", "libresolv.so.2",
)
SDL_ROOT_LIBS = {
    "libSDL2-2.0.so.0": "libSDL2-2.0.so.0",
    "libSDL2_ttf-2.0.so.0": "libSDL2_ttf-2.0.so.0",
    "libasound.so.2": "libasound.so.2",
}


def _elf_needed(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:6] != b"\x7fELF\x02\x01":
        return []
    program_offset = struct.unpack_from("<Q", data, 32)[0]
    program_size = struct.unpack_from("<H", data, 54)[0]
    program_count = struct.unpack_from("<H", data, 56)[0]
    loads = []
    dynamic = None
    for index in range(program_count):
        offset = program_offset + index * program_size
        values = struct.unpack_from("<IIQQQQQQ", data, offset)
        segment_type, _, file_offset, virtual, _, file_size, memory_size, _ = values
        if segment_type == 1:
            loads.append((virtual, memory_size, file_offset))
        elif segment_type == 2:
            dynamic = (file_offset, file_size)
    if dynamic is None:
        return []
    string_address = None
    needed_offsets = []
    start, size = dynamic
    for offset in range(start, start + size, 16):
        tag, value = struct.unpack_from("<qQ", data, offset)
        if tag == 0:
            break
        if tag == 1:
            needed_offsets.append(value)
        elif tag == 5:
            string_address = value
    if string_address is None:
        return []
    string_offset = None
    for virtual, memory_size, file_offset in loads:
        if virtual <= string_address < virtual + memory_size:
            string_offset = file_offset + string_address - virtual
            break
    if string_offset is None:
        raise ValueError("cannot locate ELF string table: %s" % path)
    names = []
    for offset in needed_offsets:
        start = string_offset + offset
        end = data.find(b"\0", start)
        names.append(data[start:end].decode("ascii"))
    return names


def _runtime_library_index(sysroot):
    candidates = {}
    for directory in (os.path.join(sysroot, "lib"), os.path.join(sysroot, "usr", "lib")):
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                candidates.setdefault(name, []).append(path)
    return candidates


def _resolve_library(name, index):
    exact = index.get(name, [])
    if exact:
        return exact[0]
    stem = name.split(".so", 1)[0]
    candidates = []
    for candidate_name, paths in index.items():
        if candidate_name.startswith(stem + ".so.") or candidate_name.startswith(stem + "-"):
            candidates.extend(paths)
    if not candidates:
        raise FileNotFoundError("runtime library not found: %s" % name)
    return sorted(candidates, key=lambda path: (len(os.path.basename(path)), path))[0]


def _copy(path, destination, executable=False):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copyfile(path, destination)
    os.chmod(destination, 0o755 if executable else 0o644)


def _stdlib_zip(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for current, directories, filenames in os.walk(source):
            directories[:] = sorted(name for name in directories if name not in SKIP_STDLIB_DIRS)
            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(current, filename)
                relative = os.path.relpath(path, source).replace(os.sep, "/")
                info = zipfile.ZipInfo(relative, (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with open(path, "rb") as handle:
                    archive.writestr(info, handle.read(), compresslevel=9)


def _write_launcher(path):
    content = """#!/bin/sh
RUNTIME=$(CDPATH= cd -- "$(dirname "$0")/.." 2>/dev/null && pwd)
[ -n "$RUNTIME" ] || exit 126
export PYTHONHOME="$RUNTIME"
export PYTHONPATH="$RUNTIME/lib/python310.zip:$RUNTIME/lib/python3.10/lib-dynload"
export LD_LIBRARY_PATH="$RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$RUNTIME/lib/ld-linux-aarch64.so.1" \\
    --library-path "$LD_LIBRARY_PATH" \\
    "$RUNTIME/bin/python3.10" "$@"
"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.chmod(path, 0o755)


def build_runtime(sysroot):
    sysroot = os.path.abspath(sysroot)
    python_binary = os.path.join(sysroot, "usr", "bin", "python3.10")
    stdlib = os.path.join(sysroot, "usr", "lib", "python3.10")
    dynamic_modules = os.path.join(stdlib, "lib-dynload")
    for required in (python_binary, stdlib, dynamic_modules):
        if not os.path.exists(required):
            raise SystemExit("TrimUI SDK Python runtime missing: %s" % required)
    output = os.path.abspath(OUTPUT)
    files_root = os.path.abspath(os.path.join(ROOT, "files"))
    if os.path.commonpath((output, files_root)) != files_root:
        raise SystemExit("refusing to write runtime outside files directory")
    shutil.rmtree(output, ignore_errors=True)
    _copy(python_binary, os.path.join(output, "bin", "python3.10"), executable=True)
    _write_launcher(os.path.join(output, "bin", "python3"))
    _stdlib_zip(stdlib, os.path.join(output, "lib", "python310.zip"))
    license_path = os.path.join(stdlib, "LICENSE.txt")
    _copy(license_path, os.path.join(output, "LICENSE.python.txt"))

    native_paths = [python_binary]
    target_dynamic = os.path.join(output, "lib", "python3.10", "lib-dynload")
    for filename in sorted(os.listdir(dynamic_modules)):
        source = os.path.join(dynamic_modules, filename)
        if os.path.isfile(source) and filename.endswith(".so"):
            destination = os.path.join(target_dynamic, filename)
            _copy(source, destination, executable=True)
            native_paths.append(source)

    index = _runtime_library_index(sysroot)
    pending = []
    for native_path in native_paths:
        pending.extend(_elf_needed(native_path))
    pending.extend(EXTRA_RUNTIME_LIBS)
    copied = set()
    while pending:
        name = pending.pop(0)
        if name in copied or name == "ld-linux-aarch64.so.1":
            continue
        source = _resolve_library(name, index)
        destination = os.path.join(output, "lib", name)
        _copy(source, destination, executable=True)
        copied.add(name)
        pending.extend(_elf_needed(source))

    loader = os.path.join(sysroot, "lib", "ld-linux-aarch64.so.1")
    _copy(loader, os.path.join(output, "lib", "ld-linux-aarch64.so.1"), executable=True)
    total = sum(
        os.path.getsize(os.path.join(current, filename))
        for current, _, filenames in os.walk(output)
        for filename in filenames
    )
    print("vendored Python %s AArch64 runtime: %d files, %.1f MiB" % (
        PYTHON_VERSION,
        sum(len(filenames) for _, _, filenames in os.walk(output)),
        total / (1024 * 1024),
    ))


def build_sdl_runtime(sysroot):
    output = os.path.abspath(LIBS_OUTPUT)
    files_root = os.path.abspath(os.path.join(ROOT, "files"))
    if os.path.commonpath((output, files_root)) != files_root:
        raise SystemExit("refusing to write SDL runtime outside files directory")
    mixer = os.path.join(output, "libSDL2_mixer-2.0.so")
    if not os.path.isfile(mixer):
        raise SystemExit("bundled SDL2_mixer source is missing: %s" % mixer)
    descriptor, preserved_mixer = tempfile.mkstemp(prefix="music-player-mixer-", suffix=".so")
    os.close(descriptor)
    shutil.copyfile(mixer, preserved_mixer)
    try:
        shutil.rmtree(output, ignore_errors=True)
        os.makedirs(output, exist_ok=True)
        shutil.copyfile(preserved_mixer, mixer)
    finally:
        if os.path.exists(preserved_mixer):
            os.unlink(preserved_mixer)
    os.chmod(mixer, 0o755)
    index = _runtime_library_index(sysroot)
    shared_runtime = set(os.listdir(os.path.join(OUTPUT, "lib")))
    pending = list(_elf_needed(mixer)) + list(SDL_ROOT_LIBS)
    copied = set()
    while pending:
        name = pending.pop(0)
        if name in copied or name == "ld-linux-aarch64.so.1":
            continue
        if name in shared_runtime:
            copied.add(name)
            continue
        source = _resolve_library(name, index)
        destination_name = SDL_ROOT_LIBS.get(name, name)
        destination = os.path.join(output, destination_name)
        if not os.path.exists(destination):
            _copy(source, destination, executable=True)
        copied.add(name)
        pending.extend(_elf_needed(source))
    total = sum(os.path.getsize(os.path.join(output, name)) for name in os.listdir(output))
    print("vendored SDL AArch64 runtime: %d files, %.1f MiB" % (
        len(os.listdir(output)), total / (1024 * 1024),
    ))


def main():
    parser = argparse.ArgumentParser(description="Vendor TrimUI SDK Python AArch64 runtime")
    parser.add_argument(
        "--sysroot", default=os.environ.get("TRIMUI_SDK_SYSROOT", DEFAULT_SYSROOT),
        help="TrimUI AArch64 SDK sysroot",
    )
    args = parser.parse_args()
    build_runtime(args.sysroot)
    build_sdl_runtime(os.path.abspath(args.sysroot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
