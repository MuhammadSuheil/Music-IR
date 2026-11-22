import { useEffect, useState } from 'react'
import { ClipboardCheck, Download, LoaderCircle, Search, Users } from 'lucide-react'
import { Artwork } from './components'
import { api, spotifyUrl } from './lib'
import { download, type BenchmarkSummary, type CandidatePool, type ExportBundle } from './research'

const grades = ['0 · Tidak relevan', '1 · Sedikit terkait', '2 · Relevan', '3 · Sangat relevan']

export default function BenchmarkPage({ onSearch }: { onSearch: (query: string) => void }) {
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null)
  const [selected, setSelected] = useState('')
  const [split, setSplit] = useState('dev')
  const [category, setCategory] = useState('all')
  const [pool, setPool] = useState<CandidatePool | null>(null)
  const [annotator, setAnnotator] = useState(() => { try { return localStorage.getItem('music-ir-annotator') || '' } catch { return '' } })
  const [name, setName] = useState(annotator)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [depth, setDepth] = useState(10)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [bundle, setBundle] = useState<ExportBundle | null>(null)
  const query = summary?.queries.find(q => q.query_id === selected)
  const filtered = summary?.queries.filter(q => q.split === split && (category === 'all' || q.category === category)) || []

  async function loadSummary() {
    const data = await api<BenchmarkSummary>('/benchmark')
    setSummary(data)
    return data
  }
  useEffect(() => {
    const controller = new AbortController()
    api<BenchmarkSummary>('/benchmark', { signal: controller.signal }).then(setSummary)
      .catch(exc => { if (!controller.signal.aborted) setError(exc.message) })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (filtered.length && !filtered.some(q => q.query_id === selected)) setSelected(filtered[0].query_id)
  }, [summary, split, category, selected])
  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setLoading(true); setPool(null); setBundle(null); setError('')
    api<CandidatePool>(`/benchmark/queries/${encodeURIComponent(selected)}?annotator=${encodeURIComponent(annotator)}`, { signal: controller.signal })
      .then(data => { setPool(data); setNotes(Object.fromEntries(data.candidates.map(t => [t.track_id, t.judgment?.notes || '']))) })
      .catch(exc => { if (!controller.signal.aborted) setError(exc.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selected, annotator, revision])

  async function act(action: () => Promise<unknown>) {
    setError(''); setBusy(true)
    try { await action() } catch (exc) { setError(exc instanceof Error ? exc.message : 'Perubahan belum dapat disimpan.') }
    finally { setBusy(false) }
  }
  async function judge(trackId: string, grade: number) {
    await act(async () => {
      await api(`/benchmark/queries/${selected}/judgments`, { method: 'PUT', body: JSON.stringify({ track_id: trackId, annotator, grade, notes: notes[trackId] || '' }) })
      setPool(previous => previous ? { ...previous, candidates: previous.candidates.map(t => t.track_id === trackId ? { ...t, judgment: { grade, notes: notes[trackId] || '' } } : t) } : null)
      setBundle(null); await loadSummary()
    })
  }
  return <div className="page-content benchmark-page">
    <p className="eyebrow">EKSPERIMEN LOKAL</p><h1>Benchmark & penilaian</h1>
    <p className="page-description">Tinjau maksud query, lalu nilai relevansi lagu. Nilai disimpan di backend lokal dan tidak dipakai untuk melatih model secara otomatis.</p>
    <p><a className="text-button" href="/?view=relevance">Buka review label awal LLM →</a></p>
    {error && <div className="research-error" role="alert">{error}</div>}
    {!summary ? <div className="research-loading"><LoaderCircle className="spin" size={24} /><button className="text-button" onClick={() => act(loadSummary)}>Muat ulang benchmark</button></div> : <>
      <div className="research-stats"><span><strong>{summary.total}</strong> draft query</span><span><strong>{summary.approved}</strong> disetujui</span><span><strong>{summary.judgments}</strong> penilaian manusia</span><span>Label relevan: <strong>2–3</strong></span></div>
      <form className="research-form annotator-form" onSubmit={event => {
        event.preventDefault()
        const value = name.trim()
        if (!/^\w[\w .-]{0,63}$/u.test(value)) { setError('Nama/kode penilai harus dimulai huruf/angka dan berisi 1–64 karakter.'); return }
        setAnnotator(value); setError('')
        try { localStorage.setItem('music-ir-annotator', value) } catch { /* Session use remains available. */ }
      }}><label>Nama / kode penilai<input aria-label="Nama penilai" value={name} onChange={event => setName(event.target.value)} placeholder="Contoh: penilai-1" maxLength={64} required /></label><button className="white-button"><Users size={17} />Gunakan nama</button>{annotator && <span>Aktif: <strong>{annotator}</strong></span>}</form>
      <div className="benchmark-filters"><label>Split<select aria-label="Split benchmark" value={split} onChange={event => setSplit(event.target.value)}><option value="dev">Development</option><option value="test">Test — evaluasi akhir</option></select></label><label>Kategori<select aria-label="Kategori benchmark" value={category} onChange={event => setCategory(event.target.value)}><option value="all">Semua kategori</option>{['title', 'artist', 'lyrics', 'semantic', 'audio'].map(value => <option key={value}>{value}</option>)}</select></label><label className="query-select">Query<select aria-label="Query benchmark" value={selected} onChange={event => setSelected(event.target.value)}>{filtered.map(q => <option value={q.query_id} key={q.query_id}>{q.query_id} · {q.query}</option>)}</select></label></div>
      {query && <section className="research-panel benchmark-query"><div className="research-body"><div className="benchmark-query-heading"><span className="source-chip">{query.review_status === 'approved' ? 'Definisi disetujui' : 'Perlu ditinjau'}</span><span>{query.category} · {query.split}</span></div><h2>{query.query}</h2><p>{query.intent_note}</p><p className="research-secondary">Group: <code>{query.group_id}</code>. Parafrasa terkait tetap berada di split yang sama.</p>
        <div className="research-actions"><button className="white-button" disabled={!annotator || busy || query.review_status === 'approved'} onClick={() => act(async () => { await api(`/benchmark/queries/${selected}/review`, { method: 'PUT', body: JSON.stringify({ annotator }) }); await loadSummary() })}><ClipboardCheck size={17} />Setujui definisi query</button><button className="text-button" onClick={() => onSearch(query.query)}><Search size={17} />Buka pencarian biasa</button></div>
        <p className="research-secondary">Pastikan maksudnya jelas sebelum menyetujui. Koreksi definisi draft melalui file evaluation/queries.draft.jsonl; perubahan definisi/corpus membuat versi penilaian baru.</p>
      </div></section>}
      {loading ? <div className="research-loading"><LoaderCircle className="spin" size={24} />Memuat kandidat…</div> : pool && <>
        <div className="research-toolbar"><div><strong>Pool kandidat</strong><p className="research-secondary">{query?.judged_count || 0} / {pool.candidates.length} lagu dinilai · {query?.conflicts || 0} konflik antarpenilai</p></div><label>Kandidat per metode<select aria-label="Kedalaman pool" value={depth} onChange={event => setDepth(Number(event.target.value))}>{[5, 10, 20].map(value => <option key={value}>{value}</option>)}</select></label><button className="white-button" disabled={busy} onClick={() => act(async () => {
          await api(`/benchmark/queries/${selected}/pool`, { method: 'POST', body: JSON.stringify({ depth }) }); await loadSummary(); setRevision(r => r + 1)
        })}>{busy ? <LoaderCircle className="spin" size={17} /> : <ClipboardCheck size={17} />}{pool.prepared ? 'Perbarui pool' : 'Siapkan pool kandidat'}</button></div>
        <p className="research-secondary">Kandidat menggabungkan hasil metode, hint sumber, dan sampel acak. Urutan diacak; skor dan asal metode disembunyikan agar penilaian lebih independen. Nilai tidak terisi otomatis.</p>
        {!annotator && <p className="warning-banner">Isi nama penilai dan tekan “Gunakan nama” sebelum memberikan nilai.</p>}
        {pool.candidates.map(track => <article className="annotation-card" key={track.track_id}>
          <header><Artwork track={track} /><div><h3>{track.title}</h3><p>{track.artist}</p><small>{track.album}</small></div><a href={spotifyUrl(track)} target="_blank" rel="noreferrer">Buka Spotify</a></header>
          <div className="annotation-audio">{Object.entries(track.audio).filter(([, value]) => value != null).map(([key, value]) => <span key={key}>{key}: {value?.toFixed(key === 'tempo' ? 1 : 2)}</span>)}</div>
          <details className="annotation-lyrics"><summary>Baca lirik sumber</summary><p>{track.lyrics || 'Lirik tidak tersedia.'}</p></details>
          <div className="grade-buttons" role="group" aria-label={`Nilai relevansi ${track.title}`}>{grades.map((label, grade) => <button key={grade} className={track.judgment?.grade === grade ? 'grade-selected' : ''} aria-pressed={track.judgment?.grade === grade} aria-label={`${label} — ${track.title}`} disabled={!annotator || busy} onClick={() => judge(track.track_id, grade)}>{label}</button>)}</div>
          <label className="annotation-notes">Catatan untuk {track.title}<textarea aria-label={`Catatan untuk ${track.title}`} maxLength={2000} value={notes[track.track_id] || ''} onChange={event => setNotes(previous => ({ ...previous, [track.track_id]: event.target.value }))} placeholder="Catatan tersimpan saat memilih nilai." /></label>
          <p className="research-secondary">{track.judgment ? `Nilai kamu: ${track.judgment.grade} · tersimpan di backend` : 'Belum kamu nilai'}</p>
        </article>)}
        {pool.prepared && <section className="research-panel"><div className="research-body"><h2>Ekspor untuk evaluasi</h2><p>Selesaikan seluruh pool, setujui query, dan pastikan konflik antarpenilai sudah diselesaikan. Minimal satu lagu relevan diperlukan; query tanpa lagu relevan harus diaudit.</p><button className="white-button" disabled={busy || !query || query.review_status !== 'approved' || query.judged_count < query.pool_count || query.conflicts > 0} onClick={() => act(async () => setBundle(await api<ExportBundle>(`/benchmark/export?split=${split}&query_id=${encodeURIComponent(selected)}`)))}><Download size={17} />Siapkan ekspor query ini</button>{bundle && <div className="research-actions"><button className="green-button" onClick={() => download('queries.jsonl', bundle.queries_jsonl, 'application/x-ndjson')}>Unduh queries.jsonl</button><button className="green-button" onClick={() => download('qrels.csv', bundle.qrels_csv, 'text/csv')}>Unduh qrels.csv</button><button className="text-button" onClick={() => download('benchmark-manifest.json', JSON.stringify(bundle.manifest, null, 2))}>Unduh manifest</button></div>}<p className="research-secondary">Untuk mengekspor semua query suatu split, gunakan CLI benchmark-export setelah semua query selesai ditinjau/dinilai.</p></div></section>}
      </>}
    </>}
  </div>
}
