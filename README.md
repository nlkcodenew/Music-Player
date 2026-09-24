# Music Player for TrimUI Brick Pro

Music Player is a self-contained music player for TrimUI Brick Pro Stock OS and
Spruce OS. It does not require NextUI libraries or place a hidden application
directory at the SD-card root.

## Version 1.1.0

- Detect Stock OS and Spruce OS at runtime.
- Scan the SD card recursively for WAV, MP3, OGG, FLAC and OPUS files.
- Play through the firmware SDL2_mixer with controller navigation.
- Display synchronized offline LRC lyrics and optional translated LRC lines.
- Stop after a preset time or at the end of the current track with Sleep Timer.
- Turn off the Brick Pro display while playback continues, then wake on any input.
- Persist volume, shuffle, repeat and the last selected track.
- Rotate local logs and preserve pending error reports.
- Create deduplicated GitHub Issues when an Issues-only token is configured.
- Update in place over verified TLS with SHA-256 validation and atomic writes.
- Keep the complete application in one visible menu directory.

AAC/M4A, album art, online lyrics/translation, radio, podcasts, EQ and crossfade
are not included. Screen-off Playback keeps music running while this app remains
open; it is not a background service after launching another application.

## Install

Download exactly one package from the GitHub release:

- Stock OS: `trimui-music-player-v1.1.0-stock.zip`
- Spruce OS: `trimui-music-player-v1.1.0-spruce.zip`

Extract the selected ZIP directly to the SD-card root. Do not copy files between
folders manually.

Stock OS installs one self-contained directory:

```text
/Apps/MusicPlayer/
  app.py
  launch.sh
  config.json
  icon.png
  certs/
  musicplayer/
```

Spruce OS installs the same application in its native menu directory:

```text
/App/MusicPlayer/
  app.py
  launch.sh
  config.json
  icon.png
  certs/
  musicplayer/
```

There is no `/.music-player` directory. Settings, logs, optional credentials and
OTA updates remain inside the installed `MusicPlayer` directory. The visible
menu label remains "Music Player"; the folder name intentionally has no spaces
for compatibility with the Stock OS launcher.

Music is read from `$MUSIC_PLAYER_MUSIC_DIR` when set, otherwise the first
existing path among `Music`, `Media/Music`, `Roms/MUSIC`, and `ROMS/MUSIC` at
the SD-card root.

## Controls

- D-pad: select track; Left/Right seek while playing
- A: play / pause
- B: back; from Library opens exit confirmation
- L1 / R1: previous / next
- L2 / R2: volume down / up
- X: add/remove the selected song or playlist from favorites
- Y in Library: All Songs / Favorite Songs / Playlists / Favorite Playlists
- Y in Now Playing: repeat off / all / one
- Start: library / now playing
- Select: open Quick Menu

To exit, press **B** in Library, then **A** to confirm. Press **B** again to
cancel. The footer displays the controls for the current screen.

Quick Menu provides Lyrics, Sleep Timer, Screen-off Playback, diagnostics and
OTA installation. Use Up/Down to select, A to activate, B or Select to close.
On Sleep Timer, Left/Right or A cycles Off, 15, 30, 45, 60, 90 minutes and End
of track. Any controller input wakes the screen without also triggering an app
action.

## Lyrics

Place a synchronized LRC file beside the matching audio file with the same base
name:

```text
/Music/Album/Song.mp3
/Music/Album/Song.lrc
```

Standard `[mm:ss.xx]text` timestamps, multiple timestamps per line and LRC
`[offset:]` are supported. For an existing translated LRC, append a language
code and keep matching timestamps:

```text
/Music/Album/Song.vi.lrc
/Music/Album/Song.en.lrc
```

Open Lyrics from Quick Menu. Press X on the Lyrics screen to cycle translation
Off and the available language files. Translation is read offline; this release
does not send lyrics to an online translation service.

Each folder under `Music` is treated as a playlist. Favorite songs and favorite
playlists are stored in `data/collections.json` and are preserved by OTA.

## Diagnostics

Run the launcher with `--diagnose` from the installed application directory:

```sh
cd "/mnt/SDCARD/Apps/MusicPlayer" # Stock OS
./launch.sh --diagnose
```

Use `/mnt/SDCARD/App/MusicPlayer` on Spruce OS. Diagnostics and bounded logs
are written in the same application directory.

## GitHub Issues

Copy `secrets.example.json` to `secrets.json` inside the installed
`MusicPlayer` directory. Add a fine-grained token restricted to **Issues: read and
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
