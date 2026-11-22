import { useEffect, useState } from 'react'
import { api } from './lib'
import './relevance.css'

type Counts = { run_id: string; query_count: number; pairs: number; auto_processed: number; auto_completed: number;
  auto_unprocessed: number; auto_errors: number; auto_needs_review: number; human_final_pairs: number; pool_complete: boolean;
  auto_complete: boolean; human_complete: boolean }
type Query = { query_id: string; query: string; user_need: string; category: string; split: string; definition_approved: boolean;
  pool_count: number; final_count: number }
type Summary = Counts & { queries: Query[]; human_review_required?: boolean; automatic_label_source?: string }
type Review = { human_grade: number | null; final_grade: number | null; human_review_status: string; reason: string; updated: string; viewed_auto: number }
type Candidate = { track_id: string; title: string; artist: string; album: string; lyrics: string; genres: string[];
  audio: Record<string, number | null>; numeric_checks: { field: string; operator: string; bound: number; observed: number | null; passed: boolean | null }[];
  auto_available: boolean; review: Review | null; draft: { grade: number | null; reason: string } | null }
type Pool = { candidates: Candidate[]; total: number; offset: number }
type Proposal = { proposal: { auto_grade: number | null; reason: string; evidence: { field: string; quote: string }[];
  uncertainty_flags: string[]; provider: string; model: string | null }; status: string }
const labels = ['0 · Tidak relevan', '1 · Sedikit relevan', '2 · Relevan', '3 · Sangat relevan']

