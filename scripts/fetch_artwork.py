"""Cache public Spotify oEmbed thumbnails for the most popular corpus albums.

Optional asset preparation, never part of an online search request. No API key.
"""
import concurrent.futures
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_ir.data import ROOT, load_docs


def main():
    target = ROOT / "frontend" / "public" / "artwork"
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / "index.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    albums = {}
    for doc in sorted(load_docs(), key=lambda d: -(d.get("track_popularity") or 0)):
        if doc.get("track_album_id"):
            albums.setdefault(doc["track_album_id"], doc)
        if len(albums) == 48:
            break

    def fetch(item):
        album_id, doc = item
        path = target / (album_id + ".jpg")
        if path.exists():
            return album_id, previous.get(album_id, {"path": "/artwork/" + path.name, "track_id": doc["track_id"]})
        try:
            url = "https://open.spotify.com/oembed?" + urlencode({"url": "https://open.spotify.com/track/" + doc["track_id"]})
            with urlopen(Request(url, headers={"User-Agent": "MusicIR-local-demo/1.0"}), timeout=20) as response:
                meta = json.load(response)
            with urlopen(meta["thumbnail_url"], timeout=20) as response:
                path.write_bytes(response.read())
            return album_id, {"path": "/artwork/" + path.name, "track_id": doc["track_id"],
                              "source": meta["thumbnail_url"], "provider": "Spotify oEmbed"}
        except Exception as exc:
            print(f"Artwork {album_id}: {type(exc).__name__}", flush=True)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        result = dict(item for item in pool.map(fetch, albums.items()) if item)
    result = {**previous, **result}
    manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    (ROOT / "frontend" / "src" / "artwork.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{len(result)} album artworks cached.", flush=True)


if __name__ == "__main__":
    main()
