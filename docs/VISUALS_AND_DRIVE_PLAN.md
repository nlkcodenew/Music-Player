# Visuals + Google Drive plan — Music Player (doc hien tai, chua code tiep)

> Ngay: 2026-10-01. Trang thai: da phan tich xong Truepod + app nha, da co 2 file moi
> CHUA GAN vao pipeline. Cho ban doc xong moi lam tiep.

## 1. Truepod repo + binary noi gi (da boc xong)

- Repo `E:\Trimiu Brick Pro\Project APPS\truepod`: chi co README/RELEASE/TERMS/media,
  khong co source. LICENSE proprietary, cam sua/phat tan binary.
- Binary `E:\Trimiu Brick Pro\Truepod-0.2.0-stockOS\Apps\Truepod\truepod`:
  ELF ARM 64-bit, Rust, chay qua `mplayer` cua may.
- Menu Options trong binary thay: `LEDs`, `Rumble`, `Screen off`, `Wi-Fi sync`,
  `Telegram sync`, `Bottom USB DAC`, + 1 chuoi `Premium required`.
- Khong thay code Spotify/SoundCloud/Navidrome/Subsonic/playlist .m3u/favourites/
  queue/gapless/EQ/sleep-timer/tieng-Viet trong binary 0.2.0 nay.
- `launch.sh` cua Truepod ghi ro: ban Free bo qua block `telegram` trong config,
  chi giu lai de ban Premium sau dung tiep.
- Ket luan: khong mo khoa Pro tu binary nay duoc (stub UI + vi pham LICENSE).
  Chi HOC duoc: UI dep, LED nhay theo nhac, spectrum, Wi-Fi upload QR.

## 2. Cach Truepod lai LED (da tim ra node sysfs)

- Tat engine mac dinh: ghi `0` vao `/sys/class/led_anim/effect_enable`
  (fallback `/sys/class/led_anim/enable`).
- Ve frame: ghi chuoi hex vao `/sys/class/led_anim/frame_hex`.
- Tra lai khi thoat: ghi `1` vao `effect_enable`, xoa frame.
- `launch.sh` cua Truepod cung lam viec nay o cuoi de chong treo LED.
- Rumble: qua `/sys/class/gpio/gpio227/value` (motor).
- Neu khong co node LED: Truepod chi hien spectrum tren man hinh.
  App minh lam y het: co node thi lai LED, khong co thi chi ve spectrum.

## 3. App nha hien tai (v1.3.2, 49/49 tests OK)

- Goc chay: `files/app.py` -> `MusicPlayerApp(files/musicplayer/ui.py).run()`.
- Phat nhac: `AudioPlayer(files/musicplayer/audio.py)` chi `Mix_LoadMUS(track.path)`,
  file local tren the SD, chua phat URL/stream.
- Thu vien: `scan_library(files/musicplayer/library.py)` de quy thu muc local.
- EQ san co `Mix_SetPostMix` trong `files/musicplayer/equalizer.py`:
  chi chay khi gains != (0,0,0). Day la cho moc analyser ly tuong.
- Now Playing (`ui.py:771 _render_playing`): text + thanh tien trinh,
  chua cover art, chua spectrum.
- Settings hien tai: volume/shuffle/repeat/last_track/auto_update/lyrics/EQ/
  audio_output/auto_report_errors. Chua co gi ve LED/visual/drive.
- Hien tai branch `main` sach, 2 file moi dang untracked:
  `files/musicplayer/visuals.py` (155 dong), `files/musicplayer/leds.py` (127 dong).

## 4. Hai file moi da viet (chua gan vao app)

### files/musicplayer/visuals.py — SpectrumAnalyser
- Nhan PCM S16 stereo tu postmix, tinh RMS + FFT 256 diem + 14 band log,
  attack nhanh / release cham, phat hien beat tu bass.
- API: `offer(pcm)`, `snapshot() -> (levels, rms, beat)`, `decay()`,
  `set_sample_rate()`, `reset()`.
