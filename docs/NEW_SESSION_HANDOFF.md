# New-session handoff — Music Player v1.3.2

> Updated 2026-09-26. Read this file and `docs/PROJECT_STATUS.md` first.

## Quick state

- Repo: `https://github.com/nlkcodenew/Music-Player`.
- Workspace: `E:\Trimiu Brick Pro\Project APPS\Music-Player`.
- Branch: `main`.
- Latest release: `v1.3.2`.
- Feature commit/tag: `v1.3.2` release commit / `v1.3.2`.
- Release: `https://github.com/nlkcodenew/Music-Player/releases/tag/v1.3.2`.
- 49/49 tests passed; both ZIPs verified with 31 entries and 31 OTA files.
- Stock SHA-256: `0675ce83c712053be73b0435b2a9b468ed8a1688826e5a7d97c384086dcb3686`.
- Spruce SHA-256: `d08275bc9a5209deac5c67ba36e3e9ff67b25798c7d4eddb46c8f37e031802a3`.

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

## Suggested continuation prompt

```text
Continue E:\Trimiu Brick Pro\Project APPS\Music-Player.
Read docs/NEW_SESSION_HANDOFF.md and docs/PROJECT_STATUS.md first.
Latest is v1.3.2 with stable MP-xxxxxxxx header ID and a credential-free HTTPS
Issue relay. Auto-reporting defaults off. Do not place GitHub tokens or the
private diagnostics repo in the app, manifest or ZIP, and do not overwrite user
data during OTA.
```
