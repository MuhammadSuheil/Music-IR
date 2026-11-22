const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const output = path.join(__dirname, 'evidence', 'screenshots');
(async () => {
  await fs.mkdir(output, {recursive:true});
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:960},deviceScaleFactor:1});
  const events=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  async function search(query,name) {
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/search') && r.request().postDataJSON().query===query,{timeout:300000});
    await page.goto('http://127.0.0.1:8501/?q='+encodeURIComponent(query));
    const response=await pending;const data=await response.json();
    events.push({name,status:response.status(),payload:response.request().postDataJSON(),response:data});
    if(!response.ok())throw Error('Search failed: '+name);
    await page.locator('.diagnostics-panel > summary').waitFor();
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(output,name+'.png'),fullPage:true,animations:'disabled'});
    return data;
  }
  try {
    await search('tempo > 120 BPM','search');
    await page.locator('.diagnostics-panel > summary').click();
    const trace=page.waitForResponse(r=>r.url().endsWith('/api/search') && r.request().postDataJSON().trace===true,{timeout:300000});
    await page.getByRole('button',{name:'Lihat jejak',exact:true}).click();
    const traced=await trace;events.push({name:'trace',status:traced.status(),payload:traced.request().postDataJSON(),response:await traced.json()});
    await page.locator('.research-table').waitFor();
    await page.locator('.diagnostics-panel').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'trace.png'),animations:'disabled'});
    await search('tempo > 999 BPM','empty');
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/benchmark'),{timeout:30000});
    await page.goto('http://127.0.0.1:8501/?view=benchmark');
    const response=await pending;events.push({name:'evaluation_status',status:response.status(),response:await response.json()});
    await page.getByRole('heading',{name:'Benchmark & penilaian',exact:true}).waitFor();
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(output,'evaluation_status.png'),animations:'disabled'});
    console.log(JSON.stringify({screenshots:4,real_backend:true,mocked_routes:false,page_errors:errors}));
  } finally {
    await fs.writeFile(path.join(__dirname,'evidence','ui_live_responses.json'),JSON.stringify({events,page_errors:errors},null,2));
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1});
