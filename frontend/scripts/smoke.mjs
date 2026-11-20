import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const output = resolve('../artifacts/ui')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 })
const errors = []
page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto('http://127.0.0.1:8501/')
  await page.getByRole('heading', { name: 'Temukan favorit barumu' }).waitFor()
  await page.evaluate(() => document.fonts.ready)
  await page.locator('.quick-grid img').first().waitFor({ state: 'visible' })
  await page.screenshot({ path: resolve(output, 'desktop-home.png'), fullPage: true, animations: 'disabled' })
  console.log('Desktop home: live catalog rendered.')
  for (const query of ['Die With A Smile', 'lagu tentang sulit melupakan seseorang', 'tempo > 120 BPM', 'lirik "make the stars look like there not shining"', 'lagu happy']) {
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/search') && r.request().postDataJSON().query === query, { timeout: 180000 })
    await page.goto('http://127.0.0.1:8501/?q=' + encodeURIComponent(query))
    const response = await responsePromise
    const data = await response.json()
    if (!response.ok() || data.mode !== 'AUTO' || !data.results.length) throw new Error(`Search failed: ${query} (${response.status()})`)
    await page.getByText(`${data.results.length} lagu ditemukan`, { exact: true }).waitFor()
    console.log(JSON.stringify({ query, status: response.status(), pipeline: data.pipeline, top: data.results[0].title }))
    if (query === 'Die With A Smile') await page.screenshot({ path: resolve(output, 'desktop-search.png'), fullPage: true, animations: 'disabled' })
    if (query.includes('stars look like')) {
      if (data.results[0].title !== 'Just the Way You Are' || data.results[0].artist !== 'Bruno Mars') throw new Error('User lyric regression failed')
      await page.getByText('Potongan lirik yang mirip', { exact: true }).waitFor()
      await page.screenshot({ path: resolve(output, 'desktop-lyrics.png'), fullPage: true, animations: 'disabled' })
    }
    if (query.startsWith('tempo') && data.results.some(track => track.audio.tempo <= 120)) throw new Error('Audio constraint violated')
  }
  await page.getByRole('button', { name: 'Music IR — Beranda', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('heading', { name: 'Temukan favorit barumu' }).waitFor()
  if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)) throw new Error('Mobile layout overflows')
  await page.screenshot({ path: resolve(output, 'mobile-home.png'), fullPage: true, animations: 'disabled' })
  if (errors.length) throw new Error(errors.join('\n'))
  console.log('Live browser smoke passed; desktop/search/mobile screenshots saved to artifacts/ui/.')
} finally {
  await browser.close()
}
