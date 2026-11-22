import { expect, test } from '@playwright/test'

test('mood scope changes the results and resets for a new title search', async ({ page }) => {
  const sad = { track_id: 'sad', title: 'Quiet Farewell', artist: 'Alice', album: 'First', album_id: '',
    duration_ms: 180000, popularity: 80, release_date: '2020', genres: ['pop'], lyrics_available: true,
    audio: { valence: .2, energy: .4 }, snippet: 'a sad goodbye' }
  const sugar = { ...sad, track_id: 'sugar', title: 'Sugar', artist: 'Maroon 5', audio: { valence: .884, energy: .788 } }
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/health') data = { documents: 2, semantic_ready: true, default_mode: 'AUTO' }
    else if (url.pathname === '/api/catalog') data = { tracks: [sad, sugar], total: 2, genres: [] }
    else if (url.pathname === '/api/search') {
      const body = route.request().postDataJSON()
      requests.push(body)
      const basis = body.mood_basis || 'both'
      const isMood = body.query === 'lagu bermakna sedih'
      data = { query: body.query, results: isMood && basis !== 'lyrics' ? [sad] : [sugar, sad],
        candidate_count: 2, latency_ms: 2, warnings: [], pipeline: { semantic: basis !== 'audio', audio: basis !== 'lyrics', degraded: false },
        mood: isMood ? { label: 'sad', basis, audio_constraints: basis === 'lyrics' ? [] : [['valence', '<=', .5], ['energy', '<=', .65]], note: 'Perkiraan dari dataset.' } : null }
    } else data = sad
    await route.fulfill({ json: data })
  })

  await page.goto('/?q=lagu%20bermakna%20sedih')
  await expect(page.getByRole('button', { name: 'Makna + musik', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.songs-section')).not.toContainText('Sugar')
  await page.getByText('Dasar penyaringan musik', { exact: true }).click()
  await expect(page.getByRole('region', { name: 'Dasar pencarian suasana' })).toContainText('energy <= 0.65')

  await page.getByRole('button', { name: 'Makna lirik', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Makna lirik', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.songs-section')).toContainText('Sugar')
  expect(requests.at(-1)?.mood_basis).toBe('lyrics')

  await page.locator('.diagnostics-panel > summary').click()
  await page.getByRole('button', { name: 'Lihat jejak', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.trace).toBe(true)
  expect(requests.at(-1)?.mood_basis).toBe('lyrics')

  await page.getByRole('button', { name: 'Nuansa musik', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Nuansa musik', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.result-info')).toContainText('Pencarian nuansa musik')
  await expect(page.locator('.songs-section')).not.toContainText('Sugar')
  expect(requests.at(-1)?.mood_basis).toBe('audio')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('main').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)

  const search = page.getByRole('textbox', { name: 'Cari musik', exact: true })
  await search.fill('Sugar')
  await search.press('Enter')
  await expect(page.locator('.songs-section')).toContainText('Sugar')
  await expect(page.getByRole('region', { name: 'Dasar pencarian suasana' })).toHaveCount(0)
  expect(requests.at(-1)?.query).toBe('Sugar')
  expect(requests.at(-1)?.mood_basis).toBeUndefined()
})
