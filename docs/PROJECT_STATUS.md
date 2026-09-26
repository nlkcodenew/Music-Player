# Music Player — project status v1.3.2

> Updated 2026-09-26. Read `docs/NEW_SESSION_HANDOFF.md` before continuing.

## Current release

| Item | Value |
|---|---|
| Latest release | `v1.3.2` |
| Feature commit/tag | `v1.3.2` release commit / `v1.3.2` |
| OTA files | 31 |
| Stock ZIP entries | 31 |
| Spruce ZIP entries | 31 |
| Unit tests | 49/49 passed |
| Stock ZIP SHA-256 | `0675ce83c712053be73b0435b2a9b468ed8a1688826e5a7d97c384086dcb3686` |
| Spruce ZIP SHA-256 | `d08275bc9a5209deac5c67ba36e3e9ff67b25798c7d4eddb46c8f37e031802a3` |

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
