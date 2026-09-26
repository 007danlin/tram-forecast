// Real local monitoring, independent of historical B2; synthetic outage/staleness UI checks.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium,webkit}=require('playwright');
(async()=>{
  const url=process.argv[2]||'http://127.0.0.1:15186';assert.equal(new URL(url).hostname,'127.0.0.1');
  const output=process.argv[3]||'artifacts/monitoring/browser';fs.mkdirSync(output,{recursive:true});
  const browser=await (process.env.QA_ENGINE==='webkit'?webkit:chromium).launch();
  try {
    const context=await browser.newContext({viewport:{width:1365,height:1000},timezoneId:'America/Los_Angeles'});
    const page=await context.newPage(),errors=[],requests=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
    await page.goto(url);await page.getByTestId('total').waitFor();
    const before=await page.getByTestId('total').getAttribute('data-raw-value');
    const state=await (await page.request.get(url+'/api/v2/monitoring/status')).json();
    assert.equal(state.information_mode,'operational');assert.equal(state.forecast_effect,'not_applied');
    assert.equal(state.historical.external_live_join,false);
    for(const id of ['weather','closures','changes','events']) {
      const source=state.sources.find(s=>s.id===id);assert.equal(source.status,'fresh',`${id}: ${source.error}`);assert.ok(source.record_count>0);
      const records=await (await page.request.get(url+`/api/v2/monitoring/records?source_id=${id}&limit=100`)).json();
      records.records.forEach(r=>{assert.ok(r.source_url.startsWith('https://'));assert.ok(r.fetched_at);assert.ok('valid_start' in r);assert.ok(r.location);assert.ok(r.route_link);assert.equal(r.forecast_effect,'not_applied');});
    }
    assert.ok(['fresh','stale','lagging','pending'].includes(state.sources.find(s=>s.id==='traffic').status));
    assert.equal(state.sources.find(s=>s.id==='traffic').provider,'ЦОДД · Дептранс');
    await page.getByRole('button',{name:'О данных',exact:true}).click();
    await page.locator('[data-source="weather"]').waitFor();
    assert.equal(await page.locator('.source-card').count(),5);
    assert.equal(await page.getByLabel('Коэффициент погоды').count(),0);
    assert.equal(await page.getByLabel('Коэффициент события').count(),0);
    await page.screenshot({path:path.join(output,'sources-dark.png')});
    await page.locator('[data-source="events"] summary').click();
    assert.ok(await page.locator('[data-source="events"] .source-record a').count()>0);
    assert.ok((await page.locator('[data-source="events"]').textContent()).includes('не установлена'));
    await page.locator('[data-source="events"] summary').click();
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    await page.screenshot({path:path.join(output,'sources-light.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
    assert.equal(await page.locator('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
    await page.screenshot({path:path.join(output,'sources-mobile.png')});
    await page.getByRole('button',{name:'Закрыть сведения'}).click();
    assert.equal(await page.getByTestId('total').getAttribute('data-raw-value'),before);
    assert.equal(requests.filter(r=>r.includes('/scenarios/')).length,0);
    // Fixture only for failure presentation, never counted as a successful live collector.
    const failed=structuredClone(state);failed.sources[0].status='error';failed.sources[0].error='Источник вернул HTTP 429';
    failed.sources[1].status='stale';
    await page.route('**/monitoring/status',r=>r.fulfill({json:failed}));
    await page.setViewportSize({width:1365,height:1000});
    await page.getByRole('button',{name:'О данных',exact:true}).click();
    await page.getByText('Источник вернул HTTP 429',{exact:true}).waitFor();
    assert.match(await page.locator('[data-source="closures"] .source-status').textContent(),/устарели/);
    await page.screenshot({path:path.join(output,'sources-error-and-stale.png')});
    await page.getByRole('button',{name:'Закрыть сведения'}).click();await page.unroute('**/monitoring/status');
    await page.route('**/monitoring/status',r=>r.abort('failed'));
    await page.getByRole('button',{name:'О данных',exact:true}).click();
    await page.getByRole('alert').waitFor();
    assert.equal(await page.locator('.source-card[data-status="fresh"]').count(),0);
    assert.equal(errors.length,0,errors.join('\n'));
    fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify({checked_at:new Date().toISOString(),sources:state.sources.map(({id,status,record_count,last_success_at})=>({id,status,record_count,last_success_at})),historical_total:before,checks:['real collectors through API','source provenance and unknown routes','B2 total unchanged','no manual UI or scenario requests','dark/light/mobile','explicit 429/stale/offline states'],errors},null,2));
    console.log('PASS automatic monitoring sources, provenance, no coefficients, B2 preserved, dark/light/mobile/errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
