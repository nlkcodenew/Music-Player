# PHÁT TRIỂN — Music Player

> Sổ tay maintainer (tiếng Việt). Người dùng đọc `USER_GUIDE.md`; kiến trúc
> Drive đọc `DRIVE_OFFLINE.md`; lịch sử bản đọc `CHANGELOG.md`.

## 1. Bản đồ module (`files/musicplayer/`)

| File | Trách nhiệm |
|---|---|
| `__init__.py` | `APP_VERSION` — nguồn version duy nhất |
| `ui.py` | Vòng lặp chính, mọi màn hình, intro NLK, tiến trình tải, toast |
| `drive.py` | Drive API, `StreamJob`, cache, offline index, giới hạn dung lượng |
| `drivelink.py` | Server LAN + QR để link Drive riêng từ điện thoại |
| `audio.py` / `audio_output.py` | Phát qua SDL_mixer, chọn USB DAC / System / BT |
| `equalizer.py` | EQ 3 band + preset, DSP callback |
| `library.py` | `Track(path,title,folder,extension)`, `scan_library()` |
| `lyrics.py` | Parse LRC + bản dịch `.vi.lrc` |
| `settings.py` | Mặc định + chuẩn hóa settings (volume, shuffle, repeat, drive_*, intro…) |
| `paths.py` | Tìm gốc SD, phân biệt Stock/Spruce, đường dẫn runtime |
| `background.py` | Service phát nền khi về OS, resume vị trí cũ |
| `updater.py` | OTA: kiểm tra, tải, verify SHA-256, ghi atomic, không xóa user data |
| `reporter.py` / `identity.py` | ID `MP-xxxxxxxx`, hàng đợi báo lỗi, relay HTTPS không token |
| `display.py` / `leds.py` | Tắt/mở màn hình khi phát, LED theo phổ |
| `sleep_timer.py` / `collections.py` | Hẹn giờ, yêu thích + playlist tự tạo (`custom_playlists`, giữ thứ tự, gộp custom trước folder) |
| `sdl_runtime.py` / `input.py` / `visuals.py` | Nạp SDL2, map phím, phổ nhạc |
| `ssl_context.py` / `diagnostics.py` / `logger.py` / `audio_format.py` / `qrcode.py` | TLS verify, diagnose, log xoay vòng, định dạng audio, QR |

`files/app.py` + `files/launch.sh`: điểm vào + launcher (chọn SDL hệ thống
trên Spruce, ưu tiên native bind trước `dll-mali`). `files/release.json`:
repo GitHub cho tool release. `files/reporting.json`: URL relay công khai.

## 2. Test — 242 test, 4 file

| File | Phủ |
|---|---|
| `tests/test_core.py` | Thư viện, paths, settings, audio/EQ, lyrics, Drive list/cache/prefetch, UI logic |
| `tests/test_drive_download.py` | Job dùng chung (không tải trùng), % kẹp 0–100, hủy, resolve không block UI, offline index + khớp tên/kích thước, toast, badge, strip/inline progress |
| `tests/test_render_smoke.py` | **Chạy thật `_render()`** mọi màn hình + trạng thái (stub duy nhất là SDL và `measure` trả đúng tuple như TTF thật) |
| `tests/test_features_v121.py` | Xóa slot (X + Quick Menu + reset default), tải theo album, playlist tự tạo (tạo/thêm/giữ thứ tự/xóa), tải cả thư mục (bỏ subfolder, check SD, xác nhận, tải nối tiếp) |

Chạy:

```powershell
py -3 -m compileall -q files tools tests
py -3 -m unittest tests.test_core tests.test_drive_download tests.test_render_smoke tests.test_features_v121
```

Bài học xương máu (v1.19.0): crash `int + tuple` ở badge lọt qua vì không
test nào gọi `_render()` thật. Từ đó mọi code vẽ phải được smoke test bao —
trong đó có test **cố tình cấm** `fill(0,0,W,H)` khi đang tải (chống lớp phủ
trắng toàn màn hình quay lại) và test badge với tên bài 56 ký tự.

ALSA abort lesson: v1.21.2–v1.21.4 thêm `musicplayer/audio_probe.py` và
`MUSIC_PLAYER_AUDIO_PROBE=1` trong `launch.sh` để thử mở audio trong tiến
trình con. Nếu child abort với `snd_mask_leave: Assertion ...`, parent chặn
luồng audio thật và đặt `Audio unavailable` thay vì để ALSA kill app; lỗi
thường (busy, no device, chưa có Bluetooth PCM) vẫn thử mở audio thật.

## 3. Preview màn hình thật

```powershell
py -3 tools/preview_render.py   # ra dist/preview/01..05*.png
```

Tool dùng **đúng hàm vẽ của app**, chỉ thay SDL bằng PIL + font TTF thật.
Sửa layout xong thì mở PNG kiểm tra bằng mắt: list Drive có % trong dòng +
badge, dải strip ở Now Playing, toast tên đầy đủ, thư viện local, bản
1280x720. `dist/` đã gitignore nên ảnh không lọt vào release.

## 4. Release — một ZIP universal

```powershell
py -3 tools/vendor_python_runtime.py # lấy Python ARM64 từ TrimUI SDK
py -3 tools/make_release.py          # manifest + universal ZIP + SHA-256
py -3 tools/verify_release.py        # entry, hash, quyền, cấm token, cấm user-data
py -3 tools/make_github_release.py   # tạo Release + upload asset (token từ git credential)
```

- Universal ZIP chứa `Apps/MusicPlayer` cho Stock và `App/MusicPlayer` cho
  Spruce; mỗi layout đều có runtime Python 3.10 ARM64 hoàn chỉnh.
- `EXCLUDED` (không bao giờ đóng gói/OTA đè): `settings.json`,
  `collections.json`, `identity.json`, `pending-reports.json`, log, cache,
  trạng thái background/drive.
- Quy tắc sắt: **đổi version cho mọi thay đổi payload, không bao giờ retag**
  bản đã publish. Version chỉ nằm ở `APP_VERSION`; manifest/ZIP/tag/release
  đều suy ra từ đó.
- Sau publish: `git push origin main` + `git push origin vX.Y.Z`.

## 5. Quy ước code

- Python 3 stdlib + ctypes (không dependency runtime); Windows dev dùng
  `py -3` (không có `python3/head/grep`).
- Comment giải thích "vì sao" bằng tiếng Việt, ngắn gọn; docstring tiếng Việt
  cho hàm mới.
- `measure()` trả **tuple** `(w, h)` — lấy `[0]` trước khi cộng số (lỗi
  v1.19.0, đã có test gác).
- Mọi I/O mạng/đĩa nặng cấm chạy trên UI thread — dùng job nền + vòng lặp
  pump (`_wait_for_download` là mẫu chuẩn).
- Không `print` stacktrace ra màn hình máy; dùng `get_logger()`.
- Không thêm token, tên repo diagnostics private, hay user-data vào app /
  manifest / ZIP — `verify_release.py` gác cửa.
