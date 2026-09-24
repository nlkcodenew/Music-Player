# Music Player for TrimUI Brick Pro

Music Player is a self-contained music player for TrimUI Brick Pro Stock OS and
Spruce OS. It does not require NextUI libraries or place a hidden application
directory at the SD-card root.

## Version 1.3.0

- Detect Stock OS and Spruce OS at runtime.
- Scan the SD card recursively for WAV, MP3, OGG, FLAC and OPUS files.
- Play through the firmware SDL2_mixer with controller navigation.
- Display synchronized offline LRC lyrics and optional translated LRC lines.
- Stop after a preset time or at the end of the current track with Sleep Timer.
- Turn off the Brick Pro display while playback continues, then wake on any input.
- Return to the OS while a separate background service continues playback.
- Show the installed version beside every main screen title.
- Apply a three-band Equalizer with presets before speaker, Bluetooth or USB output.
- Prefer a connected USB Audio DAC in Auto mode and fall back to system audio.
- Bundle a consistent AArch64 SDL2_mixer runtime with FLAC decoding.
- Negotiate Bluetooth/BlueALSA sample rates and keep the UI open if audio is unavailable.
- Use SDL_mixer's finished callback so a temporary Bluetooth stall cannot restart a track.
- Persist volume, shuffle, repeat and the last selected track.
- Rotate local logs and preserve pending error reports.
- Create a new GitHub Issue with the complete current-session log for every manual report.
- Update in place over verified TLS with SHA-256 validation and atomic writes.
- Keep the complete application in one visible menu directory.

AAC/M4A, album art, online lyrics/translation, radio, podcasts and crossfade are
not included.

## Install

Download exactly one package from the GitHub release:

- Stock OS: `trimui-music-player-v1.3.0-stock.zip`
- Spruce OS: `trimui-music-player-v1.3.0-spruce.zip`

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

Active Repeat and Shuffle modes are displayed on the Now Playing screen. Repeat
One intentionally restarts the current song; Repeat All can restart a one-song
queue.

To exit, press **B** in Library, then **A** to confirm. Press **B** again to
cancel. The footer displays the controls for the current screen.

Quick Menu provides Lyrics, Sleep Timer, Screen-off Playback, Background
Playback, diagnostics and OTA installation. It also provides Equalizer and
Audio Output. Use Up/Down to select, A to activate, B or Select to close.
On Sleep Timer, Left/Right or A cycles Off, 15, 30, 45, 60, 90 minutes and End
of track. Any controller input wakes the screen without also triggering an app
action.

## Background Playback

Start a song, then choose `Select > Background Playback (Return to OS)`. Music,
Bluetooth output, EQ, repeat, shuffle and Sleep Timer continue in a detached
audio service after the Music Player window closes. Open Music Player again to
stop the service, reclaim the audio device and resume the same track near its
current position.

Linux audio devices on these firmwares may be exclusive. Navigating the OS and
using applications that do not open audio can run alongside background music.
A game or application that requests exclusive ALSA/BlueALSA access may conflict
with Music Player; stop background playback by opening Music Player before using
that application's audio.

## Equalizer

Open `Select > Equalizer`. Presets include Flat, Bass Boost, Vocal, Rock, Pop,
Classical and Jazz. Bass, Mid and Treble can each be adjusted from `-6 dB` to
`+6 dB`; changing an individual band selects Custom. Automatic headroom reduces
clipping when a band is boosted. Flat bypasses the DSP callback completely.

EQ is applied before the selected output, so it works with the built-in speaker,
wired headphones, Bluetooth A2DP and USB DAC devices. Bluetooth audio is encoded
again by A2DP and should not be described as lossless.

## FLAC And USB DAC

FLAC is decoded locally without lossy transcoding. The current playback pipeline
outputs stereo 16-bit PCM at the sample rate negotiated with Stock OS, Spruce OS,
Bluetooth or USB Audio. This release therefore does not claim bit-perfect or
native high-resolution output, even when the source FLAC or DAC supports it.

Audio Output modes are available in Quick Menu:

- `Auto`: prefer a detected USB/DAC device; otherwise use system audio.
- `System / Bluetooth`: use the OS default, including Spruce BlueALSA A2DP.
- `USB DAC`: request a detected USB/DAC device and fall back safely if absent.

Connect and power the USB DAC or Bluetooth device before opening Music Player.
Output changes are saved and applied on the next app launch. If a DAC is removed
during playback, close and reopen the app to restore the system output safely.

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
are written in the same application directory. Playback state is logged every
10 seconds during this diagnostic phase, including position, duration, repeat,
shuffle and SDL end-of-track state.

## GitHub Issues

Copy `secrets.example.json` to `secrets.json` inside the installed
`MusicPlayer` directory. Add a fine-grained token restricted to **Issues: read and
write** for `nlkcodenew/Music-Player`.

`secrets.json`, settings, identity, pending reports, logs and diagnostics are
never committed, packaged or replaced by OTA. Tokens are never written to logs.
Every press of `Send Diagnostic` creates a separate Issue. The complete log from
that application session is snapshotted immediately; long logs continue in Issue
comments, and failed uploads remain queued for retry.

## Development

Build and verify both packages:

```powershell
python tools/make_release.py
python tools/verify_release.py
```

A `vX.Y.Z` tag publishes the two ZIP files, their SHA-256 sidecars and the
shared `ota-manifest.json` release asset.
