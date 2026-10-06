import os

from .library import natural_key
from .settings import atomic_json_write


class Collections:
    def __init__(self, path):
        self.path = path
        self.favorite_tracks = set()
        self.favorite_playlists = set()
        # Playlist tu tao: {ten -> [duong dan tuyet doi]}. Giu thu tu them
        # vao de phat dung thu tu nguoi dung sap xep; ten khong trung voi
        # ten thu muc nhac (folder playlist) de UI phan biet duoc.
        self.custom_playlists = {}

    def load(self):
        try:
            import json
            with open(self.path, "r", encoding="utf-8") as handle:
                values = json.load(handle)
        except (OSError, ValueError, TypeError):
            return self
        if isinstance(values, dict):
            self.favorite_tracks = {
                str(path) for path in values.get("favorite_tracks", []) if path
            }
            self.favorite_playlists = {
                str(name) for name in values.get("favorite_playlists", []) if name
            }
            raw = values.get("custom_playlists", values.get("playlists", {}))
            cleaned = {}
            if isinstance(raw, dict):
                for name, items in raw.items():
                    label = str(name or "").strip()[:48]
                    if not label or not isinstance(items, list):
                        continue
                    paths = []
                    for item in items:
                        text = str(item or "").strip()
                        if not text or text.startswith("drive://"):
                            continue
                        absolute = os.path.abspath(text)
                        if absolute not in paths:
                            paths.append(absolute)
                    cleaned[label] = paths[:2000]
            self.custom_playlists = cleaned
        return self

    def save(self):
        atomic_json_write(self.path, {
            "favorite_tracks": sorted(self.favorite_tracks, key=natural_key),
            "favorite_playlists": sorted(self.favorite_playlists, key=natural_key),
            "custom_playlists": {
                name: list(paths)
                for name, paths in sorted(self.custom_playlists.items())
            },
        })

    def toggle_track(self, path):
        return self._toggle(self.favorite_tracks, os.path.abspath(path))

    def toggle_playlist(self, name):
        return self._toggle(self.favorite_playlists, str(name))

    def is_track_favorite(self, path):
        return os.path.abspath(path) in self.favorite_tracks

    def is_playlist_favorite(self, name):
        return str(name) in self.favorite_playlists

    def playlists(self, tracks, favorites_only=False):
        names = {track.folder for track in tracks if track.folder != "Music"}
        if favorites_only:
            names &= self.favorite_playlists
        return sorted(names, key=natural_key)

    def custom_names(self):
        """Ten playlist tu tao (da sap xep)."""
        return sorted(self.custom_playlists.keys(), key=natural_key)

    def is_custom_playlist(self, name):
        return str(name) in self.custom_playlists

    def combined_playlists(self, tracks, favorites_only=False):
        """Playlist tu tao (uu tien truoc) + playlist thu muc.

        Tay cam kho go ten nen playlist tu tao co ten san "Playlist N";
        hien truoc de de tim, playlist thu muc (tu folder nhac) hien sau.
        """
        custom = self.custom_names()
        folders = self.playlists(tracks)
        # Ten trung nhau (hiem): uu tien ban tu tao, bo ban folder trung.
        folder_only = [name for name in folders if name not in self.custom_playlists]
        merged = custom + folder_only
        if favorites_only:
            merged = [name for name in merged if name in self.favorite_playlists]
        return merged

    def next_playlist_name(self, base="Playlist"):
        taken = set(self.custom_playlists.keys())
        number = 1
        while True:
            candidate = "%s %d" % (base, number)
            if candidate not in taken:
                return candidate
            number += 1

    def create_playlist(self, name=""):
        """Tao playlist rong, tra ve ten that (tu sinh neu trung/rong)."""
        label = str(name or "").strip()[:48]
        if not label or label in self.custom_playlists:
            label = self.next_playlist_name(
                (label.rsplit(" ", 1)[0] if label else "Playlist") or "Playlist"
            )
            while label in self.custom_playlists:
                label = self.next_playlist_name()
        self.custom_playlists[label] = []
        return label

    def delete_playlist(self, name):
        """Xoa playlist tu tao; tra True neu co xoa."""
        label = str(name)
        if label not in self.custom_playlists:
            return False
        del self.custom_playlists[label]
        self.favorite_playlists.discard(label)
        return True

    def add_to_playlist(self, name, track_path):
        """Them bai vao playlist; tra (ten that, added?)."""
        label = str(name or "").strip()
        if not label:
            label = self.next_playlist_name()
        if label not in self.custom_playlists:
            # Khong tu tao playlist moi tu ten la: ten thu muc nhac co the
            # trung ten playlist nen chi them vao playlist tu tao da co,
            # hoac tao moi khi ten con trong.
            self.custom_playlists[label] = []
        text = str(track_path or "").strip()
        if not text or text.startswith("drive://"):
            return label, False
        absolute = os.path.abspath(text)
        items = self.custom_playlists[label]
        if absolute in items:
            return label, False
        if len(items) >= 2000:
            return label, False
        items.append(absolute)
        return label, True

    def remove_from_playlist(self, name, track_path):
        label = str(name)
        items = self.custom_playlists.get(label)
        if not items:
            return False
        try:
            items.remove(os.path.abspath(str(track_path)))
            return True
        except ValueError:
            return False

    def playlist_track_count(self, name, tracks):
        if self.is_custom_playlist(name):
            return len(self.custom_playlists.get(str(name), []))
        return len([track for track in tracks if track.folder == name])

    def custom_tracks(self, name, tracks):
        """Track trong playlist tu tao, giu dung thu tu them vao."""
        items = self.custom_playlists.get(str(name), [])
        by_path = {}
        for track in tracks or []:
            key = os.path.abspath(getattr(track, "path", ""))
            if key and key not in by_path:
                by_path[key] = track
        return [by_path[path] for path in items if path in by_path]

    @staticmethod
    def _toggle(values, item):
        if item in values:
            values.remove(item)
            return False
        values.add(item)
        return True
