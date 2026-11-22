import { expect, test, type Page } from '@playwright/test'

const tracks = [
  { track_id: '2plbrEY59IikOBgBGLjaoe', title: 'Die With A Smile', artist: 'Lady Gaga, Bruno Mars', album: 'Die With A Smile', album_id: '10FLjwfpbxLmW8c25Xyc2N', duration_ms: 251668, popularity: 100, release_date: '2024-08-16', genres: ['pop'], lyrics_available: true, spotify_url: 'https://open.spotify.com/track/2plbrEY59IikOBgBGLjaoe', audio: { tempo: 157.969, energy: .592, danceability: .521, valence: .535, acousticness: .308 } },
  { track_id: '5vNRhkKd0yEAg8suGBpjeY', title: 'APT.', artist: 'ROSÉ, Bruno Mars', album: 'APT.', album_id: '2IYQwwgxgOIn7t3iF6ufFD', duration_ms: 169917, popularity: 98, release_date: '2024-10-18', genres: ['pop'], lyrics_available: true, spotify_url: 'https://open.spotify.com/track/5vNRhkKd0yEAg8suGBpjeY', audio: { tempo: 149.027, energy: .783, danceability: .777, valence: .939, acousticness: .0283 } },
  { track_id: '6dOtVTDdiauQNBQEDOtlAB', title: 'BIRDS OF A FEATHER', artist: 'Billie Eilish', album: 'HIT ME HARD AND SOFT', album_id: '7aJuG4TFXa2hmE4z1yxc3n', duration_ms: 210373, popularity: 97, release_date: '2024-05-17', genres: ['pop', 'rock'], lyrics_available: true, spotify_url: 'https://open.spotify.com/track/6dOtVTDdiauQNBQEDOtlAB', audio: { tempo: 104.978, energy: .507, danceability: .747, valence: .438, acousticness: .2 } },
]
const result = { results: tracks.map(t => ({ ...t, snippet: 'stay with me forever', snippet_type: 'lexical', reasons: ['Kecocokan kata pada judul'] })), candidate_count: 3, latency_ms: 12, warnings: [], pipeline: { semantic: true, audio: false, degraded: false } }
const genres = [{ name: 'pop', count: 3 }, { name: 'rock', count: 1 }]

async function mockApi(page: Page) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    let body: unknown
    if (url.pathname === '/api/health') body = { documents: 3, semantic_ready: true, default_mode: 'AUTO', tuned: false }
    else if (url.pathname === '/api/catalog') body = { tracks: url.searchParams.get('genre') === 'rock' ? tracks.slice(2) : tracks, total: 3, genres }
    else if (url.pathname === '/api/search') body = result
    else body = { ...tracks.find(t => url.pathname.endsWith(t.track_id)), lyrics: 'stay with me forever\nthrough the night' }
    await route.fulfill({ json: body })
  })
}

test.beforeEach(async ({ page }) => { await mockApi(page) })

