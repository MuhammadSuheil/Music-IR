# Local visual assets

- `artwork/*.jpg`: album thumbnails returned by public Spotify oEmbed for tracks already present in the user's corpus. Source URLs and track IDs are recorded in `artwork/index.json`. Album artwork belongs to its respective owners. Refresh the cache with `python scripts/fetch_artwork.py` from the project root.
- `fonts/dm-sans-latin.woff2`: DM Sans variable font, distributed by Google Fonts under the SIL Open Font License. Source: https://fonts.google.com/specimen/DM+Sans. License: https://github.com/google/fonts/blob/main/ofl/dmsans/OFL.txt.
- `favicon.svg`: original Music IR waveform mark.

Tracks without cached artwork display a generated CSS cover. No images or models are fetched during a search request. Spotify embeds connect to Spotify only when the listener opens the player.
