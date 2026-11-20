import { useState } from 'react'
import { Bug, Download, LoaderCircle } from 'lucide-react'
import { api, type SearchResult } from './lib'
import { download, type Decisions, type DecisionRow } from './research'

const disposition: Record<string, string> = { ranked: 'Masuk hasil', audio_filtered: 'Gugur: batas audio', intent_filtered: 'Gugur: artis/judul/genre berbeda',
  candidate_limit: 'Gugur: batas kandidat', not_retrieved: 'Tidak terambil', not_in_corpus: 'Tidak ada di corpus' }
const number = (value: number | null | undefined) => value == null ? '—' : value.toFixed(4)

export default function DiagnosticsPanel({ query, mode, moodBasis }: { query: string; mode: string; moodBasis?: string }) {
  const [decisions, setDecisions] = useState<Decisions | null>(null)
  const [response, setResponse] = useState<unknown>(null)
  const [target, setTarget] = useState('')
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function inspect(event?: React.FormEvent) {
    event?.preventDefault(); setBusy(true); setError('')
    try {
      const trackId = target.match(/track\/([A-Za-z0-9]+)/)?.[1] || target.trim()
      const data = await api<SearchResult & { trace?: { decisions: Decisions } }>('/search', { method: 'POST',
        body: JSON.stringify({ query, mode, top_k: 30, trace: true, inspect_track_id: trackId || undefined, mood_basis: moodBasis }) })
      if (!data.trace?.decisions) throw new Error('Backend belum menyediakan jejak keputusan. Muat ulang backend.')
      setDecisions(data.trace.decisions); setResponse(data)
    } catch (exc) { setError(exc instanceof Error ? exc.message : 'Jejak belum dapat dimuat.') }
    finally { setBusy(false) }
  }
  const rows = decisions?.candidates.filter(row => `${row.title} ${row.artist} ${row.track_id}`.toLowerCase().includes(filter.toLowerCase())) || []
  return <details className="research-panel diagnostics-panel">
    <summary><Bug size={18} />Jejak keputusan pencarian<span>Untuk audit dan eksperimen</span></summary>
    <div className="research-body">
      <p>Periksa sumber kandidat, urutan sebelum/sesudah, dan kontribusi skor. Pengambilan jejak menjalankan ulang query dengan konfigurasi yang sama.</p>
      <form className="research-form" onSubmit={inspect}>
        <label>ID atau tautan Spotify lagu yang ingin diperiksa (opsional)<input aria-label="Lagu target diagnostik" value={target} onChange={event => setTarget(event.target.value)} placeholder="ID lagu atau https://open.spotify.com/track/…" maxLength={200} /></label>
        <button className="white-button" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Bug size={17} />}Lihat jejak</button>
      </form>
      {error && <p className="research-error" role="alert">{error}</p>}
      {decisions && <>
        <div className="research-stats"><span>Jenis: <strong>{decisions.query_plan.effective_type}</strong></span><span>Terambil: <strong>{decisions.stages.retrieved_unique}</strong></span><span>Gugur audio: <strong>{decisions.stages.audio_filtered}</strong></span><span>Kandidat akhir: <strong>{decisions.stages.selected_candidates}</strong></span></div>
        <dl className="decision-plan">{decisions.ranking && <><dt>Arti skor</dt><dd>{decisions.ranking.score_meaning}</dd><dt>Dasar urutan</dt><dd>{decisions.ranking.order_label}</dd></>}<dt>Teks pencarian</dt><dd>{decisions.query_plan.text_query || 'Audio murni'}</dd><dt>Teks untuk encoder</dt><dd>{decisions.query_plan.semantic_query || 'Tidak digunakan'}</dd></dl>
        {decisions.target && <div className="target-verdict" role="status"><strong>Target: {decisions.target.title || decisions.target.track_id}</strong><span>{disposition[decisions.target.disposition]}{decisions.target.final_rank ? ` · urutan ${decisions.target.final_rank}` : ''}</span></div>}
        <div className="research-toolbar"><input aria-label="Filter kandidat diagnostik" placeholder="Filter judul, artis, atau ID" value={filter} onChange={event => setFilter(event.target.value)} /><button className="text-button" onClick={() => download('search-trace.json', JSON.stringify(response, null, 2))}><Download size={16} />Unduh JSON</button></div>
        <div className="research-table-wrap"><table className="research-table"><thead><tr><th>Lagu</th><th>Sumber / posisi</th><th>Sebelum</th><th>Sesudah</th><th>Keputusan & skor</th></tr></thead><tbody>{rows.map(row => <tr key={row.track_id}>
          <td><strong>{row.title}</strong><small>{row.artist}</small><code>{row.track_id}</code></td>
          <td>{Object.entries(row.sources).map(([name, rank]) => <span className="source-chip" key={name}>{name} #{rank}</span>)}</td>
          <td>{row.rank_before_reranking || '—'}</td><td>{row.final_rank || '—'}{row.final_rank && !row.displayed ? <small>Di luar 30 hasil UI</small> : null}</td>
          <td><span>{disposition[row.disposition]}</span>{row.displayed_group === 'related' && <small>Ditampilkan sebagai hasil serupa</small>}<strong className="decision-score">{decisions.ranking?.score_kind === 'eligibility' && row.score != null ? 'Memenuhi syarat' : number(row.score)}</strong>{decisions.ranking?.score_kind === 'eligibility' && row.score != null && <small>Indikator: {number(row.score)}; Popularitas: {row.ordering_values?.popularity ?? 'tidak tersedia'}</small>}{row.failed_constraints.map((constraint, i) => <small key={i}>{constraint.feature} {constraint.operator} {constraint.bound}; nilai: {constraint.value ?? 'hilang'}</small>)}<Contributions row={row} />{row.theme_evidence && <details className="passage-evidence"><summary>Bukti bagian lirik</summary><p>{row.theme_evidence.text}</p><small>Cosine tema: {number(row.theme_evidence.cosine)}</small>{row.theme_evidence.counter_cosine != null && <><small>Cosine tema pembanding: {number(row.theme_evidence.counter_cosine)}</small><p>{row.theme_evidence.counter_themes?.join(' ')}</p></>}</details>}</td>
        </tr>)}</tbody></table></div>
        <details className="research-manifest"><summary>Waktu dan identitas eksperimen</summary><p>{decisions.score_note}</p><dl>{Object.entries(decisions.timings_ms).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value.toFixed(1)} ms</dd></div>)}</dl><p>Model: {decisions.manifest.model_name}</p><p>Corpus: <code>{decisions.manifest.corpus_sha256}</code></p><p>Implementasi: <code>{decisions.manifest.implementation_sha256}</code></p></details>
      </>}
    </div>
  </details>
}

function Contributions({ row }: { row: DecisionRow }) {
  if (!Object.keys(row.contributions).length) return null
  return <details className="score-details"><summary>Kontribusi skor</summary><dl>{Object.entries(row.contributions).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{number(value)}</dd></div>)}</dl></details>
}
