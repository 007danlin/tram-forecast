// DF-03/04: use the displayed result, preserve state, fail honestly without data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium, webkit} = require('playwright');
const {visible, applyScenario, openScenario, closeDialog, mobilePane} = require('./ui.cjs');
const near = (a,b) => assert.ok(Math.abs(a-b)<1e-7+Math.abs(b)*1e-12, `${a} != ${b}`);
(async()=>{
  const [baseURL, output] = process.argv.slice(2);
  assert.equal(new URL(baseURL).hostname,'127.0.0.1');
  fs.mkdirSync(output,{recursive:true});
  const browser = await (process.env.QA_ENGINE==='webkit'?webkit:chromium).launch();
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'America/Los_Angeles',acceptDownloads:true});
    const errors=[],queries=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().endsWith('/query'))queries.push(r.postDataJSON());});
    const response = page.waitForResponse(r=>r.url().endsWith('/handoff/query')&&r.ok());
    await page.goto(baseURL);
    const base=await(await response).json();
    await page.getByTestId('total').waitFor();
    fs.writeFileSync(path.join(output,'base-api.json'),JSON.stringify(base,null,2));
    const peak=base.rows.reduce((best,r,i)=>r.value>base.rows[best].value?i:best,0);
    await page.getByRole('button',{name:'Час пик',exact:true}).click();
    await page.getByTestId('dispatch-action').locator('summary').click();
    const checkValues=async rows=>{
      const values=await page.locator('[data-dispatch-value]').evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.dispatchValue)));
      const expected=[peak-1,peak,peak+1].filter(i=>i>=0&&i<rows.length).map(i=>rows[i].value);
      assert.equal(values.length,expected.length);values.forEach((v,i)=>near(v,expected[i]));
    };
    await checkValues(base.rows);
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Скачать CSV',exact:true}).click();
    await(await download).saveAs(path.join(output,'base.csv'));
    await page.screenshot({path:path.join(output,'dispatch-desktop.png'),fullPage:true});
    const scenario=await applyScenario(page,{'Погода':10,'Мероприятия':20});
    await page.getByTestId('total').waitFor();
    near(scenario.total,base.total*1.32);await checkValues(scenario.rows);
    fs.writeFileSync(path.join(output,'scenario-api.json'),JSON.stringify(scenario,null,2));
    const scenarioDownload=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать CSV',exact:true}).click();
    await(await scenarioDownload).saveAs(path.join(output,'scenario.csv'));
    const selected=await visible(page.getByLabel('Точка временного ряда')).inputValue(),before=queries.length;
    await page.getByRole('button',{name:'На год',exact:true}).click();
    assert.match(await page.getByTestId('year-basis').textContent(),/Маршрут|исторический профиль/);
    assert.equal(await page.getByRole('region',{name:'План на 12 месяцев'}).locator('article').count(),4);
    assert.match(await page.getByTestId('year-period').textContent(),/2025.*2026/);
    await page.screenshot({path:path.join(output,'year-desktop.png'),fullPage:true});
    await page.getByRole('region',{name:'План на 12 месяцев'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'year-plan-desktop.png'),fullPage:true});
    await closeDialog(page);
    assert.equal(queries.length,before);assert.equal(await visible(page.getByLabel('Точка временного ряда')).inputValue(),selected);
    near(Number(await page.getByTestId('total').getAttribute('data-raw-value')),scenario.total);
    await openScenario(page);assert.equal(await page.getByLabel('Поправка: Погода').inputValue(),'10');
    await page.getByRole('button',{name:'Сбросить поправки',exact:true}).click();
    await page.getByRole('button',{name:'Применить',exact:true}).click();await page.getByTestId('total').waitFor();
    near(Number(await page.getByTestId('total').getAttribute('data-raw-value')),base.total);
    for(const route of ['5','2','__overview__']){
      await page.getByLabel('Маршрут',{exact:true}).selectOption(route);
      await page.getByRole('button',{name:'На год',exact:true}).click();
      assert.equal(await page.locator('.year-view__scenarios').count(),0);
      assert.equal(await page.getByRole('region',{name:'План на 12 месяцев'}).count(),0);
      await closeDialog(page);
    }
    await page.getByLabel('Маршрут',{exact:true}).selectOption('1');await page.getByTestId('total').waitFor();
    await page.setViewportSize({width:390,height:844});await mobilePane(page,'Прогноз');
    if(await page.getByTestId('dispatch-action').getAttribute('open')===null) await page.getByTestId('dispatch-action').locator('summary').click();
    await page.screenshot({path:path.join(output,'dispatch-mobile.png'),fullPage:true});
    await page.getByRole('button',{name:'Открыть меню',exact:true}).click();await page.getByRole('button',{name:'На год',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
    await page.screenshot({path:path.join(output,'year-mobile.png'),fullPage:true});
    await page.getByRole('region',{name:'План на 12 месяцев'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'year-plan-mobile.png'),fullPage:true});await closeDialog(page);
    // Old backend without optional year metadata must remain usable.
    await page.route('**/handoff/capabilities',async route=>{const r=await route.fetch(),body=await r.json();delete body.year;await route.fulfill({json:body});});
    await page.reload();await page.getByTestId('total').waitFor();
    await page.getByRole('button',{name:'Открыть меню',exact:true}).click();
    assert.equal(await page.getByRole('button',{name:'На год',exact:true}).isDisabled(),true);
    await page.getByRole('button',{name:'Закрыть меню',exact:true}).press('Escape');
    await page.unroute('**/handoff/capabilities');
    // Synthetic missing hour, derived from a response fixture, never saved as real evidence.
    await page.route('**/handoff/query',async route=>{
      const r=await route.fetch(),body=await r.json(),row=body.rows[0];
      body.total-=row.value;row.value=null;row.reference_value=null;row.lower_90=null;row.upper_90=null;row.priority_score=null;
      row.available_hours=0;row.coverage=0;row.status='no_data';
      body.coverage=(body.rows.length-1)/body.rows.length;body.total_scope='available_only';
      await route.fulfill({json:body});
    });
    await page.reload();await page.getByTestId('total').waitFor();await mobilePane(page,'Прогноз');
    await page.getByTestId('dispatch-action').locator('summary').click();
    assert.match(await page.getByTestId('dispatch-action').textContent(),/Данные неполные/);
    assert.doesNotMatch(await page.getByTestId('dispatch-action').textContent(),/выбранный [+−]/);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify({run:base.forecast_run_id,result_id:base.result_id,scenario_result_id:scenario.result_id,route:base.filters.route_ids[0],period:base.filters,peak_index:peak,peak:base.rows[peak],checks:['API and neighboring UI values','base/scenario exports','coefficient product/reset','year preserves state without queries','4 quarters desktop/mobile','baseline/unsupported/overview suppressed','missing metadata','synthetic null/partial'],errors},null,2));
    console.log('PASS final closure: route/action/neighbors, scenarios/reset, year/state/quarters, missing data, mobile');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
