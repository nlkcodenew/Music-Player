# New-session handoff — Music Player v1.6.3 (Buoc A done, next: Buoc B Drive)

> Updated 2026-10-02. Read this file, `docs/PROJECT_STATUS.md` and
> `docs/STEP_A_DONE.md` first. Buoc B plan lives in
> `docs/VISUALS_AND_DRIVE_PLAN.md` section 5 (Buoc B).

## Quick state

- Repo: `https://github.com/nlkcodenew/Music-Player`.
- Workspace: `E:\Trimiu Brick Pro\Project APPS\Music-Player`.
- Branch: `main` (clean, pushed; latest commit `70bf487`, docs commit on top).
- Latest release: `v1.6.3`.
- Feature commit/tag: `70bf487` / `v1.6.3`.
- Release: `https://github.com/nlkcodenew/Music-Player/releases/tag/v1.6.3`.
- 82/82 tests passed; both ZIPs verified with 34 entries and 34 OTA files.
- Stock SHA-256: `156ab7840aa978b6db1e63d28657295bf700e890770b969ff324425af178cfb1`.
- Spruce SHA-256: `048d5a617e2b0a3395655ec5393f5a39cedf28b44183aa4d446c7a8bc1e5f624`.

## What v1.3.2 changed

1. The header now shows a stable `MP-xxxxxxxx` device ID beside the version.
2. The same ID is included in the GitHub Issue title and body.
3. Direct GitHub API/token use was removed from the app.
4. Reports now use a credential-free HTTPS Cloudflare Worker relay.
5. `Auto-report Errors` was added to Quick Menu and defaults to off.
6. Manual `Send Diagnostic` still sends immediately and snapshots the full
   current-session log; long logs continue in Issue comments.
7. Release verifier rejects token markers and invalid relay URLs.
8. Spruce SmartProS now loads SDL2/SDL2_ttf from Spruce's native bind path
   before any `dll-mali` fallback, preventing the `mali-fbdev` startup crash.
9. Runtime diagnostics now record the selected SDL library paths and
   `PYSDL2_DLL_PATH` for future firmware compatibility reports.

## Production relay

- Endpoint:
  `https://trimui-music-player-issue-relay.issue-relay.workers.dev/report`.
- Worker source: `deploy/issue-relay/worker.js`.
- Local deployment config: `deploy/issue-relay/wrangler.toml` (gitignored).
- Public config example: `deploy/issue-relay/wrangler.toml.example`.
- Private destination: `nlkcodenew/trimui-music-player-diagnostics`.
- Token exists only as Worker secret. Do not read, print, commit or package it.
- E2E Issue `#1` verified Issue creation, one comment and dedupe; it is closed.

## Files to understand first

- `files/musicplayer/identity.py`: stable install ID and safe model label.
- `files/musicplayer/reporter.py`: sanitize, queue, relay upload and consent.
- `files/musicplayer/ui.py`: header ID, manual report and opt-in toggle.
- `files/reporting.json`: public HTTPS endpoint only.
- `tools/verify_release.py`: package/privacy checks.
- `deploy/issue-relay/worker.js`: server validation, sanitizing, rate limit,
  dedupe and GitHub Issue/comment creation.

## Rules for future work

1. Never restore `secrets.json` or a GitHub token in the client.
2. Never expose the private diagnostics repo in app files or relay responses.
3. Keep automatic upload disabled by default.
4. Keep user data and runtime files excluded from OTA and ZIP packages.
5. Increase the app version for any payload change; never retag a published
   release.
6. After release, download all assets from `releases/latest` and verify hashes,
   manifest version and entry counts.

## Useful commands

```powershell
Set-Location 'E:\Trimiu Brick Pro\Project APPS\Music-Player'
git status --short --branch
python -m compileall -q files tools tests
python -m unittest discover -s tests -v
node --check deploy/issue-relay/worker.js
python tools/make_release.py
python tools/verify_release.py
git diff --check
```

## Suggested continuation prompt (Buoc B — Google Drive)

```text
Continue E:\Trimiu Brick Pro\Project APPS\Music-Player.
Read docs/NEW_SESSION_HANDOFF.md, docs/PROJECT_STATUS.md, docs/STEP_A_DONE.md
and docs/VISUALS_AND_DRIVE_PLAN.md section 5 (Buoc B) first.
Latest is v1.6.3, main is clean and pushed. Buoc A is closed — do not touch
visuals/LED/UI unless Buoc B requires it.
Task: implement Buoc B Drive — public folder 1KB8-kxt0QSpgBSQw4VMIQmYCGS3F2D2a
(Anyone with link - Viewer). New module drive.py with paged folder browsing
(small pageSize, files.list q=parents, minimal fields, audio only), disk cache,
per-track streaming via uc?export=download without full scan (RAM-safe), plus
download-to-Music/Drive/<Album> for offline. DRIVE library screen, folder link
in settings via urllib + verified SSL, no tokens. Confirm with user whether to
use a public API key or keyless download endpoints before coding. Standard gate:
compileall, unittest, node --check, make_release, verify_release, git diff
--check. Bump version, never retag. No GitHub tokens or private repo names in
app/manifest/ZIP.
```
