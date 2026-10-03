# HƯỚNG DẪN SỬ DỤNG — Music Player v1.20.1

> Dành cho người dùng cuối trên TrimUI Brick Pro (Stock OS) và Smart Pro S
> (Spruce OS). Tài liệu kỹ thuật cho dev nằm ở `DRIVE_OFFLINE.md`,
> `DEVELOPMENT.md`, `CHANGELOG.md`.

## 1. Cài đặt

1. Vào trang Release, tải **đúng 1 file** theo máy:
   - Stock OS: `trimui-music-player-vX.Y.Z-stock.zip`
   - Spruce OS: `trimui-music-player-vX.Y.Z-spruce.zip`
2. Giải nén thẳng ra **gốc thẻ nhớ**. Không copy file lẻ sang thư mục khác.
3. Stock OS sẽ có `/Apps/MusicPlayer/`, Spruce OS có `/App/MusicPlayer/`.
4. Chép nhạc vào thư mục `Music/` ở gốc thẻ (hoặc `Media/Music`,
   `Roms/MUSIC`, `ROMS/MUSIC` — app tự tìm thư mục đầu tiên tồn tại).

Mở app từ menu máy. Lần đầu sẽ hiện logo **NLK** ~2 giây (bấm phím bất kỳ
để bỏ qua; tắt hẳn trong Quick Menu → Intro).

## 2. Các màn hình

| Màn hình | Vào bằng | Ghi chú |
|---|---|---|
| ALL SONGS | Mặc định khi mở | Toàn bộ nhạc trên thẻ |
| FAVORITE SONGS | Y trong Library | Bài đã bấm X đánh dấu |
| PLAYLISTS | Y trong Library | Mỗi thư mục con của `Music` là 1 playlist |
| MUSIC (nguồn phát) | Y trong Library | Chọn LOCAL / DRIVE / + Add Drive |
| DRIVE | MUSIC → DRIVE | Duyệt thư mục Google Drive |
| NOW PLAYING | Start / A vào bài | Thanh phát, phổ nhạc, lời |
| LYRICS | Quick Menu → Lyrics | Lời đồng bộ, X đổi bản dịch |
| ADD DRIVE | MUSIC → + Add Drive | QR để link Drive riêng từ điện thoại |

## 3. Phím bấm

- **D-pad lên/xuống**: di chuyển. **Trái/phải**: tua khi đang phát.
- **A**: mở thư mục / phát / tạm dừng.
- **B**: quay lại. Đang tải thì **hủy tải**. Ở Library thì mở xác nhận thoát.
- **L1/R1**: bài trước / bài kế.
- **L2/R2**: bật-tắt shuffle / đổi repeat (off → all → one), dùng ở mọi màn hình.
- **X trong danh sách Drive**: tải bài về máy (chạy nền, % hiện ngay trong dòng).
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

Bài đã lưu nằm ở `Music/Drive/<Tên thư mục>/` và tự xuất hiện trong LOCAL
sau khi app quét lại thư viện.

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
