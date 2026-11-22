import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownWideNarrow, ArrowRight, ArrowUpRight, Check, ChevronLeft, ChevronRight, CircleCheck,
  ExternalLink, Heart, Home, LibraryBig, ListMusic, LoaderCircle, Maximize2, Menu, Mic2, Music2,
  Play, Plus, Search, Settings2, Shuffle, SkipBack, SkipForward, Sparkles, SquarePlay, X } from 'lucide-react'
import { Artwork, Empty, IconButton, LikedArt, Modal, TrackCard, TrackTable } from './components'
import DiagnosticsPanel from './DiagnosticsPanel'
import BenchmarkPage from './BenchmarkPage'
import RelevancePage from './RelevancePage'
import MoodControls from './MoodControls'
import { api, duration, genreName, pageUrl, readLibrary, readPage, spotifyUrl,
  type Catalog, type Health, type Library, type Page, type SearchResult, type Track, type MoodBasis } from './lib'

const suggestions = [
  { label: 'Sulit melupakan seseorang', query: 'lagu tentang sulit melupakan seseorang', color: '#7358ff' },
  { label: 'Energi untuk harimu', query: 'energi tinggi', color: '#e13300' },
  { label: 'Pelan-pelan saja', query: 'tempo di bawah 90 BPM', color: '#006450' },
  { label: 'Saatnya jatuh cinta', query: 'lagu tentang jatuh cinta', color: '#e8115b' },
]

