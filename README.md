# Music Player for TrimUI (Brick Pro / Smart Pro S)

Self-contained music player for TrimUI Brick Pro Stock OS and Spruce OS
(Smart Pro S). No NextUI libraries required, no hidden directory at the
SD-card root.

## Highlights (v1.21.0)

- Recursive SD-card scan for WAV, MP3, OGG, FLAC, OPUS — plays through the
  bundled SDL2/SDL2_ttf/SDL2_mixer runtime with full controller navigation.
- **Google Drive**: browse shared folders, stream tracks, and save them to the
  device for offline listening. Multiple Drive slots (Drive 1–N), keyless
  public-folder access, optional API key.
- **Drive slots can be removed**: X on a slot row, or Quick Menu → Remove
  This Drive when a link is broken. Cached listing is cleared, saved music
  in `Music/Drive/` is kept.
- **Offline layout**: every save lands in its own `Music/Drive/<Slot>/<Folder>/`
  subfolder (never dumped into `Music/` root); the status names the
  destination so LOCAL stays organized.
- **Custom playlists**: Quick Menu → Add to Playlist / New Playlist
  (auto-named `Playlist N`, no typing needed). PLAYLISTS shows custom lists
  first, then folder lists; custom lists keep their added order.
- **Download a whole Drive folder (X on a folder)**: only files directly
  inside are taken, subfolders are skipped. The app shows track count, total
  size and SD free space and asks A to confirm / B to cancel before saving
  files one by one into `Music/Drive/<Slot>/<Folder>/`.
- **Non-blocking downloads**: streaming and saving run on background jobs with
  a shared single-flight registry — playback never freezes, progress renders
  **inside the downloading row** (`Saving 2MB / 7MB`, `32%`), B cancels.
- **ON DEVICE badge**: tracks already saved on the device (even in another
  folder) are marked in every Drive list; re-saving is skipped with
  `Already saved: <full filename>`.
- Wordmark **NLK** boot splash (skippable with any key, toggle in Quick Menu).
- Synchronized offline LRC lyrics with optional translation lines.
- Sleep timer, screen-off playback, background playback after returning to OS.
- Three-band equalizer with presets; USB DAC auto-preference with safe
  fallback; Bluetooth/BlueALSA support.
- In-place OTA updates over verified TLS (SHA-256, atomic writes).
- Bundled Python 3.10 AArch64 runtime, glibc loader, OpenSSL, ctypes and zlib;
  no Python package or matching runtime libraries are required from firmware.
- Diagnostics via a credential-free HTTPS relay — no GitHub token ever lives
  in the app, ZIP, manifest, SD card, or request URL. Fatal crashes are
  reported automatically when online (or queued until the next launch);
  non-fatal automatic error reporting remains off by default.

AAC/M4A, album art, online lyrics/translation, radio, podcasts and crossfade
are not included.

## Install

Download the single universal package from the
[latest release](https://github.com/nlkcodenew/Music-Player/releases/latest):

- Stock OS + Spruce OS: `trimui-music-player-vX.Y.Z-universal.zip`

Extract the ZIP directly to the SD-card root. It contains the native menu
directory for both systems; each OS ignores the other directory.

Stock OS installs one self-contained directory:

```text
/Apps/MusicPlayer/
  app.py
  launch.sh
  config.json
  icon.png
  certs/
  musicplayer/
  python/
```

Spruce OS installs the same application in its native menu directory:

```text
/App/MusicPlayer/
  ...same layout...
```

Settings, logs and OTA state stay inside the installed `MusicPlayer`
directory. The visible menu label remains "Music Player".

Music is read from `$MUSIC_PLAYER_MUSIC_DIR` when set, otherwise the first
existing path among `Music`, `Media/Music`, `Roms/MUSIC`, `ROMS/MUSIC` at the
SD-card root. Drive downloads land in `Music/Drive/<Slot>/<Folder>/` — one
subfolder per Drive album, never mixed into `Music/` root.

## Controls

Library views: **All Songs / Favorites / Playlists (custom + folder) /
MUSIC source** (LOCAL + DRIVE + Add Drive) / **DRIVE browser**.

- D-pad: move selection; Left/Right seek while playing
- A: open / play / pause; A confirms dialogs
- B: back / cancel download; from Library opens exit confirmation; B cancels dialogs
- L1 / R1: previous / next track
- L2 / R2: shuffle toggle / repeat cycle (everywhere)
- X in Drive list on a track: save track to device (background, with % in the row)
- X in Drive list on a folder: download the whole folder (direct files only,
  subfolders skipped, with SD-space check + A/B confirmation)
- X in Drive slot list (Drive 1–N): remove that Drive link (with confirmation)
- X elsewhere: add/remove favorite
- Y in Library: switch view (All Songs / Favorites / Playlists / MUSIC)
- Y in Now Playing: save current Drive track to device
- Start: library / now playing
- Select: Quick Menu

Footer hints always show the controls for the current screen. To exit, press
**B** in Library, then **A** to confirm.

Quick Menu: Lyrics, Equalizer, Audio Output, Sleep Timer, Screen-off
Playback, Background Playback, NLK intro on/off, Add to Playlist / New
Playlist, Drive Refresh / Download Folder / Remove This Drive / slots,
Add Drive (QR over LAN), diagnostics, OTA install, `Auto-report Errors`
(opt-in).

## Drive in 30 seconds

1. Library → Y → MUSIC → DRIVE (or pick a Drive 1–N slot).
2. Browse folders with A, go back with B.
3. Press **X** on a track to save it to `Music/Drive/<Slot>/<Folder>/` — the
   row itself shows the live %.
4. Press **X** on a folder to download the whole folder (direct audio files
   only, subfolders skipped) after checking SD free space and confirming.
5. Press **X** on a Drive 1–N slot row (or Quick Menu → Remove This Drive)
   to delete a broken link.
6. Tracks already on the device show **ON DEVICE** and are never
   re-downloaded.
7. Saved tracks appear in LOCAL after an automatic library rescan.

No API key is needed for public ("Anyone with the link") folders. For
private or quota-sensitive shares, paste a key in Quick Menu → Drive
settings. Your own Drive folder can be linked from your phone: Quick Menu →
Add Drive shows a QR code served over LAN.

Details: `docs/USER_GUIDE.md`, `docs/DRIVE_OFFLINE.md` (Vietnamese).

## Development

```powershell
py -3 -m compileall -q files tools tests
py -3 -m unittest tests.test_core tests.test_drive_download tests.test_render_smoke tests.test_features_v121
py -3 tools/make_release.py
py -3 tools/verify_release.py
py -3 tools/preview_render.py   # render real screens to dist/preview/*.png
```

Docs (Vietnamese maintainer handbook): `docs/DEVELOPMENT.md` (module map,
tests, release flow, conventions), `docs/CHANGELOG.md` (version history),
`docs/PROJECT_STATUS.md` (current release state).

Rules: bump `APP_VERSION` in `files/musicplayer/__init__.py` for every
payload change — never retag a published release. Keep tokens, user data and
runtime files out of the manifest and ZIPs.
