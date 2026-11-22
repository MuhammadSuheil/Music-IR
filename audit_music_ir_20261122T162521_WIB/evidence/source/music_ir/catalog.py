"""Public track metadata shared by catalog and retrieval responses."""

AUDIO_FIELDS = ("tempo", "energy", "valence", "danceability", "acousticness")


def track_summary(doc):
    return {
        "track_id": doc["track_id"], "title": doc["track_name"], "artist": doc["track_artist"],
        "album": doc.get("track_album_name", ""), "album_id": doc.get("track_album_id", ""),
        "duration_ms": doc.get("duration_ms"), "popularity": doc.get("track_popularity"),
        "release_date": doc.get("track_album_release_date", ""), "genres": doc.get("playlist_genre", []),
        "lyrics_available": doc["lyrics_available"],
        "spotify_url": "https://open.spotify.com/track/" + doc["track_id"],
        "audio": {field: doc.get(field) for field in AUDIO_FIELDS},
    }


def catalog(docs, limit=60, offset=0, genre=None):
    from collections import Counter
    counts = Counter(genre for doc in docs for genre in set(doc.get("playlist_genre", [])))
    selected = [d for d in docs if genre is None or genre in d.get("playlist_genre", [])]
    selected.sort(key=lambda d: (-(d.get("track_popularity") or 0), d["track_id"]))
    return {"tracks": [track_summary(d) for d in selected[offset:offset + limit]],
            "total": len(selected), "offset": offset, "limit": limit,
            "genres": [{"name": name, "count": count} for name, count in counts.most_common()]}
