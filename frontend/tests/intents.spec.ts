import { expect, test } from '@playwright/test'

test('verified lyric hits and related tracks are separate and both remain playable', async ({ page }) => {
  const direct = { track_id: 'direct', title: 'The Lyric Match', artist: 'Alice', album: 'First', album_id: '',
    duration_ms: 180000, popularity: 80, release_date: '2020', genres: ['pop'], lyrics_available: true,
    audio: {}, snippet: 'when i see your face', snippet_type: 'lexical', lyric_match: { kind: 'exact', similarity: 1 } }
  const related = { ...direct, track_id: 'related', title: 'Another Face', artist: 'Bob', lyric_match: null }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = path.endsWith('/health') ? { documents: 2, semantic_ready: true, default_mode: 'AUTO' } :
      path.endsWith('/catalog') ? { tracks: [direct, related], total: 2, genres: [] } :
        { results: [direct], related_results: [related], result_policy: { primary: 'direct' },
          warnings: [], latency_ms: 1, pipeline: { semantic: true, audio: false, degraded: false } }
    await route.fulfill({ json })
  })
  await page.goto('/?q=when%20i%20see%20your%20face')
  await expect(page.getByRole('heading', { name: 'Kecocokan langsung', exact: true })).toBeVisible()
  await expect(page.locator('.songs-section').first()).toContainText('The Lyric Match')
  await expect(page.locator('.songs-section').first()).not.toContainText('Another Face')
  await expect(page.locator('.related-results')).toContainText('Another Face')
  await expect(page.locator('.result-info')).toContainText('1 lagu ditemukan · 1 hasil serupa')
  await page.locator('.related-results tbody tr').first().hover()
  await page.locator('.related-results').getByRole('button', { name: 'Dengarkan Another Face', exact: true }).click()
  await expect(page.locator('iframe')).toHaveAttribute('src', /track\/related/)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('genre results explain playlist labels and show the catalog search type', async ({ page }) => {
  const track = { track_id: 'rock', title: 'A Rock Track', artist: 'Artist', album: '', album_id: '',
    duration_ms: 100000, popularity: 70, release_date: '', genres: ['rock'], lyrics_available: true, audio: {} }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = path.endsWith('/health') ? { documents: 1, semantic_ready: false, default_mode: 'AUTO' } :
      path.endsWith('/catalog') ? { tracks: [track], total: 1, genres: [] } :
        { results: [track], related_results: [], result_policy: { primary: 'direct', genre_source: 'playlist_genre' },
          catalog_match: { kind: 'genre', value: 'rock', method: 'exact', similarity: 1, source: 'playlist_genre' },
          warnings: [], latency_ms: 1, pipeline: { semantic: false, audio: false, degraded: false } }
    await route.fulfill({ json })
  })
  await page.goto('/?q=rock%20song')
  await expect(page.locator('.result-info')).toContainText('Pencarian genre')
  await expect(page.getByText('Genre mengikuti label playlist pada koleksi; beberapa lagu memiliki lebih dari satu label.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Hasil serupa', exact: true })).toHaveCount(0)
})
