import os

from .library import natural_key
from .settings import atomic_json_write


class Collections:
    def __init__(self, path):
        self.path = path
        self.favorite_tracks = set()
        self.favorite_playlists = set()

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
        return self

    def save(self):
        atomic_json_write(self.path, {
            "favorite_tracks": sorted(self.favorite_tracks, key=natural_key),
            "favorite_playlists": sorted(self.favorite_playlists, key=natural_key),
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

    @staticmethod
    def _toggle(values, item):
        if item in values:
            values.remove(item)
            return False
        values.add(item)
        return True
