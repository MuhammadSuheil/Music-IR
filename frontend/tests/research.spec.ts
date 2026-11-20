import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const tracks = [
  { track_id: 'a', title: 'Stay', artist: 'Alice', album: 'First', album_id: '', duration_ms: 180000, popularity: 80,
    release_date: '2020', genres: ['pop'], lyrics_available: true, spotify_url: 'https://open.spotify.com/track/a',
    audio: { tempo: 100, energy: .2 }, lyrics: 'stay with me forever' },
  { track_id: 'b', title: 'Goodbye', artist: 'Bob', album: 'Second', album_id: '', duration_ms: 200000, popularity: 75,
    release_date: '2021', genres: ['pop'], lyrics_available: true, spotify_url: 'https://open.spotify.com/track/b',
    audio: { tempo: 140, energy: .9 }, lyrics: 'a different story' },
]

async function mockResearch(page: Page) {
  let prepared = false
  let approved = false
  const judgments: Record<string, { grade: number; notes: string }> = {}
  const query = () => ({ query_id: 'title-001', query: 'Stay', category: 'title', split: 'dev', group_id: 'stay',
    intent_note: 'Cari lagu dengan judul Stay.', review_status: approved ? 'approved' : 'draft',
    pool_count: prepared ? 2 : 0, judged_count: Object.keys(judgments).length, conflicts: 0 })
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    let data: unknown
    if (url.pathname === '/api/health') data = { documents: 2, semantic_ready: true, default_mode: 'AUTO' }
    else if (url.pathname === '/api/catalog') data = { tracks, total: 2, genres: [{ name: 'pop', count: 2 }] }
    else if (url.pathname === '/api/benchmark') data = { queries: [query()], total: 1, approved: approved ? 1 : 0,
      judgments: Object.keys(judgments).length, dataset_sha256: 'fixture', rubric: {}, note: 'Human only' }
    else if (url.pathname.endsWith('/pool')) { prepared = true; data = { pool_count: 2 } }
    else if (url.pathname.endsWith('/review')) { approved = true; data = { review_status: 'approved' } }
    else if (url.pathname.endsWith('/judgments')) {
      const body = request.postDataJSON()
      judgments[body.track_id] = { grade: body.grade, notes: body.notes }
      data = body
    } else if (url.pathname === '/api/benchmark/export') data = {
      queries_jsonl: JSON.stringify({ ...query(), review_status: 'approved' }) + '\n',
      qrels_csv: 'query_id,track_id,relevance,annotator\ntitle-001,a,3,human\ntitle-001,b,0,human\n', manifest: { human: true },
    }
    else if (url.pathname === '/api/benchmark/queries/title-001') data = { query: query(), prepared,
      candidates: prepared ? tracks.map(track => ({ ...track, judgment: judgments[track.track_id] || null })) : [] }
    else if (url.pathname === '/api/search') {
      const body = request.postDataJSON()
      const decisions = { query_plan: { planned_type: 'text', effective_type: 'text', text_query: 'Stay', semantic_query: 'Stay' },
        stages: { corpus: 2, sources: { lexical: 1, semantic: 2 }, retrieved_unique: 2, audio_filtered: 0, selected_candidates: 2, displayed: 2 },
        timings_ms: { lexical: 1, model_loading: 0 }, text_weights: {}, audio_weight: 0,
        manifest: { corpus_sha256: 'corpus', implementation_sha256: 'implementation', model_name: 'fixture', model_revision: 'fixture' },
        candidates: [{ track_id: 'a', title: 'Stay', artist: 'Alice', sources: { lexical: 1, semantic: 2 },
          rank_before_reranking: 2, final_rank: 1, displayed: true, disposition: 'ranked', score: .8,
          contributions: { bm25_normalized: .3, cosine_normalized: .5 }, features: {}, failed_constraints: [] }],
        target: body.inspect_track_id ? { track_id: body.inspect_track_id, disposition: 'not_in_corpus' } : null,
        score_note: 'Skor bukan probabilitas.' }
      data = { query: body.query, results: tracks, candidate_count: 2, latency_ms: 2, warnings: [],
        pipeline: { semantic: true, audio: false, degraded: false }, ...(body.trace ? { trace: { decisions } } : {}) }
    } else data = tracks[0]
    await route.fulfill({ json: data })
  })
}

test.beforeEach(async ({ page }) => { await mockResearch(page) })

test('diagnostics are opt-in, inspect missing targets, and export the full trace', async ({ page }) => {
  let traced = 0
  page.on('request', request => {
    if (request.url().endsWith('/api/search') && request.postDataJSON().trace) traced++
  })
  await page.goto('/?q=Stay')
  await expect(page.getByText('2 lagu ditemukan', { exact: true })).toBeVisible()
  expect(traced).toBe(0)
  await page.locator('.diagnostics-panel > summary').click()
  await page.getByRole('textbox', { name: 'Lagu target diagnostik' }).fill('missing')
  await page.getByRole('button', { name: 'Lihat jejak', exact: true }).click()
  await expect(page.locator('.target-verdict')).toContainText('Tidak ada di corpus')
  await expect(page.locator('.research-table')).toContainText('lexical #1')
  await page.getByText('Kontribusi skor', { exact: true }).click()
  await expect(page.locator('.score-details')).toContainText('0.5000')
  const event = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Unduh JSON', exact: true }).click()
  const file = await event
  const body = JSON.parse(await readFile((await file.path())!, 'utf8'))
  expect(body.trace.decisions.target.track_id).toBe('missing')
  expect(traced).toBe(1)
})

test('benchmark has no automatic grades and human reviews persist after reload', async ({ page }) => {
  await page.goto('/?view=benchmark')
  await expect(page.getByRole('heading', { name: 'Benchmark & penilaian' })).toBeVisible()
  await page.getByRole('button', { name: 'Siapkan pool kandidat', exact: true }).click()
  const grade = page.getByRole('button', { name: '3 · Sangat relevan — Stay', exact: true })
  await expect(grade).toBeDisabled()
  await expect(page.locator('.grade-selected')).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Nama penilai', exact: true }).fill('human')
  await page.getByRole('button', { name: 'Gunakan nama', exact: true }).click()
  await expect(grade).toBeEnabled()
  await page.getByRole('button', { name: 'Setujui definisi query', exact: true }).click()
  await grade.click()
  await expect(page.getByRole('button', { name: 'Siapkan ekspor query ini', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '0 · Tidak relevan — Goodbye', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Siapkan ekspor query ini', exact: true })).toBeEnabled()
  await page.reload()
  await expect(page.getByRole('button', { name: '3 · Sangat relevan — Stay', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Siapkan ekspor query ini', exact: true }).click()
  const event = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Unduh qrels.csv', exact: true }).click()
  expect(await (await event).suggestedFilename()).toBe('qrels.csv')
})

test('benchmark is reachable from settings and fits a mobile viewport', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Pengaturan pencarian', exact: true }).click()
  await page.getByRole('button', { name: 'Benchmark & penilaian', exact: true }).click()
  await expect(page).toHaveURL(/view=benchmark/)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Siapkan pool kandidat', exact: true }).click()
  await expect(page.getByRole('button', { name: '3 · Sangat relevan — Stay', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('main').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
})
