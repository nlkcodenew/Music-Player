# HƯỚNG DẪN SỬ DỤNG — Music Player v1.21.0

> Dành cho người dùng cuối trên TrimUI Brick Pro (Stock OS) và Smart Pro S
> (Spruce OS). Tài liệu kỹ thuật cho dev nằm ở `DRIVE_OFFLINE.md`,
> `DEVELOPMENT.md`, `CHANGELOG.md`.

## 1. Cài đặt

1. Vào trang Release, tải **một file duy nhất**:
   `trimui-music-player-vX.Y.Z-universal.zip` cho cả Stock OS và Spruce OS.
2. Giải nén thẳng ra **gốc thẻ nhớ**. Không copy file lẻ sang thư mục khác.
3. Stock OS sẽ có `/Apps/MusicPlayer/`, Spruce OS có `/App/MusicPlayer/`.
   Gói đã kèm Python 3.10 ARM64 và thư viện runtime, không cần cài Python,
   PortMaster hoặc phụ thuộc bản firmware để mở app.
4. Chép nhạc vào thư mục `Music/` ở gốc thẻ (hoặc `Media/Music`,
   `Roms/MUSIC`, `ROMS/MUSIC` — app tự tìm thư mục đầu tiên tồn tại).

Mở app từ menu máy. Lần đầu sẽ hiện logo **NLK** ~2 giây (bấm phím bất kỳ
để bỏ qua; tắt hẳn trong Quick Menu → Intro).

## 2. Các màn hình

| Màn hình | Vào bằng | Ghi chú |
|---|---|---|
| ALL SONGS | Mặc định khi mở | Toàn bộ nhạc trên thẻ |
| FAVORITE SONGS | Y trong Library | Bài đã bấm X đánh dấu |
| PLAYLISTS | Y trong Library | Playlist tự tạo (lên trước) + mỗi thư mục con của `Music` là 1 playlist |
| MUSIC (nguồn phát) | Y trong Library | Chọn LOCAL / DRIVE / + Add Drive |
| DRIVE | MUSIC → DRIVE | Duyệt thư mục Google Drive |
| NOW PLAYING | Start / A vào bài | Thanh phát, phổ nhạc, lời |
| LYRICS | Quick Menu → Lyrics | Lời đồng bộ, X đổi bản dịch |
| ADD DRIVE | MUSIC → + Add Drive | QR để link Drive riêng từ điện thoại |

## 3. Phím bấm

- **D-pad lên/xuống**: di chuyển. **Trái/phải**: tua khi đang phát.
- **A**: mở thư mục / phát / tạm dừng. **A** xác nhận hộp thoại.
- **B**: quay lại. Đang tải thì **hủy tải**. Ở Library thì mở xác nhận thoát.
  **B** hủy hộp thoại xác nhận.
- **L1/R1**: bài trước / bài kế.
- **L2/R2**: bật-tắt shuffle / đổi repeat (off → all → one), dùng ở mọi màn hình.
- **X trên bài Drive**: tải bài về máy (chạy nền, % hiện ngay trong dòng).
- **X trên thư mục Drive**: tải cả thư mục (chỉ file nằm trực tiếp, bỏ thư
  mục con; hiện dung lượng + dung lượng trống SD, A tải / B hủy).
- **X trên danh sách slot Drive 1–N**: xóa link Drive đó (hỏi xác nhận).
- **X ở chỗ khác**: thêm/bỏ yêu thích.
- **Y trong Library**: đổi chế độ xem. **Y khi đang phát**: lưu bài Drive đang
  phát về máy.
- **Start**: chuyển Library / Now Playing. **Select**: Quick Menu.

Dòng gợi ý dưới cùng màn hình luôn ghi đúng phím của màn hình đó.

## 4. Nghe nhạc từ Google Drive

Không cần API key với thư mục chia sẻ công khai ("Anyone with the link").

1. Library → bấm **Y** vài lần tới màn hình MUSIC → chọn **DRIVE**
   (hoặc slot Drive 1–N đã lưu).
2. Dùng A mở thư mục, B quay lại. Danh sách hiện tên bài, định dạng
   (MP3/FLAC…) và dung lượng.
3. Bấm **A** để phát ngay (bài được tải đệm về bộ nhớ đệm, màn hình vẫn hiện
   % và bấm B để hủy).
4. Bấm **X** để lưu bài về máy — % chạy **ngay trong dòng bài đó**, xong thì
   báo `Saved: <tên file đầy đủ kèm đuôi>`, ví dụ
   `Saved: 04. giac mo con mai - le quuyen [FLAC].flac`.
5. Bài nào đã có trên máy (kể cả nằm ở thư mục khác) sẽ có nhãn
   **ON DEVICE** — bấm X vào đó chỉ báo `Already saved: ...`, không tải lại.

Bài đã lưu nằm ở `Music/Drive/<Tên slot>/<Tên thư mục>/` (mỗi album 1 thư
mục con riêng, không đổ chung vào `Music/`) và tự xuất hiện trong LOCAL
sau khi app quét lại thư viện. Thông báo `Saved to Drive/...` ghi rõ thư
mục đích.

### Xóa link Drive hỏng

- Cách 1: ở màn hình DRIVE khi hiện danh sách slot Drive 1–N, chọn slot hỏng
  rồi bấm **X** → hộp xác nhận `Remove ...?` (A xóa, B giữ).
- Cách 2: đang mở DRIVE (kể cả khi list lỗi do link hỏng) → Quick Menu →
  **Remove This Drive** → xác nhận.
