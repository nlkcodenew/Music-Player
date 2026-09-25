# Music Player — project status v1.3.1

> Updated 2026-09-25. Read `docs/NEW_SESSION_HANDOFF.md` before continuing.

## Current release

| Item | Value |
|---|---|
| Latest release | `v1.3.1` |
| Feature commit/tag | `91bf9b7` / `v1.3.1` |
| OTA files | 31 |
| Stock ZIP entries | 31 |
| Spruce ZIP entries | 31 |
| Unit tests | 48/48 passed |
| Stock ZIP SHA-256 | `90888d006abae099e54ff9a89888f0de52db100dec4b96d15cc450281b8a4f19` |
| Spruce ZIP SHA-256 | `39d6f295ecc0416fa7a0a91d5eec371598b602fc4dc73f06e883d8487aad70e7` |

GitHub Actions `Test` and `Release` completed successfully. The public release
contains `ota-manifest.json`, two platform ZIPs and two SHA-256 sidecars. Assets
downloaded through `releases/latest` matched version, hashes and entry counts.

## Platform packaging

- Stock OS installs under `Apps/MusicPlayer`.
- Spruce OS installs under `App/MusicPlayer`.
- Both packages contain the same 31 OTA payload files and bundled AArch64
  SDL2_mixer runtime.
- Settings, collections, identity, pending reports, logs and diagnostics are
  excluded from OTA and release ZIPs.

## Diagnostics and device identity

`v1.3.1` displays `v1.3.1 | ID: MP-xxxxxxxx` in the header. The stable ID is
stored in `data/identity.json` and appears unchanged in the matching Issue title
and body, allowing a user report to be correlated without exposing a raw serial
or MAC address.

Manual `Send Diagnostic` always represents explicit user consent and sends a
new report. Automatic crash and operational-error uploads are disabled by
default and can be enabled through `Select > Auto-report Errors`.

The client sends filtered logs only to:

```text
https://trimui-music-player-issue-relay.issue-relay.workers.dev/report
```

The client contains no GitHub token, Authorization header or private diagnostics
repo name. It validates a clean HTTPS relay URL and keeps failed reports queued.
Long session logs are split between the Issue body and bounded comments.

## Relay production state

- Worker: `trimui-music-player-issue-relay`.
- Repo: `nlkcodenew/trimui-music-player-diagnostics` (private).
- KV: `MUSIC_PLAYER_REPORTS` for rate limiting and 30-day dedupe.
- GitHub fine-grained token is stored only as Cloudflare Worker secret
  `GITHUB_TOKEN` and is scoped to Issues on the diagnostics repo.
- E2E on 2026-09-25 created Issue `#1`, added one log comment, deduplicated a
  repeated payload and then closed the test Issue.
- If the token must be rotated, update the Worker secret; no app release is
  required.

## Security and release gates

Do not weaken these constraints:

1. Keep TLS certificate and hostname verification enabled.
2. Never add a token, shared client secret or private repo name to app files.
3. Keep runtime/user data out of manifest and ZIP files.
4. Preserve explicit consent: automatic reporting defaults to off.
5. Keep verifier checks for credential markers and credential-free HTTPS relay.

Standard gate:

```powershell
python -m compileall -q files tools tests
python -m unittest discover -s tests -v
node --check deploy/issue-relay/worker.js
python tools/make_release.py
python tools/verify_release.py
git diff --check
```

## Session close

- `v1.3.1` is the current OTA and GitHub latest release.
- `main`, `origin/main` and tag `v1.3.1` pointed to `91bf9b7` before the docs
  summary commit.
- Repo and public assets were clean and synchronized at the end of feature work.
- No known release, relay, test or packaging task remains open.
