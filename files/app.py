#!/usr/bin/env python3

import argparse
import json
import os
import sys
import traceback

from musicplayer import APP_VERSION
from musicplayer.library import scan_library
from musicplayer.logger import get_logger, init_logging, prune_log_backups
from musicplayer.paths import RuntimePaths

def pending_reports_waiting(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            pending = json.load(handle)
        return isinstance(pending, list) and bool(pending)
    except (OSError, ValueError, TypeError):
        return False


def parse_args():
    parser = argparse.ArgumentParser(description="Portable Music Player for TrimUI")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--background", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    paths = RuntimePaths.discover()
    paths.ensure_writable_dirs()
    resume_path = os.path.join(paths.data_dir, "background-resume.json")
    status_path = os.path.join(paths.data_dir, "background-status.json")
    init_logging(
        paths.log_file, paths.session_log_file,
        append_session=args.background or os.path.isfile(resume_path) or os.path.isfile(status_path),
    )
    log = get_logger()
    try:
        prune_log_backups(paths)
    except Exception as error:
        log.warning("log prune failed: %s", error)
    log.info(
        "starting Music Player version=%s os=%s mode=%s",
        APP_VERSION, paths.os_name, "background" if args.background else "foreground",
    )
    if args.background:
        from musicplayer.background import run_background
        return run_background(paths)
    if pending_reports_waiting(paths.pending_reports_file):
        from musicplayer.reporter import retry_pending
        retry_pending(paths)

    if args.diagnose:
        from musicplayer.diagnostics import collect_diagnostics, write_diagnostics
        report = collect_diagnostics(paths)
        output = write_diagnostics(paths, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("diagnostics written to %s" % output)
        return 0

    tracks = scan_library(paths.music_dir)
    log.info("library scan found %d tracks in %s", len(tracks), paths.music_dir)
    if args.scan:
        for track in tracks:
            print(track.path)
        return 0

    from musicplayer.ui import MusicPlayerApp

    return MusicPlayerApp(paths, tracks).run()


if __name__ == "__main__":
    paths = RuntimePaths.discover()
    try:
        sys.exit(main())
    except Exception:
        error = traceback.format_exc()
        try:
            from musicplayer.reporter import queue_report, retry_pending
            init_logging(
                paths.log_file, getattr(paths, "session_log_file", None), append_session=True
            )
            get_logger().error("unhandled crash\n%s", error)
            queue_report(paths, "python_crash", mandatory=True)
            with open(os.path.join(paths.data_dir, "crash-handled"), "w", encoding="ascii") as handle:
                handle.write("python_crash\n")
            retry_pending(paths)
        except Exception:
            sys.stderr.write(error)
        sys.exit(1)
