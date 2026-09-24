#!/bin/sh

SDCARD_PATH="${SDCARD_PATH:-/mnt/SDCARD}"
PAYLOAD="$SDCARD_PATH/.music-player/launch.sh"

if [ ! -f "$PAYLOAD" ]; then
    echo "Music Player payload is missing: $PAYLOAD" > "$SDCARD_PATH/music-player-install-error.txt"
    exit 1
fi

[ -x "$PAYLOAD" ] || chmod +x "$PAYLOAD" 2>/dev/null
exec "$PAYLOAD" "$@"

