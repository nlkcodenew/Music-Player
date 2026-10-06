# Music Player — project status v1.20.3

> Updated 2026-10-06. Toàn bộ tài liệu hiện tại: `README.md` (tổng quan),
> `docs/USER_GUIDE.md` (người dùng), `docs/DRIVE_OFFLINE.md` (kiến trúc
> Drive), `docs/DEVELOPMENT.md` (dev), `docs/CHANGELOG.md` (lịch sử bản).
> Các file `STEP_A_DONE.md`, `VISUALS_AND_DRIVE_PLAN.md` là archive của bước
> A/B (đã đóng từ v1.7.0–v1.6.3), chỉ giữ để tra cứu.

## Current release

| Item | Value |
|---|---|
| Latest release | `v1.20.3` |
| Release page | `https://github.com/nlkcodenew/Music-Player/releases/tag/v1.20.3` |
| Package | One universal ZIP for Stock + Spruce |
| Runtime | Bundled Python 3.10 AArch64 + native dependency closure |
| Unit tests | 216/216 passed (`test_core` + `test_drive_download` + `test_render_smoke`) |

Public release gồm `ota-manifest.json`, một universal ZIP + SHA-256 sidecar.
Cổng kiểm tra local: version, hash, số entry, quyền file, cấm token marker,
cấm user-data trong OTA/ZIP.

## Platform packaging

- Stock OS: `Apps/MusicPlayer`. Spruce OS: `App/MusicPlayer`. Hai layout nằm
  chung trong một ZIP và đều kèm Python 3.10 ARM64, glibc/OpenSSL/libffi/zlib
  dependency closure cùng SDL2_mixer AArch64.
- Không OTA đè, không đóng gói: `settings.json`, `collections.json`,
  `identity.json`, `pending-reports.json`, log, `drive-cache.json`, trạng
  thái background.

## Diagnostics and device identity

Header hiện `vX.Y.Z | ID: MP-xxxxxxxx`; ID ổn định trong
`data/identity.json`, xuất hiện nguyên vẹn trong Issue để đối chiếu, không lộ
serial/MAC. `Send Diagnostic` là consent tường minh cho từng lần gửi;
crash nghiêm trọng luôn được gửi khi có mạng; `Auto-report Errors` cho lỗi
không nghiêm trọng mặc định off. Client không chứa token/repo private nào;
relay duy nhất: `https://trimui-music-player-issue-relay.issue-relay.workers.dev/report`
(token chỉ là Cloudflare Worker secret; xoay token không cần release app).

## Spruce SDL compatibility

Spruce SmartProS nạp SDL2/SDL2_ttf từ bind path của Spruce trước `dll-mali`
(tránh crash `mali-fbdev` tiền-v1.3.2). Launcher đã kiểm chứng video init +
44.1 kHz + Bluetooth + thoát sạch.

## Security and release gates (không được nới)

1. Luôn verify TLS cert + hostname.
2. Không token/secret/tên repo private trong app, manifest, ZIP.
3. User-data/runtime không vào manifest/ZIP.
4. Crash nghiêm trọng được gửi bắt buộc; auto-report lỗi không nghiêm trọng
   mặc định off.
5. Đổi version cho mọi thay đổi payload; không retag bản đã publish.

Standard gate:

```powershell
py -3 -m compileall -q files tools tests
py -3 -m unittest tests.test_core tests.test_drive_download tests.test_render_smoke
py -3 tools/make_release.py
py -3 tools/verify_release.py
git diff --check
```

## Session close

- `v1.20.3` là OTA + GitHub latest sau khi release upload hoàn tất.
- Lỗi máy Stock firmware cũ không có Python 3.8+ đã được loại bỏ bằng runtime
  self-contained; không cần PortMaster hay cập nhật firmware để mở app.