export default function App() {
  const [page, setPage] = useState<Page>(readPage)
  const [input, setInput] = useState(page.kind === 'search' ? page.query : '')
  const [health, setHealth] = useState<Health | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [browse, setBrowse] = useState<Catalog | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [homeError, setHomeError] = useState('')
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [offset, setOffset] = useState(0)
  const [library, setLibrary] = useState<Library>(readLibrary)
  const [libraryFilter, setLibraryFilter] = useState('')
  const [librarySearch, setLibrarySearch] = useState(false)
  const [libraryTab, setLibraryTab] = useState<'playlists' | 'artists'>('playlists')
  const [selected, setSelected] = useState<Track | null>(null)
  const [detail, setDetail] = useState<(Track & { lyrics: string }) | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [embedOpen, setEmbedOpen] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [mobileLibrary, setMobileLibrary] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [playlistDialog, setPlaylistDialog] = useState(false)
  const [playlistName, setPlaylistName] = useState('')
  const [addTrack, setAddTrack] = useState<Track | null>(null)
  const [mode, setMode] = useState('AUTO')
  const [moodBasis, setMoodBasis] = useState<MoodBasis | undefined>(undefined)
  const [toast, setToast] = useState('')
  const [shuffle, setShuffle] = useState(false)
  const [searchFocused, setSearchFocused] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const liked = useMemo(() => new Set(library.liked.map(t => t.track_id)), [library.liked])
  const homeTracks = catalog?.tracks || []
  const current = selected || homeTracks[0]
  const artists = useMemo(() => [...new Map(homeTracks.map(t => [t.artist.split(',')[0].trim(), t])).values()], [homeTracks])
  const selectedPlaylist = page.kind === 'playlist' ? library.playlists.find(p => p.id === page.id) : undefined
  const activeTracks = page.kind === 'search' ? [...(result?.results || []), ...(result?.related_results || [])] : page.kind === 'liked' ? library.liked :
    page.kind === 'playlist' ? selectedPlaylist?.tracks || [] : page.kind === 'genre' || page.kind === 'catalog' ? browse?.tracks || [] : homeTracks

  function navigate(next: Page) {
    window.history.pushState({}, '', pageUrl(next))
    setPage(next); setOffset(0); setMobileLibrary(false); setSearchFocused(false)
    setMoodBasis(undefined)
    setInput(next.kind === 'search' ? next.query : '')
    mainRef.current?.scrollTo({ top: 0 })
  }
  function search(query: string) {
    const trimmed = query.trim()
    if (trimmed) navigate({ kind: 'search', query: trimmed })
    else searchRef.current?.focus()
  }
  useEffect(() => {
    const handler = () => { const next = readPage(); setPage(next); setOffset(0); setMoodBasis(undefined); setInput(next.kind === 'search' ? next.query : '') }
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') { event.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('popstate', handler); window.addEventListener('keydown', shortcut)
    return () => { window.removeEventListener('popstate', handler); window.removeEventListener('keydown', shortcut) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setHomeError('')
    Promise.all([api<Health>('/health', { signal: controller.signal }), api<Catalog>('/catalog?limit=60', { signal: controller.signal })])
      .then(([status, collection]) => {
        if (status.default_mode !== 'AUTO') throw new Error('Backend perlu dimuat ulang agar mendukung pencarian otomatis. Jalankan ulang run.ps1 api.')
        setHealth(status); setCatalog(collection)
      }).catch(exc => { if (!controller.signal.aborted) setHomeError(exc.message || 'Koleksi belum bisa dimuat.') })
    return () => controller.abort()
  }, [refresh])
  useEffect(() => {
    const controller = new AbortController()
    setError(''); setResult(null); setBrowse(null); setBusy(false)
    if (page.kind === 'search') {
      setBusy(true)
      api<SearchResult>('/search', { method: 'POST', body: JSON.stringify({ query: page.query, mode, top_k: 30, mood_basis: mode === 'AUTO' ? moodBasis : undefined }), signal: controller.signal })
        .then(setResult).catch(exc => { if (!controller.signal.aborted) setError(exc.message) })
        .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    } else if (page.kind === 'genre' || page.kind === 'catalog') {
      setBusy(true)
      const params = new URLSearchParams({ limit: '60', offset: String(offset) })
      if (page.kind === 'genre') params.set('genre', page.genre)
      api<Catalog>('/catalog?' + params, { signal: controller.signal })
        .then(setBrowse).catch(exc => { if (!controller.signal.aborted) setError(exc.message) })
        .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    }
    return () => controller.abort()
  }, [page, mode, offset, refresh, moodBasis])
  useEffect(() => {
    if (!current || !detailsOpen) return
    const controller = new AbortController()
    setDetail(null); setDetailError('')
    api<Track & { lyrics: string }>('/tracks/' + encodeURIComponent(current.track_id), { signal: controller.signal })
      .then(setDetail).catch(exc => { if (!controller.signal.aborted) setDetailError(exc.message) })
    return () => controller.abort()
  }, [current?.track_id, detailsOpen])
  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(''), 3400)
    return () => window.clearTimeout(id)
  }, [toast])

  function saveLibrary(next: Library) {
    setLibrary(next)
    try { localStorage.setItem('music-ir-library-v1', JSON.stringify(next)) }
    catch { setToast('Penyimpanan browser penuh. Perubahan hanya tersimpan selama sesi ini.') }
  }
  function toggleLike(track: Track) {
    const removing = liked.has(track.track_id)
    saveLibrary({ ...library, liked: removing ? library.liked.filter(t => t.track_id !== track.track_id) : [track, ...library.liked] })
    setToast(removing ? 'Dihapus dari Lagu yang Disukai' : 'Ditambahkan ke Lagu yang Disukai')
  }
  function selectTrack(track: Track) { setSelected(track); setDetailsOpen(true); setQueueOpen(false) }
  function playTrack(track: Track) { setSelected(track); setEmbedOpen(true) }
  function skip(direction: number) {
    if (!activeTracks.length) return
    const index = activeTracks.findIndex(t => t.track_id === current?.track_id)
    const next = shuffle && activeTracks.length > 1 ?
      (Math.max(index, 0) + 1 + Math.floor(Math.random() * (activeTracks.length - 1))) % activeTracks.length :
      (index + direction + activeTracks.length) % activeTracks.length
    setSelected(activeTracks[next])
  }
  function createPlaylist(event: React.FormEvent) {
    event.preventDefault()
    const name = playlistName.trim()
    if (!name) return
    const playlist = { id: crypto.randomUUID(), name, tracks: addTrack ? [addTrack] : [] }
    saveLibrary({ ...library, playlists: [...library.playlists, playlist] })
    setPlaylistDialog(false); setAddTrack(null); setPlaylistName(''); setToast('Playlist berhasil dibuat')
    navigate({ kind: 'playlist', id: playlist.id })
  }
  function addToPlaylist(id: string) {
    if (!addTrack) return
    const exists = library.playlists.find(p => p.id === id)?.tracks.some(t => t.track_id === addTrack.track_id)
    if (!exists) saveLibrary({ ...library, playlists: library.playlists.map(p => p.id === id ? { ...p, tracks: [...p.tracks, addTrack] } : p) })
    setToast(exists ? 'Lagu sudah ada di playlist ini' : 'Lagu ditambahkan ke playlist'); setAddTrack(null)
  }
  const table = (tracks: Track[]) => <TrackTable tracks={tracks} selectedId={current?.track_id} liked={liked}
    onSelect={selectTrack} onPlay={playTrack} onLike={toggleLike} onAdd={setAddTrack} />
  const cards = (tracks: Track[], artist = false) => tracks.map(track => <TrackCard key={track.track_id} track={track}
    artist={artist} onArtist={() => search(track.artist.split(',')[0])} onSelect={selectTrack} onPlay={playTrack} />)
  const count = new Intl.NumberFormat('id-ID').format(health?.documents || 0)
  const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Jakarta', hour: 'numeric', hour12: false }).format(new Date()))
  const greeting = hour < 11 ? 'Selamat pagi' : hour < 15 ? 'Selamat siang' : hour < 18 ? 'Selamat sore' : 'Selamat malam'
  const genres = (catalog?.genres || []).filter(g => g.name !== 'gaming').slice(0, 8)

  return <div className={`app-shell ${collapsed ? 'library-collapsed' : ''} ${detailsOpen || queueOpen ? 'with-details' : ''}`}>
    <a href="#main-content" className="skip-link">Langsung ke musik</a>
    <header className="topbar">
      <button className="brand" aria-label="Music IR — Beranda" onClick={() => navigate({ kind: 'home' })}>
        <img src="/favicon.svg" alt="" /><span>Music<span className="brand-ir">IR</span></span>
      </button>
      <div className="topbar-middle">
        <IconButton label="Buka koleksi" className="mobile-menu" onClick={() => setMobileLibrary(!mobileLibrary)}><Menu size={23} /></IconButton>
        <IconButton label="Beranda" className={`home-button ${page.kind === 'home' ? 'on-home' : ''}`} onClick={() => navigate({ kind: 'home' })}><Home size={25} fill={page.kind === 'home' ? 'currentColor' : 'none'} /></IconButton>
        <form className={`searchbox ${searchFocused ? 'focused' : ''}`} role="search" onSubmit={event => { event.preventDefault(); search(input) }}>
          <Search size={23} />
          <input ref={searchRef} aria-label="Cari musik" placeholder="Apa yang ingin kamu dengarkan?" value={input} maxLength={2000}
            onChange={event => setInput(event.target.value)} onFocus={() => setSearchFocused(true)} onBlur={() => setSearchFocused(false)} />
          {input ? <IconButton label="Hapus pencarian" onClick={() => { setInput(''); searchRef.current?.focus() }}><X size={20} /></IconButton> : <kbd>Ctrl K</kbd>}
          <span className="search-divider" /><button className="browse-button" type="button" aria-label="Jelajahi semua musik" title="Jelajahi semua musik" onClick={() => navigate({ kind: 'catalog' })}><LibraryBig size={22} /></button>
          {searchFocused && !input && <div className="search-suggestions"><p>Cari dari cerita yang kamu ingat</p>{suggestions.slice(0, 3).map(item =>
            <button key={item.query} type="button" onMouseDown={event => event.preventDefault()} onClick={() => search(item.query)}><Search size={16} />{item.label}<ArrowUpRight size={16} /></button>)}</div>}
        </form>
      </div>
      <div className="topbar-right"><a className="spotify-link" href="https://open.spotify.com" target="_blank" rel="noreferrer">Buka Spotify <ArrowUpRight size={16} /></a>
        <IconButton label="Pengaturan pencarian" onClick={() => setSettingsOpen(true)}><Settings2 size={21} /></IconButton><button className="profile" onClick={() => setSettingsOpen(true)} aria-label="Profil dan pengaturan">K4</button></div>
    </header>

    {mobileLibrary && <button className="mobile-scrim" aria-label="Tutup koleksi" onClick={() => setMobileLibrary(false)} />}
    <aside className={`sidebar ${mobileLibrary ? 'mobile-open' : ''}`} aria-label="Koleksi kamu">
      <div className="library-heading"><button onClick={() => setCollapsed(!collapsed)} className="library-title" aria-label={collapsed ? 'Perluas koleksi' : 'Ciutkan koleksi'}><LibraryBig size={24} /><span>Koleksi kamu</span></button><IconButton label="Buat playlist" onClick={() => { setPlaylistName(''); setPlaylistDialog(true) }}><Plus size={23} /></IconButton></div>
      <div className="sidebar-expanded">
        <div className="library-tabs"><button className={libraryTab === 'playlists' ? 'pill active-subtle' : 'pill'} onClick={() => setLibraryTab('playlists')}>Playlist</button><button className={libraryTab === 'artists' ? 'pill active-subtle' : 'pill'} onClick={() => setLibraryTab('artists')}>Artis</button></div>
        <div className="library-tools"><IconButton label="Cari di koleksi" onClick={() => setLibrarySearch(!librarySearch)}><Search size={18} /></IconButton><span>Terbaru <ArrowDownWideNarrow size={17} /></span></div>
        {librarySearch && <input className="library-search" aria-label="Cari di koleksi" autoFocus value={libraryFilter} onChange={event => setLibraryFilter(event.target.value)} placeholder="Cari di koleksi" />}
      </div>
      <div className="library-items">
        <button className={`library-item ${page.kind === 'liked' ? 'active-item' : ''}`} onClick={() => navigate({ kind: 'liked' })} title="Lagu yang Disukai"><LikedArt small /><span><strong>Lagu yang Disukai</strong><small><Heart size={12} fill="currentColor" /> Playlist · {library.liked.length} lagu</small></span></button>
        {libraryTab === 'playlists' ? <>
          {library.playlists.filter(p => p.name.toLowerCase().includes(libraryFilter.toLowerCase())).map(playlist => <button className={`library-item ${page.kind === 'playlist' && page.id === playlist.id ? 'active-item' : ''}`} key={playlist.id} onClick={() => navigate({ kind: 'playlist', id: playlist.id })} title={playlist.name}>
            {playlist.tracks[0] ? <Artwork track={playlist.tracks[0]} /> : <div className="playlist-art"><Music2 size={24} /></div>}<span><strong>{playlist.name}</strong><small>Playlist · {playlist.tracks.length} lagu</small></span></button>)}
          {(catalog?.genres || []).filter(g => genreName(g.name).toLowerCase().includes(libraryFilter.toLowerCase())).slice(0, 7).map((genre, i) => <button key={genre.name} className={`library-item ${page.kind === 'genre' && page.genre === genre.name ? 'active-item' : ''}`} onClick={() => navigate({ kind: 'genre', genre: genre.name })} title={genreName(genre.name)} aria-label={`${genreName(genre.name)} Mix`}>
            {homeTracks.find(t => t.genres.includes(genre.name)) ? <Artwork track={homeTracks.find(t => t.genres.includes(genre.name))!} /> : <div className="genre-mini" style={{ background: suggestions[i % 4].color }}><Music2 size={25} /></div>}
            <span><strong>{genreName(genre.name)} Mix</strong><small>Koleksi · {genre.count} lagu</small></span></button>)}
        </> : artists.filter(t => t.artist.toLowerCase().includes(libraryFilter.toLowerCase())).map(track => <button className="library-item" key={track.track_id} onClick={() => search(track.artist.split(',')[0])} title={track.artist}><Artwork track={track} artist /><span><strong>{track.artist.split(',')[0]}</strong><small>Artis</small></span></button>)}
      </div>
      <div className="sidebar-expanded library-bottom"><div className="library-invite"><Music2 size={24} /><p>Musikmu, ceritamu.</p><span>Judul, lirik, atau suasana hati.<br />Temukan yang kamu cari.</span></div>
        <button className="engine-status" onClick={() => setSettingsOpen(true)}><span className={`status-dot ${health?.semantic_ready ? '' : 'muted'}`} /><span>{health?.semantic_ready ? 'Pencarian pintar aktif' : 'Pencarian kata kunci'}</span><ChevronRight size={15} /></button></div>
    </aside>

    <main id="main-content" ref={mainRef} className={`main-panel ${page.kind === 'home' ? 'home-panel' : ''} ${page.kind === 'liked' ? 'liked-panel' : ''}`}>
      <div className="content-nav"><div className="history-buttons"><IconButton label="Kembali" onClick={() => window.history.back()}><ChevronLeft size={23} /></IconButton><IconButton label="Maju" onClick={() => window.history.forward()}><ChevronRight size={23} /></IconButton></div>
        <nav className="content-tabs" aria-label="Jelajahi musik"><button className={`pill ${page.kind === 'home' ? 'active' : ''}`} onClick={() => navigate({ kind: 'home' })}>Semua</button><button className={`pill ${page.kind === 'catalog' ? 'active' : ''}`} onClick={() => navigate({ kind: 'catalog' })}>Musik</button><button className={`pill ${page.kind === 'artists' ? 'active' : ''}`} onClick={() => navigate({ kind: 'artists' })}>Artis</button></nav>
        <span className="collection-count"><span className="status-dot" />{count} lagu untuk dijelajahi</span>
      </div>

      {homeError ? <div className="error-state" role="alert"><Music2 size={36} /><h2>Koleksi belum bisa dimuat</h2><p>{homeError}</p><button className="white-button" onClick={() => setRefresh(r => r + 1)}>Coba lagi</button></div> : !catalog ?
        <div className="loading-home" aria-label="Memuat koleksi"><div className="skeleton skeleton-heading" /><div className="quick-grid">{Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton skeleton-quick" />)}</div><div className="skeleton skeleton-heading" /><div className="card-grid">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton skeleton-card" />)}</div></div> : <>
        {page.kind === 'home' && <div className="home-content">
          <div className="welcome"><div><p className="eyebrow">SOUNDTRACK UNTUK HARIMU</p><h1>{greeting}<span className="greeting-dot">.</span></h1></div><span className="welcome-note"><Sparkles size={16} />Selalu ada lagu yang pas.</span></div>
          <div className="quick-grid">{homeTracks.slice(0, 8).map(track => <div className="quick-tile" key={track.track_id}><button className="quick-main" onClick={() => selectTrack(track)}><Artwork track={track} /><span>{track.title}</span></button><button className="green-play" aria-label={`Dengarkan ${track.title}`} onClick={() => playTrack(track)}><Play size={18} fill="currentColor" /></button></div>)}</div>
          <section className="music-section"><div className="section-heading"><div><h2>Temukan favorit barumu</h2><p>Lagu-lagu populer dari koleksi kita.</p></div><button onClick={() => navigate({ kind: 'catalog' })}>Tampilkan semua</button></div><div className="card-grid">{cards(homeTracks.slice(0, 6))}</div></section>
          <section className="music-section mood-section"><div className="section-heading"><div><h2>Lagi ingin dengar apa?</h2><p>Mulai dari suasana, biarkan musik bercerita.</p></div><Sparkles size={21} /></div><div className="mood-grid">{suggestions.map((item, i) => <button className="mood-card" key={item.query} style={{ background: item.color }} onClick={() => search(item.query)}><span>{item.label}</span><small>Jelajahi musik <ArrowUpRight size={15} /></small>{homeTracks[i + 9] && <Artwork track={homeTracks[i + 9]} />}</button>)}</div></section>
          <section className="music-section"><div className="section-heading"><div><h2>Artis pilihanmu berikutnya</h2><p>Suara yang mungkin akan tinggal lebih lama.</p></div><button onClick={() => navigate({ kind: 'artists' })}>Tampilkan semua</button></div><div className="card-grid">{cards(artists.slice(0, 6), true)}</div></section>
          <section className="music-section"><div className="section-heading"><h2>Jelajahi genre</h2></div><div className="genre-grid">{genres.map((genre, i) => <button key={genre.name} style={{ background: ['#8c1932', '#1e3264', '#006450', '#8d67ab', '#b02897', '#ba5d07', '#477d95', '#537aa1'][i % 8] }} onClick={() => navigate({ kind: 'genre', genre: genre.name })}><span>{genreName(genre.name)}</span><small>{genre.count} lagu</small><ArrowUpRight size={24} /></button>)}</div></section>
        </div>}

        {page.kind === 'artists' && <div className="page-content"><p className="eyebrow">TEMUKAN SUARA BARU</p><h1>Artis di koleksi kita</h1><p className="page-description">Jelajahi artis dari lagu-lagu populer.</p><div className="artist-grid">{cards(artists, true)}</div></div>}
        {page.kind === 'benchmark' && <BenchmarkPage onSearch={search} />}
        {page.kind === 'relevance' && <RelevancePage />}

        {page.kind === 'search' && <div className="page-content search-content"><p className="eyebrow">HASIL PENCARIAN</p><h1 className="search-heading">{page.query}</h1>{busy && <div className="search-loading" role="status"><LoaderCircle className="spin" size={28} /><h3>Mencari musik yang pas…</h3><p>Pencarian pertama mungkin sedikit lebih lama.</p></div>}
          {error && <div className="inline-error" role="alert"><p>{error}</p><button className="white-button" onClick={() => setRefresh(r => r + 1)}>Coba lagi</button></div>}
          {result && <>{result.warnings.map(warning => <div className="warning-banner" role="status" key={warning}>{warning}</div>)}
            <div className="result-info"><span>{result.results.length} lagu ditemukan{result.related_results?.length ? ` · ${result.related_results.length} hasil serupa` : ''}</span><span>{result.catalog_match ? ({ artist: 'Pencarian artis', title: 'Pencarian judul', genre: 'Pencarian genre' }[result.catalog_match.kind]) : result.mood?.basis === 'audio' ? 'Pencarian nuansa musik' : result.pipeline.audio && result.pipeline.lexical === false && !result.pipeline.semantic ? 'Pencarian audio' : result.pipeline.semantic ? <><Sparkles size={14} />Pencarian makna</> : 'Pencarian kata kunci'}{result.pipeline.audio && result.mood?.basis !== 'audio' && (result.pipeline.semantic || result.pipeline.lexical !== false) ? ' + fitur audio' : ''}<i />{Math.round(result.latency_ms)} ms</span></div>
            {result.catalog_match?.kind === 'genre' && <p className="page-description">Genre mengikuti label playlist pada koleksi; beberapa lagu memiliki lebih dari satu label.</p>}
            {result.mood && <MoodControls mood={result.mood} onChange={setMoodBasis} />}
            <DiagnosticsPanel key={mode + ':' + page.query + ':' + result.mood?.basis} query={page.query} mode={mode} moodBasis={result.mood?.basis} />
            {result.results.length ? <><div className="search-top"><section><h2>Hasil teratas</h2><div className="top-result"><Artwork track={result.results[0]} /><button className="top-result-title" onClick={() => selectTrack(result.results[0])}>{result.results[0].title}</button><p>{result.results[0].artist}<span className="pill">Lagu</span></p><button className="green-play" aria-label={`Dengarkan hasil teratas ${result.results[0].title}`} onClick={() => playTrack(result.results[0])}><Play size={24} fill="currentColor" /></button></div></section>
              <section className="matching-story"><span><Sparkles size={20} />Di balik kecocokan</span><h3>{result.results[0].title}</h3><p>{result.results[0].snippet || 'Lagu ini cocok dengan pencarianmu berdasarkan metadata yang tersedia.'}</p><small>{result.results[0].snippet_type === 'semantic' ? 'Bagian lirik pendukung tema' : result.results[0].lyric_match?.kind === 'approximate' ? 'Potongan lirik yang mirip' : result.results[0].snippet_type === 'lexical' ? 'Potongan lirik yang cocok' : 'Pratinjau lirik'}</small><button onClick={() => selectTrack(result.results[0])}>Lihat detail lagu <ArrowRight size={16} /></button></section></div><section className="songs-section"><h2>{result.result_policy?.primary === 'direct' ? 'Kecocokan langsung' : result.result_policy?.primary === 'supported' ? 'Hasil berdasarkan lirik' : 'Lagu'}</h2>{table(result.results)}</section></> : <Empty title="Belum ada lagu yang cocok">Coba judul, artis, potongan lirik, atau suasana lain. Batas tempo dan energi tetap diterapkan sesuai permintaanmu.</Empty>}
            {!!result.related_results?.length && <section className="songs-section related-results"><h2>Hasil serupa</h2><p className="page-description">{result.result_policy?.primary === 'supported' ? 'Tema berdekatan, tetapi bukti lirik untuk detail yang diminta belum cukup.' : 'Lagu berikut memiliki kemiripan kata atau makna; kutipan lirik yang kamu cari belum terverifikasi pada hasil ini.'}</p>{table(result.related_results)}</section>}
          </>}
        </div>}

        {(page.kind === 'liked' || page.kind === 'playlist') && <>
          <div className={`collection-hero ${page.kind === 'liked' ? 'purple-hero' : ''}`}>
            {page.kind === 'liked' ? <LikedArt /> : activeTracks[0] ? <Artwork track={activeTracks[0]} /> : <div className="playlist-art"><Music2 size={76} /></div>}
            <div><p>Playlist</p><h1>{page.kind === 'liked' ? 'Lagu yang Disukai' : selectedPlaylist?.name || 'Playlist tidak ditemukan'}</h1><span><span className="mini-profile">K4</span><strong>Koleksi kamu</strong> · {activeTracks.length} lagu</span></div>
          </div>
          <div className="page-content collection-content"><div className="collection-actions"><button className="green-play large-play" disabled={!activeTracks.length} aria-label="Dengarkan playlist" onClick={() => activeTracks[0] && playTrack(activeTracks[0])}><Play fill="currentColor" size={27} /></button><span>Tersimpan di browser ini</span>{selectedPlaylist && <button className="text-button delete-playlist" onClick={() => {
            if (window.confirm(`Hapus playlist “${selectedPlaylist.name}”?`)) { saveLibrary({ ...library, playlists: library.playlists.filter(p => p.id !== selectedPlaylist.id) }); navigate({ kind: 'home' }); setToast('Playlist dihapus') }
          }}>Hapus playlist</button>}</div>
            {activeTracks.length ? <>{table(activeTracks)}{page.kind === 'playlist' && <p className="playlist-tip">Tambahkan lagu lewat tombol ••• pada daftar hasil pencarian.</p>}</> : <Empty title={page.kind === 'liked' ? 'Semua favoritmu, satu tempat.' : 'Playlist ini menunggu ceritamu.'}>Sukai lagu atau tambahkan lagu dari hasil pencarian untuk mulai mengisi koleksimu.<button className="white-button" onClick={() => navigate({ kind: 'catalog' })}>Temukan lagu</button></Empty>}
          </div>
        </>}

        {(page.kind === 'genre' || page.kind === 'catalog') && <div className="page-content"><p className="eyebrow">JELAJAHI KOLEKSI</p><h1>{page.kind === 'genre' ? `${genreName(page.genre)} Mix` : 'Semua musik'}</h1><p className="page-description">{browse?.total?.toLocaleString('id-ID') || '…'} lagu. Banyak cerita untuk ditemukan.</p>
          {busy && <div className="search-loading" role="status"><LoaderCircle className="spin" size={30} /><p>Memuat musik…</p></div>}{error && <div className="inline-error" role="alert">{error}<button className="white-button" onClick={() => setRefresh(r => r + 1)}>Coba lagi</button></div>}
          {browse && <>{browse.tracks.length ? table(browse.tracks) : <Empty title="Koleksi ini masih kosong">Pilih genre lain untuk melanjutkan.</Empty>}<div className="pagination"><span>{browse.total ? offset + 1 : 0}–{offset + browse.tracks.length} dari {browse.total} lagu</span><IconButton label="Halaman sebelumnya" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 60)); mainRef.current?.scrollTo({ top: 0 }) }}><ChevronLeft size={22} /></IconButton><IconButton label="Halaman berikutnya" disabled={offset + browse.tracks.length >= browse.total} onClick={() => { setOffset(offset + 60); mainRef.current?.scrollTo({ top: 0 }) }}><ChevronRight size={22} /></IconButton></div></>}
        </div>}
        <footer className="content-footer"><div className="footer-brand"><Music2 size={20} /><strong>Music IR</strong><span>Setiap lagu punya cerita.</span></div><div><span>Kelompok 4</span><i />{count} lagu dalam koleksi<i /><button onClick={() => setSettingsOpen(true)}>Tentang pencarian</button></div></footer>
      </>}
    </main>

    {(detailsOpen || queueOpen) && <aside className="detail-panel" aria-label={queueOpen ? 'Antrean lagu' : 'Detail lagu'}><header><h2>{queueOpen ? 'Antrean lagu' : 'Tentang lagu ini'}</h2><IconButton label="Tutup panel detail" onClick={() => { setDetailsOpen(false); setQueueOpen(false) }}><X size={21} /></IconButton></header>
      {queueOpen ? <div className="queue-list"><p>Dari halaman ini · {activeTracks.length} lagu</p>{activeTracks.map(track => <button key={track.track_id} className={`library-item ${current?.track_id === track.track_id ? 'active-item' : ''}`} onClick={() => setSelected(track)}><Artwork track={track} /><span><strong>{track.title}</strong><small>{track.artist}</small></span></button>)}</div> : current && <>
        <Artwork track={current} className="detail-art" /><div className="detail-title"><div><h2>{current.title}</h2><p>{current.artist}</p></div><IconButton label={liked.has(current.track_id) ? 'Hapus dari favorit' : 'Sukai lagu'} active={liked.has(current.track_id)} onClick={() => toggleLike(current)}><Heart size={23} fill={liked.has(current.track_id) ? 'currentColor' : 'none'} /></IconButton></div>
        <a className="white-button detail-spotify" href={spotifyUrl(current)} target="_blank" rel="noreferrer">Dengarkan di Spotify <ExternalLink size={16} /></a>
        <section className="detail-section"><h3>Karakter musik</h3>{[['energy', 'Energi'], ['danceability', 'Danceability'], ['valence', 'Nuansa ceria'], ['acousticness', 'Akustik']].map(([key, label]) => <div className="audio-feature" key={key}><div><span>{label}</span><b>{current.audio[key] != null ? `${Math.round(current.audio[key]! * 100)}%` : '—'}</b></div><div className="feature-track"><span style={{ width: `${Math.max(0, Math.min(100, (current.audio[key] || 0) * 100))}%` }} /></div></div>)}<p className="tempo-label">Tempo <strong>{current.audio.tempo != null ? `${Math.round(current.audio.tempo)} BPM` : 'Tidak tersedia'}</strong></p></section>
        {current.reasons?.length ? <section className="detail-section"><h3>Kenapa lagu ini?</h3>{current.reasons.map(reason => <p className="match-reason" key={reason}><CircleCheck size={15} />{reason}</p>)}</section> : null}
        <section className="detail-section lyrics-section"><h3>Lirik</h3>{detailError ? <p>{detailError}</p> : detail ? <><p className="lyrics-text">{detail.lyrics || 'Lirik belum tersedia untuk lagu ini.'}</p>{detail.lyrics && <small>Lirik dari dataset · kecocokan rekaman belum diaudit.</small>}</> : <LoaderCircle className="spin" size={22} />}</section>
      </>}
    </aside>}

    <footer className="player-bar" aria-label="Lagu pilihan">
      <div className="now-playing">{current ? <><button className="art-button" onClick={() => selectTrack(current)} aria-label={`Detail ${current.title}`}><Artwork track={current} /></button><div><button onClick={() => selectTrack(current)} className="track-title">{current.title}</button><span>{current.artist}</span></div><IconButton label={liked.has(current.track_id) ? 'Hapus dari favorit' : 'Sukai lagu pilihan'} active={liked.has(current.track_id)} onClick={() => toggleLike(current)}>{liked.has(current.track_id) ? <CircleCheck size={19} /> : <Plus size={19} />}</IconButton></> : <><div className="playlist-art"><Music2 size={25} /></div><span>Pilih musik untuk harimu</span></>}</div>
      <div className="player-center"><div className="playback-controls"><IconButton label="Acak antrean" active={shuffle} aria-pressed={shuffle} onClick={() => setShuffle(!shuffle)}><Shuffle size={17} /></IconButton><IconButton label="Lagu sebelumnya" disabled={!activeTracks.length} onClick={() => skip(-1)}><SkipBack size={19} fill="currentColor" /></IconButton><button className="main-play" aria-label="Buka pemutar Spotify" disabled={!current} onClick={() => current && playTrack(current)}><Play size={19} fill="currentColor" /></button><IconButton label="Lagu berikutnya" disabled={!activeTracks.length} onClick={() => skip(1)}><SkipForward size={19} fill="currentColor" /></IconButton><IconButton label="Detail dan lirik" active={detailsOpen} onClick={() => { setDetailsOpen(!detailsOpen); setQueueOpen(false) }}><Mic2 size={17} /></IconButton></div><div className="player-progress"><span>Spotify</span><div className="progress-line"><span /></div><span>{duration(current?.duration_ms)}</span></div></div>
      <div className="player-tools"><span className="playback-note">Dengarkan lewat Spotify</span><IconButton label="Antrean lagu" active={queueOpen} onClick={() => { setQueueOpen(!queueOpen); setDetailsOpen(false) }}><ListMusic size={19} /></IconButton><IconButton label="Tampilkan pemutar Spotify" active={embedOpen} disabled={!current} onClick={() => setEmbedOpen(!embedOpen)}><SquarePlay size={19} /></IconButton><IconButton label="Perluas detail lagu" onClick={() => { setDetailsOpen(true); setQueueOpen(false) }}><Maximize2 size={17} /></IconButton></div>
    </footer>

    {embedOpen && current && <section className="embed-panel" aria-label="Pemutar Spotify"><header><div><span className="status-dot" />Dengarkan di Spotify</div><IconButton label="Tutup pemutar Spotify" onClick={() => setEmbedOpen(false)}><X size={21} /></IconButton></header><iframe key={current.track_id} title={`Spotify — ${current.title}`} src={`https://open.spotify.com/embed/track/${encodeURIComponent(current.track_id)}?utm_source=generator&theme=0`} width="100%" height="152" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" /><p>Pemutaran dan ketersediaan pratinjau mengikuti Spotify. <a href={spotifyUrl(current)} target="_blank" rel="noreferrer">Buka di Spotify <ArrowUpRight size={12} /></a></p></section>}
    {toast && <div className="toast" role="status"><Check size={19} />{toast}</div>}

    {settingsOpen && <Modal title="Pengaturan pencarian" onClose={() => setSettingsOpen(false)}>
      <p className="modal-description">Cari lewat judul, artis, lirik, cerita, atau karakter musik.</p>
      <div className="settings-status"><Sparkles size={22} /><div>
        <strong>{health?.semantic_ready ? 'Pencarian makna siap' : 'Pencarian kata kunci tersedia'}</strong><p>{count} lagu dalam koleksi</p>
      </div></div>
      {!health?.semantic_ready && health?.embedding_progress && <div className="model-progress">
        <span>Persiapan model · {health.embedding_progress.completed || 0} / {health.embedding_progress.total || 0}</span>
        <progress aria-label="Progres persiapan model" value={health.embedding_progress.completed || 0} max={health.embedding_progress.total || 1} />
      </div>}
      <button className="text-button refresh-model" onClick={() => setRefresh(r => r + 1)}>Perbarui status model</button>
      <label className="field-label" htmlFor="search-mode">Metode pencarian</label>
      <select id="search-mode" value={mode} onChange={event => setMode(event.target.value)}>
        <option value="AUTO">Otomatis — direkomendasikan</option><option value="E1">E1 — BM25 gabungan</option>
        <option value="E2">E2 — BM25 berbobot</option><option value="E3">E3 — Hybrid</option>
        <option value="E4">E4 — Reranking teks</option><option value="E5">E5 — Teks dan audio</option>
      </select>
      <p className="field-hint">E1–E5 digunakan untuk eksperimen laporan. E3–E5 membutuhkan model semantik untuk query teks.</p>
      <div className="query-examples"><h3>Coba cari</h3>{['Bruno Mars', 'lagu tentang kehilangan', 'tempo > 120 BPM', 'energi rendah'].map(query =>
        <button key={query} onClick={() => { search(query); setSettingsOpen(false) }}><Search size={15} />{query}<ArrowUpRight size={15} /></button>)}</div>
      <div className="research-entry"><button className="white-button" onClick={() => { setSettingsOpen(false); navigate({ kind: 'benchmark' }) }}>Benchmark & penilaian</button><p>Audit query dan kumpulkan label relevansi manusia.</p></div>
      <button className="green-button modal-done" onClick={() => setSettingsOpen(false)}>Selesai</button>
    </Modal>}
    {playlistDialog && <Modal title="Buat playlist" onClose={() => setPlaylistDialog(false)}><form onSubmit={createPlaylist}><div className="playlist-form-icon"><Music2 size={58} /></div><label className="field-label" htmlFor="playlist-name">Nama playlist</label><input id="playlist-name" autoFocus placeholder="Soundtrack hariku" maxLength={80} value={playlistName} onChange={event => setPlaylistName(event.target.value)} required /><p className="field-hint">Playlist disimpan di browser ini.</p><button type="submit" className="green-button modal-done" disabled={!playlistName.trim()}>Buat playlist</button></form></Modal>}
    {addTrack && !playlistDialog && <Modal title="Tambahkan ke playlist" onClose={() => setAddTrack(null)}>
      <div className="adding-track"><Artwork track={addTrack} /><div><strong>{addTrack.title}</strong><p>{addTrack.artist}</p></div></div>
      {selectedPlaylist && <button className="remove-track-option" onClick={() => {
        saveLibrary({ ...library, playlists: library.playlists.map(p => p.id === selectedPlaylist.id ?
          { ...p, tracks: p.tracks.filter(t => t.track_id !== addTrack.track_id) } : p) })
        setAddTrack(null); setToast('Lagu dihapus dari playlist')
      }}><X size={19} />Hapus dari playlist ini</button>}
      <button className="new-playlist-option" onClick={() => { setPlaylistName(''); setPlaylistDialog(true) }}><Plus size={21} />Buat playlist baru</button>
      {library.playlists.length ? library.playlists.map(playlist => <button className="playlist-option" key={playlist.id} onClick={() => addToPlaylist(playlist.id)}>
        <Music2 size={21} /><span>{playlist.name}<small>{playlist.tracks.length} lagu</small></span>
        {playlist.tracks.some(t => t.track_id === addTrack.track_id) && <Check size={19} />}
      </button>) : <p className="modal-description">Buat playlist pertamamu untuk menyimpan lagu ini.</p>}
    </Modal>}
  </div>
}
