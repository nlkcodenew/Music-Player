# Music Player — project status v1.20.1

> Updated 2026-10-03. Toàn bộ tài liệu hiện tại: `README.md` (tổng quan),
> `docs/USER_GUIDE.md` (người dùng), `docs/DRIVE_OFFLINE.md` (kiến trúc
> Drive), `docs/DEVELOPMENT.md` (dev), `docs/CHANGELOG.md` (lịch sử bản).
> Các file `STEP_A_DONE.md`, `VISUALS_AND_DRIVE_PLAN.md` là archive của bước
> A/B (đã đóng từ v1.7.0–v1.6.3), chỉ giữ để tra cứu.

## Current release

| Item | Value |
|---|---|
| Latest release | `v1.20.1` |
| Commits/tags | `4298db0` / `v1.20.1` (+ `main` đã push) |
| Release page | `https://github.com/nlkcodenew/Music-Player/releases/tag/v1.20.1` |
| OTA files | 37 |
| Stock/Spruce ZIP entries | 37 / 37 (verified) |
| Unit tests | 211/211 passed (`test_core` + `test_drive_download` + `test_render_smoke`) |

Public release gồm `ota-manifest.json`, 2 ZIP platform + 2 SHA-256 sidecar.
Cổng kiểm tra local: version, hash, số entry, quyền file, cấm token marker,
cấm user-data trong OTA/ZIP.

## Platform packaging

- Stock OS: `Apps/MusicPlayer`. Spruce OS: `App/MusicPlayer`. Cùng 37 file
  OTA + runtime SDL2_mixer AArch64 bundled.
- Không OTA đè, không đóng gói: `settings.json`, `collections.json`,
  `identity.json`, `pending-reports.json`, log, `drive-cache.json`, trạng
  thái background.

## Diagnostics and device identity

Header hiện `vX.Y.Z | ID: MP-xxxxxxxx`; ID ổn định trong
`data/identity.json`, xuất hiện nguyên vẹn trong Issue để đối chiếu, không lộ
serial/MAC. `Send Diagnostic` là consent tường minh cho từng lần gửi;
`Auto-report Errors` mặc định off. Client không chứa token/repo private nào;
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
4. Consent tường minh: auto-report mặc định off.
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

- `v1.20.1` là OTA + GitHub latest. `main`, `origin/main`, tag `v1.20.1`
  đồng bộ sau release upload OK (5/5 asset).
- Không còn task mở: treo Drive (v1.19.0), crash badge (v1.19.1), progress
  trong dòng + toast tên đầy đủ (v1.20.x) đều đã xong và có test gác.
