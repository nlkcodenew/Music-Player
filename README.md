# Portable Music Player

This repository is the Stock OS / Spruce OS rewrite of NextUI Music Player. It
does not link `libmsettings`, compile NextUI platform sources, or require NextUI
environment variables.

## Version 1.0.0

- Detect Stock OS and Spruce OS at runtime.
- Scan the SD card recursively for WAV, MP3, OGG, FLAC and OPUS files.
- Play through firmware SDL2_mixer with controller navigation. Codec support is
  reported at startup and depends on the OS mixer; unsupported files show a
  visible error instead of crashing the app.
- Persist volume, shuffle, repeat and the last selected track.
- Rotate local logs and preserve pending error reports.
- Create deduplicated GitHub Issues when a user provides an Issues-only token.
- Check immutable OTA manifests over verified TLS, verify SHA-256, stage, apply
  atomically and restart through the launcher.
- Generate one ZIP rooted at `App/Music Player/` for both supported OSes.

AAC/M4A, playlists, album art, lyrics, radio, podcasts and downloads will be
ported from the original implementation as independent later modules.

## Install

Build the package, then extract it at the SD-card root:

```powershell
python tools/make_release.py
python tools/verify_release.py
```

Publish the ZIP, its `.sha256` sidecar, and `portable-manifest.json` from
`dist/` on a tag named `vX.Y.Z` so OTA uses immutable URLs.

The resulting layout deliberately contains one shared payload and two tiny menu
entries because Stock OS uses `Apps/` while Spruce uses `App/`:

```text
/.music-player/             # real app; OTA updates only this directory
  app.py
  musicplayer/
App/Music Player/           # Spruce menu entry
  config.json
  launch.sh
Apps/Music Player/          # Stock OS menu entry
  config.json
  launch.sh
```

Both launchers execute the same `/.music-player/launch.sh`. Logs, settings,
tokens and OTA state therefore cannot diverge when the SD card boots another
OS.

Music is read from `$MUSIC_PLAYER_MUSIC_DIR` when set, otherwise the first
existing path among `Music`, `Media/Music`, `Roms/MUSIC`, and `ROMS/MUSIC` at
the SD-card root.

## Controls

- D-pad: select track; Left/Right seek while playing
- A: play / pause
- B: back / exit
- L1 / R1: previous / next
- L2 / R2: volume down / up
- X: shuffle
- Y: repeat off / all / one
- Start: library / now playing

## Diagnostics

Run this on the device:

```sh
cd "/mnt/SDCARD/App/Music Player"
./launch.sh --diagnose
```

It writes `music-player-diagnostics.json`. Normal logs are in
`music-player.log`, with bounded rotated backups.

To enable automatic GitHub Issue reports, copy `secrets.example.json` to
`secrets.json` and provide a fine-grained token restricted to **Issues: read
and write** for the target repository. Tokens and raw secrets are never logged,
uploaded, included in OTA, or included in release archives.
