# Logo khởi động NLK kiểu Netflix — cách làm và cách mang sang app khác

> File này ghi lại toàn bộ cách làm màn hình intro chữ NLK trong Music
> Player để tái sử dụng cho mọi app (chiaki-ng, Trimui-Terminal...).
> Cập nhật lần cuối: v1.17.0.

## 1. Nó là gì

Mỗi lần mở app, màn hình hiện nền đen, 3 chữ **N-L-K** màu đỏ Netflix
(`#E50914`) bật lên tuần tự từ dưới bay lên, chữ giãn dần ra, nảy nhẹ
khi chạm vị trí, có quầng đỏ dưới chữ, cuối cùng một tia sáng trắng
quét ngang qua rồi vào app chính. Tổng 2.2 giây, bấm phím bất kỳ để bỏ
qua. Tắt hẳn được ở Quick Menu → `Intro: Off` (lưu vào settings).

## 2. Timeline hiệu ứng (progress 0.0 → 1.0)

| Progress | Việc gì xảy ra |
|---|---|
| 0.05 / 0.21 / 0.37 | Chữ N / L / K bắt đầu bay lên (mỗi chữ lệch nhau 0.16) |
| 0.00 → 0.55 | Khoảng cách chữ giãn từ hẹp ra rộng (ease-out) |
| khi chạm vị trí | Nảy lên một nhịp nhỏ (overshoot hình sin) rồi đứng yên |
| 0.50 trở đi (mỗi chữ) | Đổi từ đỏ sẫm sang đỏ tươi + hiện quầng đỏ lệch dưới chữ |
| 0.72 → 1.00 | Tia sáng trắng quét lần lượt N → L → K |
| bất kỳ lúc nào | Có phím bấm → dừng intro, vào app ngay |

## 3. Kiến trúc trong Music Player

File duy nhất: `files/musicplayer/ui.py`. Hằng số màu:

```python
INTRO_BG = (8, 8, 12, 255)      # nền gần đen
INTRO_RED = (229, 9, 20, 255)   # đỏ Netflix
```

Luồng chạy trong `run()`: `initialize()` → `_play_intro()` → vòng lặp
chính. Các hàm (đọc theo thứ tự này là hiểu hết):

1. `_play_intro()` — vòng lặp thời gian. Mỗi khung hình: hút event SDL
   (bấm phím là thoát), vẽ `_render_intro_frame(t)`, `SDL_Delay(16)`,
   `SDL_RenderPresent` nằm trong hàm vẽ. Kết thúc luôn gọi
   `_free_intro_glyphs()` để không rò texture.
2. `_build_intro_glyphs()` — **vẽ trước** mỗi chữ × 3 màu
   (sẫm/tươi/trắng) ở cỡ font `giant` (= `hero` × 3) **đúng một lần**,
   giữ texture trong dict. Lý do: vẽ chữ bằng SDL_ttf rất đắt, còn dán
   texture có sẵn (`SDL_RenderCopy`) thì rẻ — 60fps vẫn mượt trên chip
   yếu. Không có font/giant thì dict rỗng và hàm vẽ tự rớt về đường
   vẽ chữ thường (fallback, không crash).
3. `_render_intro_frame(progress, glyphs)` — vẽ nền, tính vị trí từng
   chữ theo `progress`, dán texture. `fit = min(1, (width-80)/total)`:
   màn hình nào cũng vừa, màn chuẩn thì `fit = 1` (đúng 3x).
4. `_render_intro_glyphs()` — chi tiết từng hiệu ứng: rise + overshoot,
   ngưỡng sáng/tối, quầng glow (dán bản sẫm lệch +3/+6), tia sweep.
5. `_intro_spread()` / `_intro_letter_layout()` — toán vị trí chữ.

Điểm mấu chốt để giữ 60fps: **trong vòng lặp chỉ làm toán vị trí +
dán texture, tuyệt đối không gọi `TTF_Render*`, không mở file, không
log francesco mỗi frame.**

## 4. Núm chỉnh (muốn khác thì sửa đúng chỗ này)

| Muốn gì | Sửa ở đâu |
|---|---|
| Chữ khác (VD: CHIAKI) | Vòng lặp `for letter in "NLK"` trong `_build_intro_glyphs` và `_render_intro_glyphs` (2 chỗ) |
| To/nhỏ hơn | Cỡ font `"giant"` trong `_load_fonts` (hiện 132 ≈ hero × 3) |
| Nhanh/chậm | `duration = 2.2` trong `_play_intro` |
| Màu thương hiệu | `INTRO_RED`, `INTRO_BG`, màu `"dark"` trong `_build_intro_glyphs` |
| Thứ tự/tốc độ bay | `enter_at = 0.05 + index * 0.16`, chia `/ 0.30` |
| Độ giãn chữ | `_intro_spread`: `4 → 30`, ngưỡng `progress / 0.55` |
| Độ nảy | `rise 90`, `-14 * sin(...)` sau `local > 0.65` |
| Tia sáng | Ngưỡng `progress > 0.72`, cửa sổ `/ 0.28`, độ rộng `0.18` |

