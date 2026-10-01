# Music Player — project status v1.6.2 (Buoc A done, xem `docs/STEP_A_DONE.md`)

> Updated 2026-10-02. Buoc A (visuals + LED + UI kieu Truepod) da close.
> Tiep theo: Buoc B Google Drive. `docs/NEW_SESSION_HANDOFF.md` van mo ta v1.3.2.

## Current release

| Item | Value |
|---|---|
| Latest release | `v1.6.2` |
| Feature commit/tag | `d327b2d` / `v1.6.2` |
| OTA files | 34 |
| Stock ZIP entries | 34 |
| Spruce ZIP entries | 34 |
| Unit tests | 76/76 passed |
| Stock ZIP SHA-256 | `e6a0a8c1c824828a412ac4dd754fa9e676b0b70059e155de3855491d3dc2d222` |
| Spruce ZIP SHA-256 | `50ada629b5c3648acb3af85a2e3a86097886edf4dde9320c1799b360b5a7c63b` |

The public release contains `ota-manifest.json`, two platform ZIPs and two
SHA-256 sidecars. The local release gate validates version, hashes, entry counts,
permissions, privacy exclusions and OTA safety before the tag is pushed.

## Platform packaging

- Stock OS installs under `Apps/MusicPlayer`.
- Spruce OS installs under `App/MusicPlayer`.
- Both packages contain the same 31 OTA payload files and bundled AArch64
  SDL2_mixer runtime.
- Settings, collections, identity, pending reports, logs and diagnostics are
  excluded from OTA and release ZIPs.

## Diagnostics and device identity

`v1.3.2` displays `v1.3.2 | ID: MP-xxxxxxxx` in the header. The stable ID is
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

## Spruce SDL compatibility

Spruce `SmartProS` exposes its compatible SDL2 and SDL2_ttf libraries through
`spruce/brick/sdl2`, which is populated by Spruce's bind script from `/usr/lib`.
The launcher now places that directory and the system libraries ahead of
`App/PyUI/dll-mali`. The latter requires the unavailable Mali fbdev ION device
on this firmware and caused the pre-`v1.3.2` startup crash. The installed
`v1.3.2` payload was tested on Spruce with successful video initialization,
44.1 kHz audio playback, Bluetooth/system output, and clean exit.

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

- `v1.3.2` is the current OTA and GitHub latest release.
- `main`, `origin/main` and tag `v1.3.2` point to the tested Spruce SDL fix.
- Repo and public assets were clean and synchronized at the end of feature work.
- No known release, relay, test or packaging task remains open.
