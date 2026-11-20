export type Track = {
  track_id: string; title: string; artist: string; album: string; album_id: string
  duration_ms: number | null; popularity: number | null; release_date: string; genres: string[]
  lyrics_available: boolean; spotify_url: string
  audio: Record<string, number | null>
  snippet?: string; snippet_type?: string; reasons?: string[]; score?: number
  theme_evidence?: { cosine: number; best_cosine: number; passages: number; text: string; source: string; method: string;
    ranking_cosine?: number; counter_cosine?: number | null; profile?: string | null; counter_themes?: string[]; topic_cues?: string[] }
  lyric_match?: { kind: 'exact' | 'approximate'; similarity: number } | null
}
export type Health = { documents: number; semantic_ready: boolean; default_mode: string; tuned: boolean
  embedding_progress?: { state: string; completed?: number; total?: number } | null }
export type Catalog = { tracks: Track[]; total: number; genres: { name: string; count: number }[] }
export type SearchResult = {
  ranking?: RankingPolicy
  results: Track[]; related_results?: Track[]; candidate_count: number; latency_ms: number; warnings: string[]
  result_policy?: { primary: 'direct' | 'ranked' | 'supported'; genre_source: string | null }
  catalog_match?: { kind: 'artist' | 'title' | 'genre'; value: string; method: string; similarity: number; source?: string } | null
  pipeline: { lexical?: boolean; semantic: boolean; audio: boolean; degraded: boolean }
  mood?: { label: 'sad' | 'happy'; basis: MoodBasis; audio_constraints: [string, string, number][]; note: string } | null
}
export type RankingPolicy = { score_kind: 'eligibility' | 'audio_preference' | 'ranking'; score_label: string;
  score_meaning: string; order_by: string[]; order_label: string }
export type MoodBasis = 'lyrics' | 'audio' | 'both'
export type Playlist = { id: string; name: string; tracks: Track[] }
export type Library = { liked: Track[]; playlists: Playlist[] }
export type Page = { kind: 'home' | 'liked' | 'catalog' | 'artists' | 'benchmark' } |
  { kind: 'search'; query: string } | { kind: 'genre'; genre: string } | { kind: 'playlist'; id: string }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, {
    ...options, headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const message = typeof body.detail === 'string' ? body.detail :
      Array.isArray(body.detail) ? body.detail.map((item: { msg: string }) => item.msg).join('. ') :
        'Layanan musik belum bisa dihubungi. Coba lagi sebentar.'
    throw new Error(message)
  }
  return response.json()
}

export const spotifyUrl = (track: Track) => `https://open.spotify.com/track/${encodeURIComponent(track.track_id)}`
export function duration(milliseconds: number | null | undefined) {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return '—'
  const seconds = Math.floor(milliseconds / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
export function genreName(name: string) {
  const names: Record<string, string> = { pop: 'Pop', rock: 'Rock', 'hip-hop': 'Hip-Hop', rap: 'Hip-Hop',
    latin: 'Latin', electronic: 'Elektronik', edm: 'Elektronik', folk: 'Folk & akustik', gaming: 'Gaming',
    'r&b': 'R&B', jazz: 'Jazz', classical: 'Klasik', indie: 'Indie', country: 'Country' }
  return names[name] || name.charAt(0).toUpperCase() + name.slice(1)
}
export function readPage(): Page {
  const params = new URLSearchParams(window.location.search)
  if (params.get('q')) return { kind: 'search', query: params.get('q')!.slice(0, 2000) }
  if (params.get('genre')) return { kind: 'genre', genre: params.get('genre')! }
  if (params.get('playlist')) return { kind: 'playlist', id: params.get('playlist')! }
  const kind = params.get('view')
  return { kind: kind === 'liked' || kind === 'catalog' || kind === 'artists' || kind === 'benchmark' ? kind : 'home' }
}
export function pageUrl(page: Page) {
  const params = new URLSearchParams()
  if (page.kind === 'search') params.set('q', page.query)
  else if (page.kind === 'genre') params.set('genre', page.genre)
  else if (page.kind === 'playlist') params.set('playlist', page.id)
  else if (page.kind !== 'home') params.set('view', page.kind)
  return '/' + (params.size ? '?' + params.toString() : '')
}

export function readLibrary(): Library {
  const isTrack = (track: unknown): track is Track => {
    if (!track || typeof track !== 'object') return false
    const value = track as Track
    return typeof value.track_id === 'string' && /^[a-zA-Z0-9]+$/.test(value.track_id) &&
      typeof value.title === 'string' && typeof value.artist === 'string' &&
      typeof value.album === 'string' && !!value.audio && Array.isArray(value.genres)
  }
  try {
    const data = JSON.parse(localStorage.getItem('music-ir-library-v1') || '{}')
    return {
      liked: Array.isArray(data.liked) ? data.liked.filter(isTrack) : [],
      playlists: Array.isArray(data.playlists) ? data.playlists.filter((p: Playlist) =>
        typeof p?.id === 'string' && typeof p.name === 'string' && Array.isArray(p.tracks))
        .map((p: Playlist) => ({ ...p, tracks: p.tracks.filter(isTrack) })) : [],
    }
  } catch { return { liked: [], playlists: [] } }
}
