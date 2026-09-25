# New-session handoff — Music Player v1.3.1

> Updated 2026-09-25. Read this file and `docs/PROJECT_STATUS.md` first.

## Quick state

- Repo: `https://github.com/nlkcodenew/Music-Player`.
- Workspace: `E:\Trimiu Brick Pro\Project APPS\Music-Player`.
- Branch: `main`.
- Latest release: `v1.3.1`.
- Feature commit/tag: `91bf9b7` / `v1.3.1`.
- Release: `https://github.com/nlkcodenew/Music-Player/releases/tag/v1.3.1`.
- 48/48 tests passed; both ZIPs verified with 31 entries and 31 OTA files.
- Stock SHA-256:
  `90888d006abae099e54ff9a89888f0de52db100dec4b96d15cc450281b8a4f19`.
- Spruce SHA-256:
  `39d6f295ecc0416fa7a0a91d5eec371598b602fc4dc73f06e883d8487aad70e7`.

## What v1.3.1 changed

1. The header now shows a stable `MP-xxxxxxxx` device ID beside the version.
2. The same ID is included in the GitHub Issue title and body.
3. Direct GitHub API/token use was removed from the app.
4. Reports now use a credential-free HTTPS Cloudflare Worker relay.
5. `Auto-report Errors` was added to Quick Menu and defaults to off.
6. Manual `Send Diagnostic` still sends immediately and snapshots the full
   current-session log; long logs continue in Issue comments.
7. Release verifier rejects token markers and invalid relay URLs.

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
Latest is v1.3.1 with stable MP-xxxxxxxx header ID and a credential-free HTTPS
Issue relay. Auto-reporting defaults off. Do not place GitHub tokens or the
private diagnostics repo in the app, manifest or ZIP, and do not overwrite user
data during OTA.
```
