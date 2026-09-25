# Music Player GitHub Issue relay

Relay nhận log đã lọc từ app và tạo Issue trong repo chẩn đoán private. GitHub
token chỉ được lưu bằng Cloudflare Worker secret; app, manifest và ZIP không có
credential hoặc tên repo nhận log.

## Triển khai

1. Tạo repo private `nlkcodenew/trimui-music-player-diagnostics`.
2. Tạo fine-grained token chỉ cấp **Issues: Read and write** cho repo đó.
3. Tạo KV, copy `wrangler.toml.example` thành `wrangler.toml` và điền KV ID.
4. Lưu token và deploy:

   ```sh
   npx wrangler secret put GITHUB_TOKEN
   npx wrangler deploy
   ```

Client dùng endpoint HTTPS trong `files/reporting.json`. Worker giới hạn kích
thước, rate-limit theo IP băm, lọc lại token/path/IP/MAC và dedupe Issue cùng
từng phần comment trong 30 ngày. Endpoint không trả URL hay tên repo private.

Không commit `wrangler.toml`, `.wrangler/` hoặc token. Nếu token lộ, revoke rồi
đặt lại Worker secret; không cần phát hành lại app.

## Deployment hiện tại

- Worker: `trimui-music-player-issue-relay`.
- Endpoint: `https://trimui-music-player-issue-relay.issue-relay.workers.dev/report`.
- Repo nhận log: `nlkcodenew/trimui-music-player-diagnostics` (private).
- KV dedupe/rate-limit: `MUSIC_PLAYER_REPORTS`.
- E2E ngày 2026-09-25: tạo Issue `#1`, một comment log, dedupe đạt; Issue thử đã đóng.