test('home displays real metadata, artwork, and working genre navigation', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Temukan favorit barumu' })).toBeVisible()
  await expect(page.getByText('3 lagu untuk dijelajahi')).toBeVisible()
  await expect(page.locator('.quick-grid .quick-tile')).toHaveCount(3)
  await expect(page.locator('.quick-grid img').first()).toBeVisible()
  await page.getByRole('button', { name: /^Rock Mix/ }).click()
  await expect(page.getByRole('heading', { name: 'Rock Mix' })).toBeVisible()
  await expect(page.getByRole('table').getByRole('button', { name: 'BIRDS OF A FEATHER', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('search sends AUTO and opens song details and lyrics', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Cari musik', exact: true }).fill('Bruno Mars')
  const request = page.waitForRequest(r => r.url().endsWith('/api/search'))
  await page.getByRole('textbox', { name: 'Cari musik', exact: true }).press('Enter')
  expect((await request).postDataJSON()).toEqual({ query: 'Bruno Mars', mode: 'AUTO', top_k: 30 })
  await expect(page.getByRole('heading', { name: 'Bruno Mars', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Die With A Smile', exact: true }).first().click()
  await expect(page.getByLabel('Detail lagu').getByRole('heading', { name: 'Lirik' })).toBeVisible()
  await expect(page.getByText('through the night', { exact: false })).toBeVisible()
  await expect(page.getByText('158 BPM', { exact: true })).toBeVisible()
})

test('liked songs persist across page reload', async ({ page }) => {
  await page.goto('/?view=catalog')
  await page.getByRole('button', { name: 'Sukai Die With A Smile', exact: true }).click()
  await page.getByRole('button', { name: /Lagu yang Disukai/ }).click()
  await expect(page.getByRole('heading', { name: 'Lagu yang Disukai' })).toBeVisible()
  await expect(page.getByRole('table').getByRole('button', { name: 'Die With A Smile', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('table').getByRole('button', { name: 'Die With A Smile', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Hapus Die With A Smile dari favorit' }).click()
  await expect(page.getByRole('heading', { name: 'Semua favoritmu, satu tempat.' })).toBeVisible()
})

test('create playlist, add a song, and reopen stored playlist', async ({ page }) => {
  await page.goto('/?view=catalog')
  await page.getByRole('button', { name: 'Tambahkan Die With A Smile ke playlist' }).click()
  await page.getByRole('button', { name: 'Buat playlist baru' }).click()
  await page.getByRole('textbox', { name: 'Nama playlist' }).fill('Soundtrack Malam')
  await page.getByRole('dialog').getByRole('button', { name: 'Buat playlist', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Soundtrack Malam' })).toBeVisible()
  await expect(page.getByRole('table').getByRole('button', { name: 'Die With A Smile', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Soundtrack Malam' })).toBeVisible()
  await expect(page.getByRole('table').locator('tbody tr')).toHaveCount(1)
  await page.getByRole('button', { name: 'Tambahkan Die With A Smile ke playlist' }).click()
  await page.getByRole('button', { name: 'Hapus dari playlist ini', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Playlist ini menunggu ceritamu.' })).toBeVisible()
})

test('backend errors can be retried and unsupported backend is explained', async ({ page }) => {
  await page.route('**/api/search', route => route.fulfill({ status: 503, json: { detail: 'Layanan pencarian sedang disiapkan.' } }))
  await page.goto('/?q=test')
  await expect(page.getByRole('alert')).toContainText('Layanan pencarian sedang disiapkan.')
  await page.unroute('**/api/search')
  await page.getByRole('button', { name: 'Coba lagi', exact: true }).click()
  await expect(page.getByText('3 lagu ditemukan')).toBeVisible()
  await page.route('**/api/health', route => route.fulfill({ json: { documents: 3, semantic_ready: true } }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Backend perlu dimuat ulang')
})

test('settings select an explicit experiment without changing AUTO default', async ({ page }) => {
  await page.goto('/?q=Bruno')
  await expect(page.getByText('3 lagu ditemukan')).toBeVisible()
  await page.getByRole('button', { name: 'Pengaturan pencarian', exact: true }).click()
  await expect(page.getByLabel('Metode pencarian')).toHaveValue('AUTO')
  const request = page.waitForRequest(r => r.url().endsWith('/api/search') && r.postDataJSON().mode === 'E2')
  await page.getByLabel('Metode pencarian').selectOption('E2')
  await request
  await page.getByRole('button', { name: 'Selesai', exact: true }).click()
  await expect(page.getByText('3 lagu ditemukan')).toBeVisible()
})

test('Spotify player uses the selected track and has a working close control', async ({ page }) => {
  await page.goto('/')
  await page.locator('.quick-tile').first().hover()
  await page.locator('.quick-tile').first().getByRole('button', { name: 'Dengarkan Die With A Smile' }).click()
  await expect(page.getByTitle('Spotify — Die With A Smile')).toHaveAttribute('src', /embed\/track\/2plbrEY59IikOBgBGLjaoe/)
  await page.getByRole('button', { name: 'Tutup pemutar Spotify', exact: true }).click()
  await expect(page.getByTitle('Spotify — Die With A Smile')).toHaveCount(0)
})

test('mobile layout fits the viewport and supports library and search', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Temukan favorit barumu' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Buka koleksi', exact: true }).click()
  await page.getByRole('button', { name: /Lagu yang Disukai/ }).click()
  await expect(page.getByRole('heading', { name: 'Lagu yang Disukai' })).toBeVisible()
  const input = page.getByRole('textbox', { name: 'Cari musik', exact: true })
  await input.fill('tempo > 120 BPM'); await input.press('Enter')
  await expect(page.getByText('3 lagu ditemukan')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