- Chay duoc khong can audioop (co fallback struct), khong them lib moi.
- Da compile OK, test nhanh: RMS ~0.048 voi tin hieu test, band dau len ~0.14.

### files/musicplayer/leds.py — LedController
- Tim node `/sys/class/led_anim/frame_hex` + `effect_enable`/`enable`.
- `frame_for_levels(levels, rms, beat, tick)`: 1 LED/band, mau xoay wheel RGB,
  do sang theo level, beat thi chop trang 1 LED chay vong.
- `LedController.update(levels, rms, beat)`: ghi toi da ~16fps, tranh ghi lap,
  tu disable sau 8 loi. Khong co node -> `available=False`, app van chay.
- `suspend_engine()` / `restore_engine()` / `clear()` de tra LED khi thoat.
- Da compile OK, test frame mau OK tren Windows (khong ghi sysfs that).

## 5. Viec con lai (CHUA LAM, cho ban chot)

### Buoc A — gan analyser vao pipeline (can code)
1. Them visual tap `Mix_SetPostMix` LUON CHAY ke ca EQ Flat: EQ xu ly xong
   (hoac pass-through) thi `analyser.offer(pcm)`, chi 1 callback duy nhat.
2. `AudioPlayer` giu 1 `SpectrumAnalyser`, cap nhat sample_rate khi mo audio,
   `reset()` moi bai, `decay()` khi pause/stop.
3. `LedController` khoi tao o `MusicPlayerApp.initialize()`, `suspend_engine()`
   khi mo, `update()` moi frame (~16fps), `restore_engine()+clear()` o `cleanup()`.
4. Ve spectrum 14 cot len Now Playing + LED hardware (neu co).
5. Them settings: `led_mode` (off/beat/spectrum), `spectrum` (on/off).
   Luu vao settings.json, them menu Quick Menu.

### Buoc B — Google Drive public (~5TB, online + tai ve)
- Link da chot: folder `1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a`, che do
  `Anyone with link - Viewer`.
- Nguyen tac RAM: KHONG quet toan bo. Duyet tung folder theo trang (pageSize
  nho, files.list q=parents, fields toi thieu, chi audio/flac/mp3...), cache
  danh sach ra disk, stream tung bai qua `uc?export=download&id=FILE_ID`
  hoac `drive.googleapis.com/uc?export=download&id=`.
- Che do: vua stream truc tuyen, vua cho tai bai thich ve thu muc music gon
  (vi du `Music/Drive/<TenAlbum>/<nn Title>.flac`), nghe offline nhu nhac local.
- Can module moi `drive.py` + man hinh DRIVE trong Library + luu link folder
  vao settings. Dung `urllib` + `ssl_context.verified_context` san co,
  khong them token (link public).
- Can ban xac nhan: dung API key cong khai hay chi dung endpoint download
  cong khai khong key.

## 6. Rui ro da thay

- `audioop` deprecation tren Python 3.12 (van chay, se mat o 3.13):
  `visuals.py` + `equalizer.py` da co fallback/du phong, can nho khi nang Python.
- Postmix callback chay tren audio thread: chi copy/RMS nhe, FFT lam thua
  (TAP_INTERVAL 0.07s), khong log/IO trong callback.
- Ghi LED qua sysfs: toi da ~16fps, co backoff + tu disable khi loi.
- OTA: 2 file moi se lam manifest len 33 files, can tang version + regen ZIP
  + verify lai truoc khi release.
- Khong patch binary Truepod: vi pham LICENSE + de brick may.

## 7. Len mo may de xem them

- `E:\Trimiu Brick Pro\Project APPS\Music-Player\files\musicplayer\ui.py:771`
- `E:\Trimiu Brick Pro\Project APPS\Music-Player\files\musicplayer\audio.py:150`
- `E:\Trimiu Brick Pro\Project APPS\Music-Player\files\musicplayer\equalizer.py:110`
- `E:\Trimiu Brick Pro\Project APPS\Music-Player\files\musicplayer\visuals.py`
- `E:\Trimiu Brick Pro\Project APPS\Music-Player\files\musicplayer\leds.py`