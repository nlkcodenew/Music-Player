# Music Player for TrimUI Brick Pro

Music Player is a self-contained music player for TrimUI Brick Pro Stock OS and
Spruce OS. It does not require NextUI libraries or place a hidden application
directory at the SD-card root.

## Version 1.0.1

- Detect Stock OS and Spruce OS at runtime.
- Scan the SD card recursively for WAV, MP3, OGG, FLAC and OPUS files.
- Play through the firmware SDL2_mixer with controller navigation.
- Persist volume, shuffle, repeat and the last selected track.
- Rotate local logs and preserve pending error reports.
- Create deduplicated GitHub Issues when an Issues-only token is configured.
- Update in place over verified TLS with SHA-256 validation and atomic writes.
- Keep the complete application in one visible menu directory.

AAC/M4A, playlists, album art, lyrics, radio, podcasts and downloads are not yet
included.

## Install

Download exactly one package from the GitHub release:

- Stock OS: `trimui-music-player-v1.0.1-stock.zip`
- Spruce OS: `trimui-music-player-v1.0.1-spruce.zip`

Extract the selected ZIP directly to the SD-card root. Do not copy files between
folders manually.

Stock OS installs one self-contained directory:

```text
/Apps/Music Player/
  app.py
  launch.sh
  config.json
  icon.png
  certs/
  musicplayer/
```

Spruce OS installs the same application in its native menu directory:

```text
/App/Music Player/
  app.py
  launch.sh
  config.json
  icon.png
  certs/
  musicplayer/
```

There is no `/.music-player` directory. Settings, logs, optional credentials and
OTA updates remain inside the installed `Music Player` directory.

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

Run the launcher with `--diagnose` from the installed application directory:

```sh
cd "/mnt/SDCARD/Apps/Music Player" # Stock OS
./launch.sh --diagnose
```

Use `/mnt/SDCARD/App/Music Player` on Spruce OS. Diagnostics and bounded logs
are written in the same application directory.

## GitHub Issues

Copy `secrets.example.json` to `secrets.json` inside the installed `Music
Player` directory. Add a fine-grained token restricted to **Issues: read and
write** for `nlkcodenew/Music-Player`.

`secrets.json`, settings, identity, pending reports, logs and diagnostics are
never committed, packaged or replaced by OTA. Tokens are never written to logs.

## Development

Build and verify both packages:

```powershell
python tools/make_release.py
python tools/verify_release.py
```

A `vX.Y.Z` tag publishes the two ZIP files, their SHA-256 sidecars and the
shared `ota-manifest.json` release asset.
