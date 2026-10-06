#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tao GitHub Release vX.Y.Z cho trimui-music-player + upload ZIP/sha256/manifest.

Version doc tu files/musicplayer/__init__.py (APP_VERSION), dung chung voi
tools/make_release.py nen release luon khop manifest.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "nlkcodenew/Music-Player"
API = "https://api.github.com"


def version():
    path = os.path.join(ROOT, "files", "musicplayer", "__init__.py")
    with open(path, encoding="utf-8") as handle:
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', handle.read())
    if not match:
        raise SystemExit("APP_VERSION not found")
    return match.group(1)


def token():
    process = subprocess.run(
        ["git", "credential", "fill"], input="url=https://github.com\n\n",
        capture_output=True, text=True, cwd=ROOT,
    )
    for line in (process.stdout or "").splitlines():
        if line.startswith("password="):
            return line[len("password="):].strip()
    return ""


def api(method, path, tok, data=None, ctype="application/json"):
    url = API + path if path.startswith("/") else path
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + tok,
        "Accept": "application/vnd.github+json",
        "Content-Type": ctype,
        "User-Agent": "trimui-music-player-release",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode() or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(raw or "{}")
        except Exception:
            return error.code, {"raw": raw[:500]}


def upload_asset(tok, upload_url, fpath, ctype):
    name = os.path.basename(fpath)
    url = upload_url.split("{")[0] + "?name=" + urllib.request.quote(name)
    with open(fpath, "rb") as handle:
        data = handle.read()
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + tok,
        "Content-Type": ctype,
        "Content-Length": str(len(data)),
        "User-Agent": "trimui-music-player-release",
    })
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        return error.code, {"raw": error.read().decode(errors="replace")[:500]}


def main():
    ver = version()
    tag = "v" + ver
    tok = token()
    if not tok:
        print("FAIL: khong lay duoc github token tu credential manager")
        return 1
    dist = os.path.join(ROOT, "dist")
    archive = os.path.join(dist, "trimui-music-player-%s-universal.zip" % tag)
    assets = [(archive, "application/zip"), (archive + ".sha256", "text/plain")]
    assets.append((os.path.join(dist, "ota-manifest.json"), "application/json"))
    assets.append((os.path.join(ROOT, "manifest.json"), "application/json"))
    for fpath, _ in assets:
        if not os.path.isfile(fpath):
            print("FAIL: thieu file " + fpath)
            return 1
    notes = "Music Player cho TrimUI Brick Pro / Smart Pro S."
    readme = os.path.join(ROOT, "README.md")
    if os.path.isfile(readme):
        with open(readme, encoding="utf-8") as handle:
            notes = handle.read().strip()[:3000]
    status, release = api("GET", "/repos/%s/releases/tags/%s" % (REPO, tag), tok)
    if status == 200:
        print("release da ton tai id=%s -> xoa asset cu + upload lai" % release.get("id"))
        for asset in release.get("assets", []):
            api("DELETE", "/repos/%s/releases/assets/%s" % (REPO, asset["id"]), tok)
    else:
        status, release = api("POST", "/repos/%s/releases" % REPO, tok, {
            "tag_name": tag, "name": "trimui-music-player " + tag,
            "body": notes, "draft": False, "prerelease": False,
        })
        if status not in (200, 201):
            print("FAIL tao release: %s %s" % (status, release))
            return 1
        print("created release id=%s" % release["id"])
    upload_url = release.get("upload_url", "")
    if "{" not in str(upload_url):
        status, fresh = api("GET", "/repos/%s/releases/tags/%s" % (REPO, tag), tok)
        upload_url = fresh.get("upload_url", upload_url)
    ok = True
    seen = set()
    for fpath, ctype in assets:
        name = os.path.basename(fpath)
        if name in seen:
            continue
        seen.add(name)
        status, result = upload_asset(tok, upload_url, fpath, ctype)
        print(("PASS " if status in (200, 201) else "FAIL ") + name + " -> " + str(status))
        ok = ok and status in (200, 201)
    print("RELEASE OK: https://github.com/%s/releases/tag/%s" % (REPO, tag) if ok
          else "RELEASE UPLOAD LOI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
