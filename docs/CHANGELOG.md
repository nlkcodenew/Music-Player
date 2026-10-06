# LỊCH SỬ BẢN — Music Player

> Tổng hợp từ commit/tag. Bản mới nhất: **v1.21.3**.

## v1.21.3 — Lọc lại probe audio: chỉ chặn khi probe abort, lỗi thường vẫn thử mở thật

- Lần v1.21.2 quá strict: probe Bluetooth/ALSA lỗi thường làm parent không thử mở thật nên có thể mất tiếng.
- Probe vẫn chạy, nhưng chỉ trả “chặn” khi tiến trình con abort do ALSA assertion hoặc crash; lỗi `No such device`/busy/bluetooth không chặn luồng mở audio bình thường.

## v1.21.2 — Sửa crash ALSA khi mở audio

- Thêm `audio_probe`: mở thử audio trong tiến trình con trước khi mở thật.
  Nếu thử bị abort do `snd_mask_leave`/ALSA assertion, app tiếp tục đánh dấu
  audio unavailable thay vì văng app. Launcher xuất `MUSIC_PLAYER_AUDIO_PROBE=1`.

## v1.21.0 — Xóa Drive hỏng + tải theo album + playlist + tải cả thư mục

- **Xóa link Drive hỏng**: X trên dòng slot Drive 1–N hoặc Quick Menu →
  Remove This Drive (có hộp xác nhận A/B). `drive.remove_slot()` + xóa cache
  listing, giữ nhạc đã tải. Xóa slot cuối reset về Drive mặc định.
- **Tải về local theo album**: mọi bản lưu nằm ở
  `Music/Drive/<Slot>/<Folder>/` (mỗi album 1 thư mục con, không đổ chung
  vào `Music/`); status `Saved to Drive/...` ghi rõ đích
  (`offline_display_dir()`).
- **Playlist tốt**: playlist tự tạo trong `collections.json`
  (`Playlist 1...`, giữ thứ tự thêm, từ chối `drive://`). PLAYLISTS gộp
  custom trước + folder sau; Quick Menu Add to Playlist / New Playlist /
  Remove / Delete; 24 test mới `test_features_v121.py`.
- **Tải cả thư mục Drive**: X trên thư mục (hoặc Download This Folder) chỉ
  lấy file trực tiếp, bỏ thư mục con (`folder_direct_audio()`); đo tổng
  dung lượng + dung lượng trống SD (`disk_free_bytes`), cảnh báo lớn và hỏi
  xác nhận; tải nối tiếp từng bài, bỏ qua ON DEVICE, rescan 1 lần cuối.
- Footer DRIVE: `A OPEN  X SAVE/DEL  Y MUSIC`; slot list: `X DELETE`.
  Tổng test: 242 passed.

## v1.20.4 — Stock OS FLAC decoder hotfix

- Sửa thứ tự nạp thư viện trên Stock OS để luôn dùng `SDL2_mixer` đóng kèm có
  decoder `dr_flac`, thay vì vô tình dùng bản firmware không hỗ trợ FLAC.
- Loại bỏ cảnh báo `FLAC decoder unavailable` và lỗi
  `Cannot decode / Unrecognized music format` khi mở file FLAC hợp lệ.
- Vẫn giữ SDL2 video/audio của firmware ở ưu tiên cao để tương thích phần cứng.

## v1.20.3 — Universal self-contained Python runtime

- Một ZIP universal duy nhất cho Stock OS + Spruce OS, giải nén vào gốc SD.
- Đóng kèm Python 3.10 ARM64, dynamic loader, glibc, OpenSSL, libffi, zlib và
  toàn bộ native module cần thiết; không còn crash lúc mở vì firmware thiếu
  Python 3.8+ hoặc thiếu thư viện runtime.

## v1.20.2 — Crash reporting sớm + ổn định Drive

- Sửa lỗi `SDL_KEYDOWN` chưa import khi hủy tải/phát Drive; chuyển đúng file
  cache của bài Drive sang Background Playback.
- Crash lúc mở app, lỗi import và process thoát bất thường luôn được lưu và
  gửi qua relay khi có mạng, không phụ thuộc `Auto-report Errors`; launcher
  và Python phối hợp để không tạo hai issue cho cùng một crash.

## v1.20.x — Hoàn thiện tải Drive

- **v1.20.1**: badge ON DEVICE chuyển sang cột cố định bên phải (hết lỗi
  "thư mục có, thư mục mất" với bài tên dài); thông báo giữ nguyên tên file
  kèm đuôi, bỏ đường dẫn; khớp tên chuẩn hóa 2 vế (sanitize + lowercase) +
  bỏ qua file ẩn khi quét.
- **v1.20.0**: % tải vẽ ngay trong dòng đang tải (không phủ trắng màn hình);
  dải strip 30 px cho trường hợp không có dòng; toast nhường chỗ khi đang
  tải; tool `preview_render.py` vẽ màn hình thật ra PNG.

## v1.19.x — Hết treo + nền móng kiểm thử vẽ

- **v1.19.1**: sửa crash `int + tuple` ở badge khi mở thư mục Drive; thêm
  `test_render_smoke.py` chạy thật `_render()` mọi màn hình.
- **v1.19.0**: sửa treo cứng ở bài Drive thứ 3 bằng `StreamJob` dùng chung
  mỗi `file_id` (prefetch + UI không tải trùng) và vòng lặp chờ có Present +
  hủy bằng B; thanh % + toast tên ngắn; offline index phát hiện bài đã có
  (kể cả ở thư mục khác); tool `make_github_release.py`.

## v1.18.0 — Drive list fail-fast, trạng thái offline rõ ràng.

## v1.17.0 — Intro NLK 3 lớp (spread, bounce, glow) + tài liệu tái dùng logo.

## v1.16.0 — Slot list trong DRIVE view, sửa index slot với Settings thật.

## v1.15.x — Slot Drive 1–N, poll tự mở DRIVE khi link xong, link lỗi được
- hàng đợi; link Drive chỉ lưu local + redact khỏi báo lỗi; tỉa log backup
  (v1.15.1).

## v1.14.0 — Thêm Drive riêng qua QR LAN + trang web, đồng bộ tức thì.

## v1.13.x — Dòng Now Playing hiện bitrate + ngõ ra; Y lưu bài đang phát về
- máy; nhãn L2/R2 ở footer (v1.13.1, v1.13.0).

## v1.12.0 — L2 shuffle + R2 repeat mọi nơi, bỏ menu test LED.

## v1.11.x — Cache stream 1 GB LRU, prefetch nền, remap stick/D-pad/L1-R1;
- sửa crash struct jaxis; D-pad theo ngữ cảnh (v1.11.0–v1.11.2).

## v1.10.x — Duyệt + tải Drive công khai không cần API key; gọn gợi ý footer
- (v1.10.0, v1.10.1).

## v1.9.0 — Gốc nguồn MUSIC: chọn LOCAL / DRIVE.

## v1.8.x — Giao diện sáng, splash intro NLK (sửa present khung hình ở
- v1.8.1).

## v1.7.0 — Duyệt thư mục Drive công khai qua API key (bước B).

## v1.6.x — Đóng bước A: phổ nhạc cao hơn (gamma + gain), Quick Menu cuộn
- được, LED 23 slot + chế độ test, OTA kiểm tra định kỳ, audio info trên máy
  (v1.6.0–v1.6.3).

## v1.5.x — Phổ nhạc neo đáy + gain hiển thị.
