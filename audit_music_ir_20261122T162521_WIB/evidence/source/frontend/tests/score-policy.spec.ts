import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

test('filter audit explains constant scores and exports the actual order policy', async ({ page }) => {
  const track = { track_id: 'a', title: 'A Fast Song', artist: 'Artist', album: '', album_id: '', duration_ms: 100000,
    popularity: 90, release_date: '', genres: ['pop'], lyrics_available: false, audio: { tempo: 140 } }
  const ranking = { score_kind: 'eligibility', score_label: 'Indikator memenuhi syarat',
    score_meaning: 'Nilai 1 berarti seluruh syarat pencarian terpenuhi. Bukan akurasi 100%.',
    order_by: ['score_desc', 'popularity_desc', 'track_id_asc'], order_label: 'Kecocokan, lalu popularitas dataset; ID untuk nilai seri.' }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path === '/api/health') data = { documents: 1, semantic_ready: false, default_mode: 'AUTO' }
    else if (path === '/api/catalog') data = { tracks: [track], total: 1, genres: [] }
    else data = { results: [{ ...track, score: 1 }], ranking, warnings: [], latency_ms: 1,
      pipeline: { lexical: false, semantic: false, audio: true, degraded: false },
      trace: { decisions: { ranking, query_plan: { effective_type: 'audio', text_query: '', semantic_query: null },
        stages: { retrieved_unique: 1, selected_candidates: 1, audio_filtered: 0 },
        timings_ms: {}, text_weights: {}, manifest: { model_name: 'fixture', corpus_sha256: 'corpus', implementation_sha256: 'code' },
        candidates: [{ track_id: 'a', title: track.title, artist: track.artist, sources: { audio: 1 },
          final_rank: 1, rank_before_reranking: 1, displayed: true, disposition: 'ranked', score: 1,
          ordering_values: { popularity: 90 }, contributions: { audio: 1 }, failed_constraints: [] }], score_note: ranking.score_meaning } } }
    await route.fulfill({ json: data })
  })
  await page.goto('/?q=tempo%20%3E%20120%20BPM')
  await expect(page.locator('.result-info')).toContainText('Pencarian audio')
  await expect(page.locator('.result-info')).not.toContainText('Pencarian kata kunci')
  await page.locator('.diagnostics-panel > summary').click()
  await page.getByRole('button', { name: 'Lihat jejak', exact: true }).click()
  await expect(page.locator('.decision-plan')).toContainText('Bukan akurasi 100%')
  await expect(page.locator('.decision-plan')).toContainText('popularitas dataset')
  await expect(page.locator('.decision-score')).toHaveText('Memenuhi syarat')
  await expect(page.locator('.research-table')).toContainText('Indikator: 1.0000')
  await expect(page.locator('.research-table')).toContainText('Popularitas: 90')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Unduh JSON', exact: true }).click()
  const saved = JSON.parse(await readFile((await (await download).path())!, 'utf8'))
  expect(saved.results[0].score).toBe(1)
  expect(saved.trace.decisions.ranking.order_by).toContain('popularity_desc')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
