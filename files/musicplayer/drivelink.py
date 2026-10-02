"""LAN web page for adding a personal Google Drive share.

Typing a long Drive link with a gamepad is painful, so the player shows
a QR code / URL (see :mod:`musicplayer.qrcode`) that opens this tiny
page on a phone sharing the same network. The phone pastes the Drive
link, hits save, and the TrimUI stores the new folder id and syncs the
folder listing right away.

The server binds the LAN only while the "add drive" screen is open and
is stopped as soon as the user leaves that screen. No auth token or
password is involved: only public "anyone with the link" folders are
accepted, and every submitted link is verified with a live listing
before it is saved.
"""

import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .drive import (
    extract_folder_id,
    forget_folder,
    list_folder_public,
    put_cached_folder,
)
from .logger import get_logger
from .settings import Settings

PORT = 8080
MAX_BODY_BYTES = 4096


def device_ips():
    """Best-effort list of this device's LAN IPv4 addresses."""
    found = []

    def add(address):
        if address and not address.startswith("127.") and address not in found:
            try:
                socket.inet_aton(address)
            except (OSError, ValueError):
                return
            found.append(address)

    try:
        import fcntl
        import struct
    except ImportError:
        fcntl = None
    if fcntl is not None:
        for interface in ("wlan0", "eth0", "usb0", "wlan1"):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    packed = fcntl.ioctl(
                        sock.fileno(), 0x8915,
                        struct.pack("256s", interface.encode("utf-8")[:15]),
                    )
                finally:
                    sock.close()
                add(socket.inet_ntoa(packed[20:24]))
            except OSError:
                pass
    try:
        add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return found


def lan_url(port):
    ips = device_ips()
    host = ips[0] if ips else "BRICK-IP"
    return "http://%s:%d/" % (host, port)


def submit_drive_link(paths, raw_url):
    """Validate ``raw_url``, save its folder id and sync the listing.

    Returns ``(ok, message, count)``. ``count`` is the number of items
    synced (0 when the save failed).
    """
    text = str(raw_url or "").strip()
    if len(text) > 500:
        return False, "Link is too long", 0
    folder_id = extract_folder_id(text)
    if not folder_id:
        return False, "Not a Drive folder link", 0
    try:
        entries, _token = list_folder_public(paths.app_dir, folder_id)
    except Exception as error:
        get_logger().warning("drive link validation failed: %s", error)
        return False, "Cannot open that share (check link and Wi-Fi)", 0
    try:
        previous = str(Settings(paths.settings_file).load().get("drive_folder_id") or "")
    except Exception:
        previous = ""
    settings = Settings(paths.settings_file).load()
    settings.set("drive_folder_id", folder_id)
    try:
        settings.save()
    except OSError as error:
        return False, "Cannot save settings: %s" % error, 0
    try:
        if previous and previous != folder_id:
            forget_folder(paths.data_dir, previous)
        put_cached_folder(paths.data_dir, folder_id, entries, "")
    except Exception as error:
        get_logger().warning("drive link cache sync failed: %s", error)
    message = "Saved! %d items synced - open DRIVE to browse" % len(entries)
    get_logger().info("drive link updated folder=%s items=%d", folder_id, len(entries))
    return True, message, len(entries)


def _form_page(current_folder, url):
    return """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Them Drive cho TrimUI</title>
<style>body{font-family:sans-serif;max-width:560px;margin:24px auto;padding:0 16px;background:#f1f5f9;color:#0f172a}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px #0002}
input{width:100%%;padding:12px;font-size:16px;border:2px solid #0ea5e9;border-radius:8px;box-sizing:border-box}
button{width:100%%;margin-top:12px;padding:12px;font-size:17px;background:#0ea5e9;color:#fff;border:0;border-radius:8px}
.note{color:#64748b;font-size:14px}.ok{color:#15803d}.err{color:#dc2626}</style>
</head><body><div class="card">
<h2>🎵 Them nhac tu Google Drive</h2>
<p class="note">Link hien tai: <b>%s</b></p>
<form method="post" action="/save">
<input name="drive_url" placeholder="Dan link Drive: drive.google.com/drive/folders/..." autocomplete="off">
<button type="submit">Luu link</button>
</form>
<p class="note">1. Tren Drive: Share thu muc nhac → Anyone with the link (Viewer)<br>
2. Copy link, dan vao o tren, bam Luu link<br>
3. Quay lai may TrimUI, mo DRIVE de nghe</p>
<p class="note">%s</p>
</div></body></html>
""" % (current_folder or "(chua co)", url)


def _result_page(ok, message, url):
    css = "ok" if ok else "err"
    return """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Them Drive cho TrimUI</title>
<style>body{font-family:sans-serif;max-width:560px;margin:24px auto;padding:0 16px;background:#f1f5f9;color:#0f172a}
.card{background:#fff;border-radius:12px;padding:20px}.%s{font-size:18px}</style>
</head><body><div class="card">
<p class="%s">%s</p>
<p><a href="/">Nhap link khac</a></p>
</div></body></html>
""" % (css, css, message)


class _LinkHandler(BaseHTTPRequestHandler):
    server_version = "TrimUI-DriveLink/1.0"

    def log_message(self, *args):
        pass

    def _current_folder(self):
        try:
            return str(Settings(self.server.drive_paths.settings_file).load().get(
                "drive_folder_id") or "")
        except Exception:
            return ""

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path != "/":
            self.send_error(404)
            return
        page = _form_page(self._current_folder(), self.server.drive_url).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/save":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_error(413)
            return
        try:
            body = self.rfile.read(length).decode("utf-8", "replace")
        except Exception:
            self.send_error(400)
            return
        fields = urllib.parse.parse_qs(body, keep_blank_values=True)
        raw_url = (fields.get("drive_url") or [""])[0]
        try:
            ok, message, _count = submit_drive_link(self.server.drive_paths, raw_url)
        except Exception as error:
            ok, message = False, "Error: %s" % error
        try:
            self.server.drive_result = {"ok": ok, "message": message}
        except Exception:
            pass
        page = _result_page(ok, message, self.server.drive_url).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


class DriveLinkServer(object):
    """Short-lived LAN server; poll ``result`` for submitted links."""

    def __init__(self, paths):
        self.paths = paths
        self.httpd = None
        self.thread = None
        self.url = ""
        self.result = None

    def start(self):
        self.stop()
        httpd = None
        bound_port = 0
        for port in (PORT, 0):
            try:
                httpd = ThreadingHTTPServer(("0.0.0.0", port), _LinkHandler)
                bound_port = httpd.server_address[1]
                break
            except OSError as error:
                get_logger().warning("drive link port %d busy: %s", port, error)
                httpd = None
        if httpd is None:
            return ""
        httpd.daemon_threads = True
        httpd.drive_paths = self.paths
        httpd.drive_url = ""
        httpd.drive_result = None
        self.httpd = httpd
        self.result = None
        self.url = lan_url(bound_port)
        httpd.drive_url = self.url
        self.thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
            name="drive-link-web", daemon=True,
        )
        self.thread.start()
        get_logger().info("drive link server started at %s", self.url)
        return self.url

    def poll(self):
        try:
            result = self.httpd.drive_result if self.httpd else None
        except Exception:
            return None
        if result is None:
            return None
        try:
            self.httpd.drive_result = None
        except Exception:
            pass
        return result

    def stop(self):
        httpd, self.httpd = self.httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        self.thread = None
        self.url = ""