## 5. Mang sang app Python + SDL_ttf khác (VD: chiaki-ng)

Điều kiện: app đã có 3 thao tác cơ bản — tô chữ nhật, vẽ chữ TTF lên
màn hình, đưa khung hình lên màn hình (`Present`/`flip`). Chiaki-ng
đủ cả ba (Python + SDL2/SDL_ttf trong firmware).

Các bước:

1. Copy ý tưởng, không cần copy code: vòng lặp thời gian 2.2s đặt
   ngay sau khi tạo window/renderer/font, trước vòng lặp chính.
2. Thêm 1 cỡ font gấp 3 hiện tại (copy đúng 1 dòng load font).
3. Trước vòng lặp intro: vẽ trước mỗi chữ × 3 màu thành texture, giữ
   trong dict (copy `_build_intro_glyphs`, đổi chuỗi chữ và màu).
4. Trong vòng lặp: tính vị trí theo `progress` (copy công thức rise /
   spread / sweep, giữ nguyên số cũng đẹp), chỉ dán texture, rồi
   Present. Hút event để bấm phím là thoát.
5. Cuối intro (kể cả bị bỏ qua): hủy hết texture đã tạo.
6. Thêm setting `intro: True` + một mục tắt trong menu của app đó.

Test không cần máy thật: mock runtime/renderer như
`tests/test_core.py::test_intro_giant_glyphs_blits_scaled_letters`
(kiểm tra có dán texture, có Present), và test fallback khi thiếu
font (không crash).

## 6. Mang sang app shell script (VD: Trimui-Terminal)

App shell không có vòng lặp vẽ — làm theo cách "chiếu ảnh":

1. Trên PC, render sẵn vài khung hình (hoặc 1 ảnh tĩnh) bằng Pillow:
   nền đen + chữ đỏ to, xuất PNG đúng độ phân giải màn hình
   (VD 1024×768). Muốn có động thì render 6–10 frame chữ dịch dần.
2. Chép PNG vào `files/assets/` của app đó.
3. Trong `launch.sh`, trước khi chạy chương trình chính, chiếu ảnh
   bằng trình xem framebuffer có sẵn trên firmware (thử lần lượt
   `fim`, `fbv`, `fbi`; cái nào có thì dùng, không có thì bỏ qua
   êm — intro là trang trí, không được làm hỏng khởi động):

   ```sh
   if command -v fim >/dev/null 2>&1; then
     fim -q -a "$APP/assets/intro.png" >/dev/null 2>&1 &
     FIM_PID=$!
     sleep 1
     kill "$FIM_PID" 2>/dev/null || true
   fi
   ```

4. Muốn bấm phím để bỏ qua thì phức tạp hơn nhiều (cần đọc input thô
   song song) — với app shell, chấp nhận intro tĩnh ~1 giây cho đơn
   giản và chắc chắn.

## 7. Checklist trước khi release intro ở app bất kỳ

- [ ] Thiếu `Present` là màn hình đen thui dù đã vẽ (bug thật từng gặp
      ở v1.8.0, sửa ở v1.8.1) — test phải assert có Present.
- [ ] Hủy texture sau intro, không rò mỗi lần mở app.
- [ ] Font giant tốn RAM theo cấp số nhân diện tích chữ — chỉ vẽ đúng
      số chữ cần, đúng một lần.
- [ ] Chữ quá khổ màn hình nhỏ → luôn có cơ chế co vừa (như `fit`).
- [ ] Bấm phím bất kỳ là thoát ngay, kể cả khi đang tải font.
- [ ] Tắt được bằng setting, mặc định bật.
- [ ] Không log, không đọc file, không mạng trong vòng lặp intro.
- [ ] Tăng version app, không retag bản đã phát hành.

## 8. Lịch sử trong Music Player

- v1.8.0: intro NLK đầu tiên (vẽ chữ trực tiếp, cỡ hero).
- v1.8.1: sửa lỗi quên `SDL_RenderPresent` (intro không hiện).
- v1.8.2+: giữ nguyên.
- v1.17.0: chữ to gấp 3 (font `giant` + pre-render texture + co vừa
  màn hình), thêm giãn chữ, nảy overshoot, quầng đỏ, giữ toàn bộ
  hiệu ứng cũ (bay lên tuần tự, đổi màu, tia sweep, bỏ qua).
