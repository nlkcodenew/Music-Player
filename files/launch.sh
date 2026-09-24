#!/bin/sh

case "$0" in
    */*) cd "${0%/*}" || exit 1 ;;
esac
APP="$(pwd)"

export SDCARD_PATH="${SDCARD_PATH:-/mnt/SDCARD}"
export PATH="$SDCARD_PATH/System/bin:$PATH"
export LD_LIBRARY_PATH="$APP/libs:$SDCARD_PATH/System/lib:/usr/trimui/lib:$SDCARD_PATH/App/PyUI/dll-mali:$SDCARD_PATH/App/PyUI/dll:$SDCARD_PATH/spruce/flip/lib:/usr/lib64:/usr/lib:/lib:$LD_LIBRARY_PATH"
LOG_FILE="$APP/music-player.log"
STDIO_LOG="$APP/music-player-stdio.log"

usable_python() {
    [ -n "$1" ] && [ -f "$1" ] || return 1
    [ -x "$1" ] || chmod +x "$1" 2>/dev/null
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

find_python() {
    for candidate in \
        "$(command -v python3 2>/dev/null)" \
        "$APP/python/bin/python3" \
        "$SDCARD_PATH/System/bin/python3" \
        "$SDCARD_PATH/spruce/flip/bin/python3.10" \
        "$SDCARD_PATH/spruce/bin/python/bin/python3.10" \
        "$SDCARD_PATH/Apps/PortMaster/PortMaster/exlibs/python3" \
        /usr/bin/python3 /usr/local/bin/python3
    do
        if usable_python "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python)"
if [ -z "$PYTHON" ]; then
    {
        echo "Music Player could not start."
        echo "Python 3.8 or newer was not found."
        echo "Install a current Stock/Spruce runtime or place python3 in $SDCARD_PATH/System/bin."
    } > "$LOG_FILE"
    exit 1
fi

if [ -d "$SDCARD_PATH/spruce" ]; then
    export MUSIC_PLAYER_OS=spruce
else
    export MUSIC_PLAYER_OS=stock
fi

touch /tmp/stay_alive 2>/dev/null
trap 'rm -f /tmp/stay_alive 2>/dev/null' EXIT INT TERM

while true; do
    rm -f "$APP/.restart"
    if [ -f "$STDIO_LOG" ] && [ "$(wc -c < "$STDIO_LOG" 2>/dev/null)" -gt 262144 ]; then
        mv -f "$STDIO_LOG" "$STDIO_LOG.1"
    fi
    "$PYTHON" app.py "$@" >> "$STDIO_LOG" 2>&1
    STATUS=$?
    if [ $STATUS -ne 0 ]; then
        "$PYTHON" -m musicplayer.reporter --reason "exit_$STATUS" >> "$STDIO_LOG" 2>&1 || true
    fi
    [ -f "$APP/.restart" ] || break
done

exit $STATUS