export default function RelevancePage() {
  const [runs, setRuns] = useState<Counts[]>([])
  const [runId, setRunId] = useState('')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [qid, setQid] = useState('')
  const [split, setSplit] = useState('dev')
  const [pool, setPool] = useState<Pool | null>(null)
  const [offset, setOffset] = useState(0)
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem('music-ir-relevance-reviewer') || '' } catch { return '' } })
  const [name, setName] = useState(reviewer)
  const [grade, setGrade] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [saveStatus, setSaveStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const [exportInfo, setExportInfo] = useState<{ final_query_ids: string[]; qrels_final_available: boolean } | null>(null)
  const [newQuery, setNewQuery] = useState('')
  const [newNeed, setNewNeed] = useState('')
  const [revisionReason, setRevisionReason] = useState('')
  const candidate = pool?.candidates[0]
  const query = summary?.queries.find(q => q.query_id === qid)
  const filtered = summary?.queries.filter(q => q.split === split) || []
  const automaticOnly = summary?.human_review_required === false
  const base = `/relevance/runs/${encodeURIComponent(runId)}`
  const pairBase = `${base}/queries/${encodeURIComponent(qid)}/tracks/${encodeURIComponent(candidate?.track_id || '')}`

  useEffect(() => {
    api<{ runs: Counts[] }>('/relevance/runs').then(data => { setRuns(data.runs); setRunId(data.runs[0]?.run_id || '') }).catch(e => setError(e.message))
  }, [])
  useEffect(() => {
    if (!runId) return
    const controller = new AbortController()
    api<Summary>(base, { signal: controller.signal }).then(setSummary).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [runId, revision])
  useEffect(() => {
    if (filtered.length && !filtered.some(q => q.query_id === qid)) { setQid(filtered[0].query_id); setOffset(0) }
  }, [summary, split, qid])
  useEffect(() => {
    if (!runId || !qid) return
    const controller = new AbortController()
    setLoading(true); setPool(null); setProposal(null); setSaveStatus(''); setExportInfo(null)
    api<Pool>(`${base}/queries/${encodeURIComponent(qid)}?offset=${offset}&limit=1&reviewer_id=${encodeURIComponent(reviewer)}`, { signal: controller.signal })
      .then(data => { setPool(data); const c = data.candidates[0]; setGrade(c?.draft?.grade ?? c?.review?.human_grade ?? null); setReason(c?.draft?.reason ?? c?.review?.reason ?? '') })
      .catch(e => { if (!controller.signal.aborted) setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [runId, qid, offset, reviewer, revision])
  useEffect(() => { setNewQuery(query?.query || ''); setNewNeed(query?.user_need || ''); setRevisionReason('') }, [qid, query?.query, query?.user_need])
  useEffect(() => {
    if (!candidate || !reviewer || loading) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setSaveStatus('Menyimpan draft…')
      api(`${pairBase}/draft`, { method: 'PUT', signal: controller.signal, body: JSON.stringify({ reviewer_id: reviewer, grade, reason }) })
        .then(() => setSaveStatus('Draft tersimpan · belum menjadi grade final'))
        .catch(e => { if (!controller.signal.aborted) setSaveStatus(`Draft gagal tersimpan: ${e.message}`) })
    }, 500)
    return () => { clearTimeout(timer); controller.abort() }
  }, [candidate?.track_id, runId, qid, reviewer, grade, reason, loading])

  async function act(fn: () => Promise<void>) {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : 'Permintaan gagal') }
    finally { setBusy(false) }
  }
  async function decide(action: string) {
    await act(async () => {
      await api(`${pairBase}/review`, { method: 'PUT', body: JSON.stringify({ reviewer_id: reviewer, action, grade, reason, expected_updated: candidate?.review?.updated || null }) })
      setRevision(r => r + 1)
    })
  }
  async function move(change: () => void) {
    await act(async () => {
      if (candidate && reviewer) await api(`${pairBase}/draft`, { method: 'PUT', body: JSON.stringify({ reviewer_id: reviewer, grade, reason }) })
      change()
    })
  }
  return <div className="page-content relevance-page">
    <p className="eyebrow">EVALUASI RELEVANSI</p><h1>{automaticOnly ? 'Evaluasi otomatis untuk laporan' : 'Review label awal LLM'}</h1>
    <p className="page-description">{automaticOnly ? 'Ekspor hasil evaluasi otomatis tanpa persetujuan manusia. Makna lirik dinilai agent LLM; metadata, kutipan, dan angka diperiksa dari corpus. Sumber label dan nilai yang belum dapat ditentukan tetap dicatat.' : 'Baca bukti dan beri penilaian awal tanpa melihat usulan. Label otomatis, keputusan manusia, dan hasil final disimpan terpisah. Semua pasangan tetap masuk antrean, termasuk nilai 0 dan 1.'}</p>
    {error && <p className="research-error" role="alert">{error}</p>}
    <label className="relevance-run">Run evaluasi<select aria-label="Run evaluasi" value={runId} disabled={busy} onChange={e => { const value = e.target.value; void move(() => { setRunId(value); setQid(''); setOffset(0); setSummary(null) }) }}>{runs.map(r => <option key={r.run_id}>{r.run_id}</option>)}</select></label>
    {!runs.length && <p>Belum ada run evaluasi yang dibekukan.</p>}
    {summary && <>
      <div className="research-stats"><span>Pool: <strong>{summary.pairs}</strong> pasangan</span><span>Otomatis diproses: <strong>{summary.auto_processed}</strong></span><span>Belum diproses: <strong>{summary.auto_unprocessed}</strong></span><span>{automaticOnly ? 'Belum dapat ditentukan' : 'Butuh review/gagal'}: <strong>{summary.auto_needs_review + summary.auto_errors}</strong></span>{!automaticOnly && <span>Final manusia: <strong>{summary.human_final_pairs}</strong></span>}</div>
      <p className="research-secondary">Pool {summary.pool_complete ? 'selesai' : 'masih diproses'} · tahap otomatis {summary.auto_complete ? 'seluruh pasangan telah diproses' : 'belum selesai'} · {automaticOnly ? 'review manusia tidak diwajibkan' : `review manusia ${summary.human_complete ? 'selesai' : 'belum selesai'}`}. Metrik otomatis bersifat provisional.</p>
      {automaticOnly ? <section className="research-panel automatic-export"><div className="research-body"><h2>Ekspor hasil otomatis</h2><p>Tidak perlu nama reviewer, persetujuan query, atau keputusan manusia. Label ini adalah penilaian otomatis, bukan ground truth manusia. Angka dengan judgment belum lengkap ditandai secara eksplisit.</p><p>{summary.automatic_label_source}</p><button className="white-button" disabled={busy} onClick={() => act(async () => setExportInfo(await api(`${base}/export`, { method: 'POST' })))}>Hitung dan ekspor hasil otomatis</button>{exportInfo && <div className="research-actions">{['LAPORAN_EVALUASI_RELEVANSI.md', 'TEKS_SIAP_LAPORAN.md', 'qrels_auto.tsv', 'metrics_auto_per_query.csv', 'metrics_auto_summary.json', 'auto_labels.jsonl', 'unresolved_pairs.csv'].map(file => <a className="text-button" key={file} href={`/api${base}/export?name=${file}`} download>{file}</a>)}</div>}</div></section> : <>
      <form className="research-form" onSubmit={e => { e.preventDefault(); const value = name.trim(); if (!/^\w[\w .-]{0,63}$/.test(value)) { setError('Kode reviewer 1–64 karakter, diawali huruf/angka.'); return } setReviewer(value); try { localStorage.setItem('music-ir-relevance-reviewer', value) } catch { /* session only */ } }}>
        <label>Kode reviewer<input aria-label="Kode reviewer" maxLength={64} value={name} onChange={e => setName(e.target.value)} /></label><button className="white-button">Gunakan reviewer</button>{reviewer && <span>Aktif: {reviewer}</span>}
      </form>
      <div className="relevance-filters"><label>Split<select aria-label="Split review" value={split} disabled={busy} onChange={e => { const value = e.target.value; void move(() => { setSplit(value); setOffset(0) }) }}><option value="dev">Development</option><option value="test">Test</option></select></label><label>Query<select aria-label="Query review" value={qid} disabled={busy} onChange={e => { const value = e.target.value; void move(() => { setQid(value); setOffset(0) }) }}>{filtered.map(q => <option value={q.query_id} key={q.query_id}>{q.query_id} · {q.query}</option>)}</select></label></div>
      {query && <section className="research-panel"><div className="research-body"><h2>{query.query}</h2><p>{query.user_need}</p><p>{query.final_count} / {query.pool_count} pasangan final · definisi {query.definition_approved ? 'disetujui manusia' : 'masih perlu ditinjau'}</p>
        <button className="white-button" disabled={!reviewer || busy || query.definition_approved} onClick={() => act(async () => { await api(`${base}/queries/${qid}/definition`, { method: 'PUT', body: JSON.stringify({ reviewer_id: reviewer, approved: true }) }); setRevision(r => r + 1) })}>Setujui kebutuhan query</button>
        <details className="relevance-revision"><summary>Revisi query atau kebutuhan sebagai versi baru</summary><p>Perubahan membuat run baru dan memerlukan pooling serta penilaian ulang. Label lama tetap tersimpan.</p><label>Query baru<textarea value={newQuery} onChange={e => setNewQuery(e.target.value)} maxLength={2000} /></label><label>Kebutuhan baru<textarea value={newNeed} onChange={e => setNewNeed(e.target.value)} maxLength={4000} /></label><label>Alasan revisi<textarea value={revisionReason} onChange={e => setRevisionReason(e.target.value)} maxLength={4000} /></label><button className="white-button" disabled={!reviewer || busy || !revisionReason.trim()} onClick={() => act(async () => { const data = await api<{ new_run_id: string }>(`${base}/queries/${qid}/revision`, { method: 'POST', body: JSON.stringify({ reviewer_id: reviewer, query: newQuery, user_need: newNeed, reason: revisionReason }) }); const list = await api<{ runs: Counts[] }>('/relevance/runs'); setRuns(list.runs); setRunId(data.new_run_id); setQid(''); setOffset(0) })}>Buat versi baru</button></details>
      </div></section>}
      {loading && <p role="status">Memuat kandidat…</p>}
      {pool && <nav className="relevance-navigation" aria-label="Antrean review"><button className="white-button" disabled={offset === 0 || busy} onClick={() => void move(() => setOffset(o => o - 1))}>Sebelumnya</button><span>{pool.total ? offset + 1 : 0} / {pool.total} kandidat · urutan penilaian diacak</span><button className="white-button" disabled={offset + 1 >= pool.total || busy} onClick={() => void move(() => setOffset(o => o + 1))}>Berikutnya</button></nav>}
      {candidate && <article className="annotation-card" key={candidate.track_id}>
        <h2>{candidate.title}</h2><p>{candidate.artist} · {candidate.album}</p><code>{candidate.track_id}</code><p>Label genre playlist: {candidate.genres.join(', ') || 'tidak tersedia'}</p>
        <div className="annotation-audio">{Object.entries(candidate.audio).map(([k, v]) => <span key={k}>{k}: {v ?? 'tidak tersedia'}</span>)}</div>
        {!!candidate.numeric_checks.length && <div className="relevance-numeric"><h3>Pemeriksaan angka eksplisit</h3>{candidate.numeric_checks.map((c, i) => <p key={i}>{c.field} {c.operator} {c.bound}; nilai {c.observed ?? 'hilang'} · {c.passed == null ? 'tidak diketahui' : c.passed ? 'memenuhi' : 'tidak memenuhi'}</p>)}<small>Dihitung langsung dari angka corpus, terpisah dari keputusan retrieval. Bukan label kebenaran tema atau mood.</small></div>}
        <h3>Lirik sumber lengkap</h3><p className="relevance-lyrics">{candidate.lyrics || 'Lirik tidak tersedia.'}</p>
        <h3>{proposal ? 'Keputusan review' : 'Penilaian awal tanpa usulan LLM'}</h3>
        <div className="grade-buttons" role="group" aria-label="Grade manusia">{labels.map((label, g) => <button key={g} aria-pressed={grade === g} className={grade === g ? 'grade-selected' : ''} disabled={!reviewer || busy} onClick={() => setGrade(g)}>{label}</button>)}</div>
        <label className="annotation-notes">Alasan / catatan koreksi<textarea aria-label="Alasan koreksi" value={reason} onChange={e => setReason(e.target.value)} maxLength={4000} /></label><p role="status" className="research-secondary">{saveStatus}</p>
        <div className="research-actions"><button className="white-button" disabled={!reviewer || busy || grade == null || !query?.definition_approved} onClick={() => decide('independent')}>Simpan grade manusia</button><button className="text-button" disabled={!reviewer || busy || !candidate.auto_available || !!proposal} onClick={() => act(async () => setProposal(await api<Proposal>(`${pairBase}/proposal`, { method: 'POST', body: JSON.stringify({ reviewer_id: reviewer }) })))}>Buka usulan LLM</button></div>
        {!candidate.auto_available && <p className="research-secondary">Pasangan ini belum dinilai LLM. Penilaian manusia mandiri tetap dapat dilakukan.</p>}
        {proposal && <aside className="relevance-proposal"><h3>Usulan awal LLM: {proposal.proposal.auto_grade ?? 'belum dapat ditentukan'}</h3><p>{proposal.proposal.reason}</p>{proposal.proposal.evidence.map((e, i) => <blockquote key={i}><small>{e.field}</small><p>{e.quote}</p></blockquote>)}<p>{proposal.proposal.uncertainty_flags.join(' · ')}</p><small>Provider: {proposal.proposal.provider} · model: {proposal.proposal.model || 'identitas persis tidak diekspos'}</small><p>Keputusan setelah membuka usulan dicatat sebagai post-editing, termasuk jika usulan disembunyikan lagi.</p><div className="research-actions"><button className="green-button" disabled={!query?.definition_approved || busy || proposal.proposal.auto_grade == null} onClick={() => decide('accept')}>Setujui label awal</button><button className="white-button" disabled={!query?.definition_approved || busy || grade == null || !reason.trim()} onClick={() => decide('correct')}>Koreksi label awal</button></div></aside>}
        <button className="text-button" disabled={!reviewer || busy || !reason.trim()} onClick={() => decide('flag')}>Tandai bermasalah</button>
        {candidate.review && <p className="research-secondary">Keputusan tersimpan: {candidate.review.human_review_status} · grade final: {candidate.review.final_grade ?? 'belum tersedia'} · {candidate.review.viewed_auto ? 'post-editing' : 'tanpa membuka usulan'}</p>}
      </article>}
      <section className="research-panel"><div className="research-body"><h2>Metrik dan ekspor per tahap</h2><p>Metrik final hanya memakai query yang disetujui dan seluruh poolnya selesai direview. Pasangan belum direview tidak menjadi label final. Perbandingan otomatis/final memakai set query dan pool yang sama.</p><button className="white-button" disabled={busy} onClick={() => act(async () => setExportInfo(await api(`${base}/export`, { method: 'POST' })))}>Hitung ulang dan siapkan ekspor</button>{exportInfo && <div className="research-actions">{['qrels_auto.tsv', 'metrics_auto_summary.json', 'metrics_final_summary.json', 'comparison.json', 'human_review_history.jsonl', ...(exportInfo.qrels_final_available ? ['qrels_final.tsv'] : [])].map(file => <a className="text-button" key={file} href={`/api${base}/export?name=${file}`} download>{file}</a>)}<p>{exportInfo.final_query_ids.length} query final lengkap. {exportInfo.qrels_final_available ? '' : 'Qrels final belum tersedia.'}</p></div>}</div></section>
      </>}
    </>}
  </div>
}
