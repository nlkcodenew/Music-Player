#!/bin/sh

SDCARD_PATH="${SDCARD_PATH:-/mnt/SDCARD}"
export SDCARD_PATH

case "$0" in
    /*) APP="${0%/*}" ;;
    */*) APP="$(cd "${0%/*}" 2>/dev/null && pwd)" ;;
    *) APP="$SDCARD_PATH/Apps/MusicPlayer" ;;
esac
[ -d "$APP" ] || APP="$SDCARD_PATH/App/MusicPlayer"

if [ -n "$LOGS_PATH" ] && [ -d "$LOGS_PATH" ]; then
    STDIO_LOG="$LOGS_PATH/MusicPlayer.txt"
elif [ -d "$SDCARD_PATH/Logs" ]; then
    STDIO_LOG="$SDCARD_PATH/Logs/MusicPlayer.txt"
else
    STDIO_LOG="$APP/music-player-stdio.log"
fi
LOG_FILE="$APP/music-player.log"
SESSION_STDIO_LOG="$APP/data/music-player-session-stdio.log"
export MUSIC_PLAYER_STDIO_LOG="$STDIO_LOG"
export MUSIC_PLAYER_SESSION_STDIO_LOG="$SESSION_STDIO_LOG"
export PYTHONUNBUFFERED=1

mkdir -p "$(dirname "$STDIO_LOG")" 2>/dev/null
mkdir -p "$APP/data" 2>/dev/null
{
    echo "================================================"
    echo "Music Player launcher"
    date 2>/dev/null || true
    echo "app=$APP"
    echo "sdcard=$SDCARD_PATH"
    echo "args=$*"
} >> "$STDIO_LOG" 2>&1

if ! cd "$APP" 2>> "$STDIO_LOG"; then
    echo "Cannot enter application directory: $APP" >> "$STDIO_LOG"
    exit 1
fi

export PATH="$SDCARD_PATH/System/bin:$PATH"
export LD_LIBRARY_PATH="$APP/libs:$SDCARD_PATH/System/lib:/usr/trimui/lib:$SDCARD_PATH/App/PyUI/dll-mali:$SDCARD_PATH/App/PyUI/dll:$SDCARD_PATH/spruce/flip/lib:/usr/lib64:/usr/lib:/lib:$LD_LIBRARY_PATH"
export PYSDL2_DLL_PATH="$APP/libs:$SDCARD_PATH/System/lib:/usr/trimui/lib:/usr/lib64:/usr/lib"

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
        echo "Checked $SDCARD_PATH/System/bin/python3 and firmware paths."
    } | tee -a "$LOG_FILE" >> "$STDIO_LOG"
    exit 1
fi

echo "python=$PYTHON" >> "$STDIO_LOG"
"$PYTHON" -c 'import sys; print("python_version=" + sys.version.replace("\n", " "))' >> "$STDIO_LOG" 2>&1

if [ -d "$SDCARD_PATH/spruce" ]; then
    export MUSIC_PLAYER_OS=spruce
    export HOME="$APP/data/home"
    mkdir -p "$HOME"
    if [ -x "$SDCARD_PATH/spruce/scripts/asound-setup.sh" ]; then
        "$SDCARD_PATH/spruce/scripts/asound-setup.sh" "$HOME" >> "$STDIO_LOG" 2>&1 || true
    fi
else
    export MUSIC_PLAYER_OS=stock
fi

touch /tmp/stay_alive 2>/dev/null
KEEP_STAY_ALIVE=0

BACKGROUND_PID="$APP/data/background.pid"
BACKGROUND_COMMAND="$APP/data/background-command"
RESUMING_BACKGROUND=0
is_music_background() {
    [ -n "$1" ] && [ -r "/proc/$1/cmdline" ] || return 1
    CMDLINE="$(tr '\000' ' ' < "/proc/$1/cmdline" 2>/dev/null)"
    case "$CMDLINE" in
        *app.py*--background*) return 0 ;;
        *) return 1 ;;
    esac
}
if [ -f "$BACKGROUND_PID" ]; then
    BG_PID="$(cat "$BACKGROUND_PID" 2>/dev/null)"
    if is_music_background "$BG_PID"; then
        RESUMING_BACKGROUND=1
        echo "foreground" > "$BACKGROUND_COMMAND"
        COUNT=0
        while is_music_background "$BG_PID" && [ "$COUNT" -lt 50 ]; do
            sleep 0.1
            COUNT=$((COUNT + 1))
        done
        if is_music_background "$BG_PID"; then
            kill "$BG_PID" 2>/dev/null || true
            COUNT=0
            while is_music_background "$BG_PID" && [ "$COUNT" -lt 20 ]; do
                sleep 0.1
                COUNT=$((COUNT + 1))
            done
        fi
        if is_music_background "$BG_PID"; then
            kill -9 "$BG_PID" 2>/dev/null || true
        fi
    else
        rm -f "$BACKGROUND_PID" "$BACKGROUND_COMMAND" 2>/dev/null
    fi
fi

if [ "$RESUMING_BACKGROUND" -eq 0 ]; then
    : > "$SESSION_STDIO_LOG"
fi
{
    echo "================================================"
    echo "Music Player session"
    date 2>/dev/null || true
    echo "app=$APP"
    echo "os=$MUSIC_PLAYER_OS"
    echo "args=$*"
} >> "$SESSION_STDIO_LOG" 2>&1

restore_display() {
    RECOVERY_FILE="$APP/data/display-restore.json"
    if [ -n "$PYTHON" ] && [ -f "$RECOVERY_FILE" ]; then
        "$PYTHON" -m musicplayer.display --restore "$RECOVERY_FILE" >> "$STDIO_LOG" 2>&1 || true
    fi
}

cleanup_launcher() {
    restore_display
    [ "$KEEP_STAY_ALIVE" -eq 1 ] || rm -f /tmp/stay_alive 2>/dev/null
}

trap cleanup_launcher EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while true; do
    rm -f "$APP/.restart"
    if [ -f "$STDIO_LOG" ] && [ "$(wc -c < "$STDIO_LOG" 2>/dev/null)" -gt 524288 ]; then
        mv -f "$STDIO_LOG" "$STDIO_LOG.1"
        echo "Music Player log rotated" > "$STDIO_LOG"
    fi
    "$PYTHON" app.py "$@" >> "$SESSION_STDIO_LOG" 2>&1
    STATUS=$?
    restore_display
    echo "app_exit=$STATUS" >> "$STDIO_LOG"
    if [ "$STATUS" -eq 20 ]; then
        KEEP_STAY_ALIVE=1
        nohup "$PYTHON" app.py --background </dev/null >> "$SESSION_STDIO_LOG" 2>&1 &
        BG_PID=$!
        echo "$BG_PID" > "$BACKGROUND_PID"
        echo "background_pid=$BG_PID" >> "$STDIO_LOG"
        exit 0
    fi
    if [ "$STATUS" -ne 0 ]; then
        "$PYTHON" app.py --diagnose >> "$STDIO_LOG" 2>&1 || true
        "$PYTHON" -m musicplayer.reporter --reason "exit_$STATUS" >> "$STDIO_LOG" 2>&1 || true
        sync 2>/dev/null || true
    else
        "$PYTHON" -m musicplayer.reporter --retry-only >> "$STDIO_LOG" 2>&1 || true
    fi
    [ -f "$APP/.restart" ] || break
done

cat "$SESSION_STDIO_LOG" >> "$STDIO_LOG" 2>/dev/null || true

exit "$STATUS"
