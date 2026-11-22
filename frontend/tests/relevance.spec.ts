import { test, expect } from '@playwright/test'

test('review starts blind, autosaves drafts and reveals proposals only on explicit request', async ({ page }) => {
  let revealCount = 0
  let savedDraft = false
  let decision: Record<string, unknown> | null = null
  let approved = false
  const q = () => ({ query_id: 'q1', query: 'One', user_need: 'Find title One', category: 'title', split: 'dev', definition_approved: approved, pool_count: 2, final_count: decision ? 1 : 0 })
  const summary = () => ({ run_id: 'fixture-run', query_count: 1, pairs: 2, auto_processed: 2, auto_completed: 2, auto_unprocessed: 0,
    auto_errors: 0, auto_needs_review: 0, human_final_pairs: decision ? 1 : 0, pool_complete: true, auto_complete: true, human_complete: false, queries: [q()] })
  await page.route('**/api/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname
    let data: unknown = {}
    if (path === '/api/health') data = { documents: 2, semantic_ready: true, default_mode: 'AUTO' }
    else if (path === '/api/catalog') data = { tracks: [], genres: [], total: 0 }
    else if (path === '/api/relevance/runs') data = { runs: [summary()] }
    else if (path === '/api/relevance/runs/fixture-run') data = summary()
    else if (path.endsWith('/definition')) { approved = true; data = { definition_approved: true } }
    else if (path.endsWith('/draft')) { savedDraft = true; data = { saved: true, finalized: false } }
    else if (path.endsWith('/proposal')) { revealCount++; data = { status: 'ok', proposal: { auto_grade: 3, reason: 'Exact supplied title', evidence: [{ field: 'track_name', quote: 'One' }], uncertainty_flags: [], provider: 'fixture', model: 'fixture' } } }
    else if (path.endsWith('/review')) { decision = request.postDataJSON(); data = { human_grade: 2, final_grade: 2, human_review_status: 'corrected', reason: 'Needs context', updated: 'one', viewed_auto: 1 } }
    else if (path.endsWith('/queries/q1')) data = { query: q(), offset: 0, total: 2, candidates: [{ track_id: 'A', title: 'One', artist: 'Alice', album: 'First', genres: ['pop'], lyrics: 'Supplied source lyric', audio: { tempo: 120 }, numeric_checks: [], auto_available: true, review: null, draft: null }] }
    await route.fulfill({ json: data })
  })
  await page.goto('/?view=relevance')
  await expect(page.getByRole('heading', { name: 'Review label awal LLM', exact: true })).toBeVisible()
  await expect(page.getByText('Exact supplied title', { exact: true })).toHaveCount(0)
  expect(revealCount).toBe(0)
  await page.getByRole('textbox', { name: 'Kode reviewer', exact: true }).fill('test-human')
  await page.getByRole('button', { name: 'Gunakan reviewer', exact: true }).click()
  await page.getByRole('button', { name: 'Setujui kebutuhan query', exact: true }).click()
  await page.getByRole('button', { name: '2 · Relevan', exact: true }).click()
  await page.getByRole('textbox', { name: 'Alasan koreksi', exact: true }).fill('Needs context')
  await expect.poll(() => savedDraft).toBeTruthy()
  expect(decision).toBeNull()
  await page.getByRole('button', { name: 'Buka usulan LLM', exact: true }).click()
  await expect(page.getByText('Exact supplied title', { exact: true })).toBeVisible()
  expect(revealCount).toBe(1)
  await page.getByRole('button', { name: 'Koreksi label awal', exact: true }).click()
  expect(decision).toMatchObject({ reviewer_id: 'test-human', action: 'correct', grade: 2, reason: 'Needs context' })
})

test('an unresolved proposal cannot be accepted and mobile review does not overflow', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const summary = { run_id: 'fixture-run', query_count: 1, pairs: 1, auto_processed: 1, auto_unprocessed: 0, auto_errors: 0, auto_needs_review: 1,
      human_final_pairs: 0, pool_complete: true, auto_complete: true, human_complete: false, queries: [{ query_id: 'q1', query: 'lagu tentang merindukan seseorang setelah putus cinta dengan kebutuhan panjang untuk diperiksa manusia', user_need: 'Ambiguous draft', category: 'semantic', split: 'dev', definition_approved: true, pool_count: 1, final_count: 0 }] }
    const data = path.endsWith('/health') ? { documents: 1, semantic_ready: true, default_mode: 'AUTO' } : path.endsWith('/catalog') ? { tracks: [], genres: [], total: 0 } : path === '/api/relevance/runs' ? { runs: [summary] } : path.endsWith('/fixture-run') ? summary : path.endsWith('/proposal') ? { status: 'needs_review', proposal: { auto_grade: null, reason: 'Need definition', evidence: [], uncertainty_flags: ['ambiguous'], provider: 'fixture', model: null } } : path.endsWith('/queries/q1') ? { total: 1, offset: 0, candidates: [{ track_id: 'A', title: 'One', artist: 'Alice', album: '', genres: [], lyrics: 'Text', audio: {}, numeric_checks: [], auto_available: true, review: null, draft: null }] } : { saved: true }
    await route.fulfill({ json: data })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?view=relevance')
  await page.getByRole('textbox', { name: 'Kode reviewer', exact: true }).fill('test-human')
  await page.getByRole('button', { name: 'Gunakan reviewer', exact: true }).click()
  await page.getByRole('button', { name: 'Buka usulan LLM', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Setujui label awal', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
})

test('automatic-only export needs neither reviewer nor query approval', async ({ page }) => {
  const writes: string[] = []
  await page.route('**/api/**', async route => {
    const req=route.request();const path=new URL(req.url()).pathname
    if(req.method()!=='GET')writes.push(path)
    const summary={run_id:'automatic-fixture',query_count:1,pairs:2,auto_processed:2,auto_unprocessed:0,auto_errors:0,auto_needs_review:0,
      human_final_pairs:0,pool_complete:true,auto_complete:true,human_complete:false,human_review_required:false,automatic_label_source:'LLM theme + corpus checks',
      queries:[{query_id:'q',query:'One',user_need:'title',category:'title',split:'dev',definition_approved:false,pool_count:2,final_count:0}]}
    const data=path.endsWith('/health')?{documents:2,semantic_ready:true,default_mode:'AUTO'}:path.endsWith('/catalog')?{tracks:[],genres:[],total:0}:
      path==='/api/relevance/runs'?{runs:[summary]}:path.endsWith('/automatic-fixture')?summary:path.endsWith('/export')?{final_query_ids:[],qrels_final_available:false,human_review_required:false}:{candidates:[],total:0,offset:0}
    await route.fulfill({json:data})
  })
  await page.goto('/?view=relevance')
  await expect(page.getByRole('heading',{name:'Evaluasi otomatis untuk laporan',exact:true})).toBeVisible()
  await expect(page.getByRole('textbox',{name:'Kode reviewer',exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Hitung dan ekspor hasil otomatis',exact:true}).click()
  await expect(page.getByRole('link',{name:'qrels_auto.tsv',exact:true})).toBeVisible()
  expect(writes).toEqual(['/api/relevance/runs/automatic-fixture/export'])
})
