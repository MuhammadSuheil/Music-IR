import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from music_ir.api import app
from music_ir.engine import SearchEngine, load_config


class NoSemantic:
    ready = False


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"track_id": "a", "track_name": "Stay", "track_artist": "Alice", "lyrics": "stay with me",
             "lyrics_available": True, "track_album_name": "First", "track_album_id": "albumA",
             "track_popularity": 80, "duration_ms": 183000, "playlist_genre": ["pop", "pop"], "tempo": 120},
            {"track_id": "b", "track_name": "Goodbye", "track_artist": "Bob", "lyrics": "full lyrics",
             "lyrics_available": True, "track_popularity": 95, "playlist_genre": ["rock", "pop"]},
            {"track_id": "c", "track_name": "Other", "track_artist": "Carol", "lyrics": "",
             "lyrics_available": False, "track_popularity": None, "playlist_genre": ["rock"]},
        ]
        self.engine = SearchEngine(self.docs, load_config(), semantic=NoSemantic())

    def client(self):
        self.patcher = patch("music_ir.api.SearchEngine", return_value=self.engine)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        return TestClient(app)

    def test_catalog_is_paginated_sorted_and_excludes_full_lyrics(self):
        with self.client() as client:
            result = client.get("/catalog?limit=1&offset=1").json()
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["tracks"][0]["track_id"], "a")
            self.assertEqual(result["tracks"][0]["duration_ms"], 183000)
            self.assertEqual(result["tracks"][0]["album_id"], "albumA")
            self.assertNotIn("lyrics", result["tracks"][0])
            self.assertEqual(dict((g["name"], g["count"]) for g in result["genres"]), {"pop": 2, "rock": 2})
            self.assertEqual(client.get("/catalog?offset=100").json()["tracks"], [])

    def test_genre_filter_and_query_validation(self):
        with self.client() as client:
            result = client.get("/catalog?genre=rock").json()
            self.assertEqual(result["total"], 2)
            self.assertEqual([t["track_id"] for t in result["tracks"]], ["b", "c"])
            self.assertEqual(client.get("/catalog?genre=unknown").json()["tracks"], [])
            for params in ["limit=101", "limit=0", "offset=-1"]:
                self.assertEqual(client.get("/catalog?" + params).status_code, 422)

    def test_detail_returns_full_lyrics_and_missing_track_is_404(self):
        with self.client() as client:
            response = client.get("/tracks/a")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["lyrics"], "stay with me")
            self.assertEqual(response.json()["audio"]["tempo"], 120)
            self.assertEqual(client.get("/tracks/c").json()["lyrics"], "")
            self.assertEqual(client.get("/tracks/missing").status_code, 404)

    def test_search_and_catalog_share_track_metadata(self):
        with self.client() as client:
            search = client.post("/search", json={"query": "Stay", "mode": "E2"}).json()["results"][0]
            detail = client.get("/tracks/a").json()
            for field in ["track_id", "album_id", "duration_ms", "genres", "audio", "spotify_url"]:
                self.assertEqual(search[field], detail[field])
