# Buoc A — visuals + LED + UI kieu Truepod (DONE, v1.4.0 -> v1.6.2)

> Ngay close: 2026-10-02. Trang thai: code + test + release xong, da verify
> tren may that (LED nhay theo nhac, OTA live ve trong luc app mo).
> Buoc B (Google Drive) lam tiep, khong cham vao phan nay nua.

## 1. Lam duoc gi (7 releases)

| Version | Noi dung | Commit |
|---|---|---|
| v1.4.0 | Core Buoc A: postmix tap luon chay, `SpectrumAnalyser` trong `AudioPlayer`, `LedController` + spectrum 14 cot + settings `led_mode`/`spectrum` + Quick Menu | `f403b5b` |
| v1.4.1 | LED rainbow HSV vivid, spectrum gradient to, tieu de tu thu nho, layout vua man 480px. Fix bug `available` chan ghi LED sau `suspend_engine()` | `f6115db` |
| v1.5.0 | UI kieu Truepod: theme do/den, library cot spec phai, Now Playing progress manh + dong CONVERTED/DIRECT, spectrum do full-width co peak-cap trang, Quick Menu 2 cot | `774e55d` |
| v1.5.1 | Spectrum neo xuong day man hinh, gain hien thi 1.6x, progress day 8px | `088c8a9` |
| v1.6.0 | OTA tu check lai moi 5 phut + nut `Check for Update`, them `Audio Info` (decoder + output/rate). Xac minh lib co san DRFLAC/MINIMP3/stb_vorbis/OPUS/WAV | `69e0886` |
| v1.6.1 | Cot spectrum cao gap doi cam nhan (gain 2.0 + gamma 0.75) | `131dc0d` |
| v1.6.2 | Quick Menu scroll duoc (13 muc tran man 480px), gain 3.0 + gamma 0.6, nen khoi info gon hon | `d327b2d` |

Trang thai hien tai: 76/76 tests OK, manifest 34 files, ZIP stock + spruce verified.

- Stock SHA-256: `e6a0a8c1c824828a412ac4dd754fa9e676b0b70059e155de3855491d3dc2d222`
- Spruce SHA-256: `50ada629b5c3648acb3af85a2e3a86097886edf4dde9320c1799b360b5a7c63b`

## 2. Kien truc (de Buoc B khong dap do)

- `files/musicplayer/visuals.py`: `SpectrumAnalyser` — RMS + FFT 256 + 14 bands log,
  attack nhanh/release cham, beat detect tu bass, `peaks` hold roi cham cho peak-cap.
  Snapshot giu nguyen 3-tuple `(levels, rms, beat)` + `snapshot_peaks()`.
- `files/musicplayer/leds.py`: `LedController` — HSV wheel full rainbow, xoay 8 do/frame,
  beat thi chop trang 1 LED chay vong, ghi sysfs toi da ~16fps, tu disable sau 8 loi,
  khong co node thi `available=False`, app van chay.
- `files/musicplayer/equalizer.py`: 1 callback postmix duy nhat — EQ xong (hoac
  pass-through khi Flat) thi `analyser.offer()`. Khong analyser + Flat = khong cai
  callback (giu behavior cu, test cu van pass).
- `files/musicplayer/audio.py`: `AudioPlayer.analyser`, set sample_rate khi mo audio,
  `reset()` moi bai, `decay()` khi pause/stop.
- `files/musicplayer/audio_format.py`: doc spec that tu header WAV/FLAC/MP3
  (`44.1k/16`...), OGG/OPUS fallback ten duoi, co cache 512 entries.
- `files/musicplayer/ui.py`: theme do/den, library cot spec + breadcrumb, Now Playing
  (title auto-fit, progress manh, CONVERTED/DIRECT, spectrum do day man hinh),
  Quick Menu 2 cot co scroll, OTA check dinh ky 5 phut + check tay.
- `files/musicplayer/settings.py`: them `led_mode` (off/beat/spectrum, default spectrum),
  `spectrum` (bool, default True), co normalize khi load.

## 3. Da verify tren may that

1. LED nhay theo nhac, nhieu mau (rainbow), beat chop trang.
2. Thoat app LED tra ve binh thuong (restore engine + clear frame).
3. OTA live: app dang mo van nhan bao update (tu dong <= 5 phut, hoac bam tay).
4. FLAC phat truc tiep (decoder build san trong lib, khong can cai them).
5. DAC Type-C: header hien `USB DAC` khi mo duoc, tu rot ve loa may + canh bao
   khi khong thay. Kiem tra tren may: Quick Menu -> `Audio Info`.

## 4. Quyet dinh da chot (dung dao lai khi lam Buoc B)

- Khong patch/copy binary Truepod (proprietary): chi hoc layout/style.
- Postmix callback khong log/IO, FFT throttle 0.07s (audio thread).
- Ghi LED toi da ~16fps, backoff + tu disable khi loi.
- OTA: tang version moi payload change, khong retag release da publish.
- 2 che do LED: `beat` chi ghi khi co beat (tiet kiem sysfs), `spectrum` ghi lien tuc.

## 5. File lien quan (mo ra doc la hieu)

- `files/musicplayer/ui.py` — `_render_playing`, `_render_spectrum`, `_render_library`,
  `_render_quick_menu`, `_maybe_check_update`, `_audio_info_line`
- `files/musicplayer/visuals.py`, `files/musicplayer/leds.py`,
  `files/musicplayer/equalizer.py`, `files/musicplayer/audio.py`,
  `files/musicplayer/audio_format.py`, `files/musicplayer/settings.py`
- `tests/test_core.py` — `VisualsTapTests`, `LedControllerTests`, `TruepodStyleTests`,
  `OtaRecheckTests` (+ 49 tests goc tu v1.3.2)
- Doc goc de lai lam reference: `docs/VISUALS_AND_DRIVE_PLAN.md`
