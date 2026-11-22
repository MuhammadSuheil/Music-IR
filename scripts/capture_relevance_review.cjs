// Live read-only browser check. Never submits a reviewer ID, proposal reveal, or human decision.
const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
(async () => {
  const root = path.resolve(__dirname, '..');
  const run = path.resolve(root, process.argv[2]);
  const directory = path.join(run, 'validation');
  await fs.mkdir(directory, {recursive:true});
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.url().includes('/api/relevance') && r.method()!=='GET')writes.push({url:r.url(),method:r.method()})});
  try {
    await page.goto('http://127.0.0.1:8501/?view=relevance');
    await page.getByRole('heading',{name:/Review label awal LLM|Evaluasi otomatis untuk laporan/}).waitFor();
    await page.locator('.relevance-page .annotation-card, .relevance-page .automatic-export').first().waitFor({timeout:30000});
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(directory,'review_live_desktop.png'),animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(directory,'review_live_mobile.png'),animations:'disabled'});
    const data={url:page.url(),page_errors:errors,human_mutation_requests:writes,
      mobile_document_fits:await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),
      mobile_main_fits:await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth),
      real_backend:true,mocked_routes:false,reviewer_submitted:false};
    await fs.writeFile(path.join(directory,'review_live_browser.json'),JSON.stringify(data,null,2));
    console.log(JSON.stringify(data));
    if(errors.length || writes.length || !data.mobile_document_fits || !data.mobile_main_fits)throw Error('Live review check failed');
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