- Chỉ xóa slot + cache listing; nhạc đã tải trong `Music/Drive/` được giữ.
  Xóa slot cuối sẽ reset về Drive mặc định.

### Tải cả thư mục Drive

- Chọn thư mục trong DRIVE rồi bấm **X** (hoặc Quick Menu → Download This
  Folder khi đang mở thư mục đó).
- App chỉ lấy file nhạc nằm **trực tiếp** trong thư mục, **bỏ qua thư mục
  con**, rồi hiện: số bài, tổng dung lượng (~MB/GB hoặc `size unknown` khi
  Drive public không cho kích thước), dung lượng trống SD, thư mục đích
  `Music/Drive/<Slot>/<Folder>/`.
- Bấm **A** để tải nối tiếp từng bài (bài đã có ON DEVICE thì bỏ qua),
  **B** để hủy. Hết dung lượng SD thì báo `Not enough space` và không tải.
  Xong thì báo `Folder '...': N/N saved to ...` và quét lại thư viện một lần.

### Playlist tự tạo

- Tay cầm khó gõ tên nên playlist mới tự đặt `Playlist 1`, `Playlist 2`...
- Quick Menu → **Add to Playlist...** (khi đang phát hoặc đang chọn 1 bài
  local) → chọn playlist hoặc **New Playlist...**.
- Quick Menu → **New Playlist** tạo list rỗng.
- Màn hình PLAYLISTS hiện playlist tự tạo trước, playlist thư mục sau. A mở,
  X đánh dấu yêu thích như cũ.
- Trong playlist tự tạo: Quick Menu → **Remove This Song from Playlist** để
  bỏ bài, **Delete Playlist** để xóa list (file nhạc giữ nguyên).

### Thêm Drive của chính mình

MUSIC → **+ Add Drive** → màn hình hiện mã QR. Dùng điện thoại cùng Wi-Fi
quét QR, mở trang web hiện ra, dán link thư mục Drive → app tự nhận và mở
ngay. Link chỉ lưu trong `settings.json` trên máy, không gửi đi đâu.

### Khi mất mạng

Danh sách Drive dùng bản đệm đã tải trước đó; bài nào chưa đệm sẽ báo rõ
"offline" thay vì treo máy. Nút **Drive Refresh** trong Quick Menu tải lại.

## 5. Nghe offline, hẹn giờ, chạy nền

- **Lời bài hát**: đặt file `.lrc` cùng tên cạnh file nhạc
  (`Song.mp3` + `Song.lrc`; bản dịch: `Song.vi.lrc`). Mở Quick Menu → Lyrics,
  bấm X để đổi bản dịch.
- **Equalizer**: Quick Menu → Equalizer. Preset Flat/Bass Boost/Vocal/Rock/
  Pop/Classical/Jazz; chỉnh Bass/Mid/Treble ±6 dB sẽ thành Custom.
- **Ngõ ra âm thanh**: Quick Menu → Audio Output. `Auto` ưu tiên USB DAC nếu
  có, `System / Bluetooth` dùng loa/Bluetooth, `USB DAC` ép dùng DAC.
  Cắm DAC **trước** khi mở app.
- **Sleep Timer**: Quick Menu → Sleep Timer: Off / 15 / 30 / 45 / 60 / 90
  phút / hết bài.
- **Tắt màn hình vẫn phát**: Quick Menu → Screen-off Playback. Bấm phím bất
  kỳ để bật màn hình lại (không làm gì khác).
- **Chạy nền khi về OS**: đang phát → Quick Menu → Background Playback.
  Mở app lại để dừng service nền và nghe tiếp đúng vị trí cũ.
- **Báo lỗi**: Quick Menu → Send Diagnostic gửi 1 Issue riêng (có hỏi ý kiến;
  tự động gửi mặc định TẮT).

## 6. Cập nhật (OTA)

Quick Menu → Check Update (tự kiểm tra định kỳ nếu bật `auto_update`).
Bản mới tải về được kiểm SHA-256 rồi mới ghi đè từng file — nhạc, cài đặt,
yêu thích, log **không bao giờ bị xóa** khi cập nhật.

## 7. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Mở thư mục Drive bị văng ra | Đã sửa từ v1.19.1. Nếu còn gặp, gửi log (mục 8) |
| Tải bài đứng yên / không % | Kiểm tra Wi-Fi; B để hủy rồi X tải lại |
| Bài đã tải nhưng không thấy ON DEVICE | Bấm Drive Refresh; tên file trên Drive đổi khác hẳn tên đã lưu thì app coi là 2 bài |
| Không có tiếng | Quick Menu → Audio Output → System; rút DAC rồi mở lại app |
| App báo AUDIO OFF | Firmware chưa mở được audio — thoát app dùng audio khác rồi mở lại |
| Thẻ báo đầy | Quick Menu → Clear Drive cache (bộ đệm stream tối đa 1 GB, tự xóa cũ nhất) |

## 8. Lấy log gửi báo lỗi

File log nằm trong thư mục app đã cài:

- Stock: `/mnt/SDCARD/Apps/MusicPlayer/music-player.log`
- Spruce: `/mnt/SDCARD/App/MusicPlayer/music-player.log`

Cắm thẻ vào máy tính, copy file log gửi kèm mô tả thao tác trước khi lỗi.
Trong app cũng có thể bấm Quick Menu → Send Diagnostic để gửi trực tiếp.
