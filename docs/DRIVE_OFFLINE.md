# KIẾN TRÚC DRIVE & OFFLINE — Music Player v1.19–v1.20

> Tài liệu kỹ thuật cho dev. Hướng dẫn người dùng ở `USER_GUIDE.md`.
> Code: `files/musicplayer/drive.py` (mạng + job + index),
> `files/musicplayer/ui.py` (vẽ + điều khiển), `files/musicplayer/drivelink.py`
> (QR link Drive riêng qua LAN).

## 1. Vì sao từng treo máy ở bài Drive thứ 3 (v1.19.0)

`AudioPlayer.play()` gọi `drive_resolver` → `drive_ensure_stream_file()`
**tải đồng bộ trên UI thread**: suốt quá trình tải không một khung hình nào
được vẽ, không hút sự kiện — nhìn như "treo cứng". Prefetch (tải trước 1 bài)
lại không dùng chung trạng thái với thread chính nên hai bên có thể tải trùng
1 file. Bài 1–2 còn trong cache nên qua được, tới bài 3 phải tải thật là dính.

Cách sửa: **một `StreamJob` dùng chung cho mỗi `file_id`** (`_JOBS` +
`_JOBS_LOCK`, `drive.py:679`). Prefetch và màn hình chính luôn nắm cùng 1
job — bên nào tới trước tạo job, bên sau chỉ theo dõi. Đường phát không còn
gọi hàm tải đồng bộ nào; `_drive_resolve_track()` + `_wait_for_download()`
chờ trong **vòng lặp có Present + hút sự kiện**, B/ESC hủy được, quá 240 s tự
hủy thay vì treo vô hạn.

## 2. StreamJob

`drive.py:613` — job tải nền, 2 loại (`kind`):

- `stream`: tải về `data/drive-cache/<file_id><ext>` để phát.
- `offline`: tải về `Music/Drive/<Album>/<tên file>` (qua `offline_path()`).

Trường quan trọng: `file_id` (khóa dùng chung), `title`, `total` (dung lượng
kỳ vọng), `bytes` (đã tải), `path` (đích khi xong), `error`, `entry`, `album`.
`percent` luôn kẹp 0–1 và **không bao giờ chạm 100% trước khi `done`**
(khi chưa biết tổng thì ước lượng để % vẫn nhích). `update()` được truyền làm
callback `progress` cho `_download_to_path()` nên % là byte thật, không phải
giả lập. `cancel()` / `is_cancelled()` cho nút B.

Giới hạn an toàn: 1 file tối đa `MAX_TRACK_BYTES` (700 MB), cache stream tối
đa `MAX_STREAM_CACHE_BYTES` (1 GB, LRU qua `enforce_stream_cache_limit()`),
job xong giữ tối đa `keep=8` (`clear_finished_jobs()`, UI gọi dọn mỗi 60 s).

## 3. Vẽ tiến trình: % nằm trong dòng (v1.20.0)

`_render_download_progress()` **không bao giờ phủ toàn màn hình**.
Luồng quyết định:

1. `_download_job_for_row(row)` — job offline đang chạy có phải của đúng
   dòng này không: khớp `file_id` với dòng Drive; khớp basename tên file với
   dòng thư viện local (không có `file_id`).
2. Nếu dòng đang tải lọt vào list đang xem → `_draw_inline_progress()` vẽ
   ngay trong dòng: `Saving 2MB / 7MB`, `%` lớn mép phải, thanh chạy suốt
   dòng. Dòng đang chọn (nền xanh) dùng thanh **nền tối** để không hòa vào
   nền; dòng thường dùng màu accent.
3. Không có dòng nào khớp (đang ở NOW PLAYING, LYRICS…) →
   `_render_download_strip()`: dải 30 px dưới header (`SAVING TO DEVICE |
   tên bài | xMB/yMB | %` + thanh mảnh), vẫn thấy bài đang phát và phổ nhạc.
4. Ô `SAVED <tên file>` và status `Saved:` / `Already saved:` nhường chỗ
   trong lúc đang tải, xong mới hiện — hai thông báo không đè nhau.

## 4. Nhận diện "bài đã có trên máy" — ON DEVICE

Vấn đề khó: **1 bài Drive có thể đã được lưu ở nhiều thư mục khác nhau**
(`Music/Drive/<Album A>/`, `<Album B>/`…), nên không thể chỉ kiểm tra "đích
sắp lưu có tồn tại không".

Giải pháp — chỉ mục ngược (`drive.py:752+`):

- `offline_index()` quét toàn bộ `Music/Drive/` **một lần**, cache 15 s
  (`_OFFLINE_INDEX_TTL`), làm mới ngay sau mỗi lần lưu xong. Bỏ qua file/
  thư mục ẩn (`.drive-saved.json`…).
- Khóa so khớp là `offline_key()` = `sanitize_component(basename).lower()`:
  **cùng một phép biến đổi** áp cho cả tên Drive lẫn tên file trên đĩa (gom
  khoảng trắng, bỏ ký tự lạ, cắt 80 ký tự, không phân biệt hoa thường) — vì
  tên lưu trên máy đã qua sanitize nên so chuỗi thô sẽ lệch.
- Giá trị là list `(đường dẫn, kích thước)` vì 1 tên có thể ở nhiều nơi.
  Khi Drive cho biết kích thước (luôn có khi list) thì **phải khớp thêm kích
  thước** — tránh nhầm 2 bài khác nhau trùng tên; chỉ khi không biết kích
  thước mới chấp nhận trùng tên.

UI: `_drive_row_is_saved()` cache kết quả theo `(file_id, size)` trong một
lần vẽ; `_invalidate_saved_rows()` xóa cache sau mỗi lần lưu. Badge
**ON DEVICE nằm ở cột cố định bên phải** (thay chỗ cột định dạng), không nối
sau tiêu đề — trước đây bài tên dài đẩy badge ra khỏi màn hình nên "thư mục
này có, thư mục kia mất" (sửa ở v1.20.1). `_save_entry_offline()` gặp bài đã
có thì báo `Already saved: <tên>` và **không tải lại**.

## 5. Thông báo tên file: đầy đủ, không đường dẫn

`_short_saved_name()` trả **nguyên tên file kèm đuôi**
(`04. giac mo con mai - le quuyen [FLAC].flac`), loại hoàn toàn đường dẫn
`/mnt/SDCARD/...` (dài quá sẽ cắt mất cả tên). Fallback 3 tầng:
`entry.name` → basename đường dẫn → `title`, không bao giờ ra thông báo
trống. Ô toast `SAVED` tự tắt sau 8 s; breadcrumb Drive tự thu ngắn chừa chỗ.

## 6. Nguồn dữ liệu Drive

- Có API key: `files.list?q='id' in parents` (25 item/trang, field tối thiểu
  `id,name,mimeType,size`), stream qua `uc?export=download`.
- Không key (thư mục công khai): `list_folder_public()` parse trang embed
  (giới hạn 4 MB HTML, tối đa 500 entry).
- Lỗi mạng/list được phân loại hiển thị (`Drive network: …`, `Drive HTTP …`,
  `offline`) — xem `_drive_friendly_error()`; list lỗi không treo máy.
- Danh sách thư mục được cache đĩa (`drive-cache.json`) để mở lại khi
  offline; `forget_folder()` + Drive Refresh xóa cache.
- Slot Drive 1–N (`drive_slots`, `drive_slot` trong settings): nhiều thư mục
  gốc, đổi slot trong DRIVE view. Link Drive riêng chỉ lưu local
  (`settings.json`), bị redact khỏi mọi báo lỗi.
