const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const close = (a,b) => assert.ok(Math.abs(a-b) <= 1e-9 + 1e-12*Math.abs(b), `${a} != ${b}`);
(async () => {
  const {baseURL, forecast, output, sourceKind} = JSON.parse(fs.readFileSync(0,'utf8'));
  assert.equal(new URL(baseURL).hostname, '127.0.0.1');
  const original = fs.readFileSync(forecast,'utf8').trim().split(/\r?\n/).slice(1).map(line => {
    const [route,date,hour,prediction] = line.split(';'); return {route,date,hour:Number(hour),value:Number(prediction)};
  });
  const browser = await chromium.launch({channel: process.env.QA_BROWSER || 'chromium', headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1366,height:768}, timezoneId:'America/Los_Angeles', acceptDownloads:true});
    const page = await context.newPage(); const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    // A fresh clone has no private release: explain readiness, then recover.
    await page.route('**/handoff/ready',route => route.fulfill({status:503,contentType:'application/json',body:'{"error":{"code":"handoff_unavailable"}}'}));
    await page.goto(baseURL);
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').textContent(),/пакет прогноза отсутствует или недоступен/);
    assert.equal(await page.getByTestId('total').count(),0);
    assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
    await page.unroute('**/handoff/ready');
    await page.getByRole('button',{name:'Повторить запрос',exact:true}).click();
    await page.getByTestId('total').waitFor();
    await page.getByRole('button',{name:'Таблица',exact:true}).click();
    await page.getByRole('button',{name:'Свернуть карточку'}).click();
    await page.locator('.tram-map__viewport svg').waitFor();
    await page.locator('.tram-map__viewport').evaluate(el => el.qaIdentity = 'persistent');
    const mapViewport = page.locator('.tram-map__viewport');
    const mapSvg = mapViewport.locator('svg');
    const initialView = await mapSvg.getAttribute('viewBox');
    await mapViewport.focus();
    await mapViewport.press('ArrowRight');
    await page.waitForFunction(initial => document.querySelector('.tram-map__viewport svg').getAttribute('viewBox') !== initial, initialView);
    await mapViewport.press('+');
    await mapViewport.press('0');
    await page.waitForFunction(initial => document.querySelector('.tram-map__viewport svg').getAttribute('viewBox') === initial, initialView);
    // Select a visible real line away from controls. A DOM hit corridor may overlap
    // its neighbour: selection must match the clicked geometry, not paint order.
    const lineTarget = await mapSvg.evaluate(svg => {
      const box = svg.viewBox.baseVal, rect = svg.getBoundingClientRect();
      const lines = [...svg.querySelectorAll('polyline[data-lane]')];
      for (const line of lines) {
        for (const point of line.points) {
          const x = (point.x - box.x) / box.width * rect.width;
          const y = (point.y - box.y) / box.height * rect.height;
          if (x < 50 || x > rect.width - 100 || y < 180 || y > rect.height - 60) continue;
          // Avoid a junction where two lanes legitimately have the same point.
          const shared = lines.some(other => other !== line && [...other.points].some(p => Math.hypot(p.x-point.x,p.y-point.y) < .5));
          if (!shared) return {x:rect.x+x,y:rect.y+y,points:line.getAttribute('points')};
        }
      }
      throw new Error('No visible route geometry available for acceptance');
    });
    await page.mouse.click(lineTarget.x,lineTarget.y);
    await page.waitForFunction(points => document.querySelector('.tram-map__viewport polyline[stroke-width="5"]')?.getAttribute('points') === points, lineTarget.points);
    await page.getByRole('button',{name:'Открыть прогноз'}).click();
    await page.getByRole('button',{name:'Таблица',exact:true}).click();
    const horizonLabels = {day:'1 день',week:'1 нед',month:'1 мес'};
    async function setHorizon(value) {await page.getByRole('button',{name:horizonLabels[value],exact:true}).click();}
    async function checkRows(count) {
      const selectedRoute=await page.getByLabel('Маршрут',{exact:true}).inputValue();
      const selectedDay=await page.getByLabel('Дата (МСК)').inputValue();
      const horizonText=await page.locator('.filter-bar__horizon [aria-pressed=true]').textContent();
      const selectedHorizon=Object.keys(horizonLabels).find(key => horizonLabels[key] === horizonText);
      const firstDay=selectedHorizon === 'month' ? selectedDay.slice(0,7)+'-01' : selectedDay;
      const expectedRows=Array.from({length:count},(_,i) => {
        const stamp=new Date(Date.parse(firstDay+'T00:00:00Z')+i*(selectedHorizon==='day'?3600000:86400000));
        const start=stamp.toISOString().slice(0,19)+'+03:00';
        const value=original.filter(r => r.route===selectedRoute && r.date===start.slice(0,10) && (selectedHorizon==='day'?r.hour===stamp.getUTCHours():true)).reduce((sum,r)=>sum+r.value,0);
        return {route:selectedRoute,start,value};
      });
      // A previous no_data result also has 24 rows: wait for the requested
      // values and keys, not merely row count, before inspecting the new view.
      await page.waitForFunction(expected => {
        const rows=[...document.querySelectorAll('tbody tr')];
        return rows.length===expected.length && rows.every((row,i) => {
          const raw=row.querySelector('[data-raw-value]')?.dataset.rawValue;
          return row.dataset.route===expected[i].route && row.dataset.start===expected[i].start && raw!=='' && raw!==undefined && Math.abs(Number(raw)-expected[i].value)<=1e-9+1e-12*Math.abs(expected[i].value);
        });
      },expectedRows);
      const rows = await page.locator('tbody tr').evaluateAll(elements => elements.map(row => ({start:row.dataset.start, route:row.dataset.route, value:row.querySelector('[data-raw-value]').dataset.rawValue})));
      let total = 0;
      for (const row of rows) {
        const expected = original.filter(r => r.route === row.route && r.date === row.start.slice(0,10) && (count === 24 ? r.hour === Number(row.start.slice(11,13)) : true)).reduce((sum,r) => sum+r.value,0);
        close(Number(row.value),expected); total += expected;
      }
      close(Number(await page.getByTestId('total').getAttribute('data-raw-value')),total);
      assert.equal(await page.locator('.tram-map__viewport').evaluate(el => el.qaIdentity),'persistent');
      assert.equal(await mapSvg.locator('polyline[stroke-width="5"]').getAttribute('points'),lineTarget.points);
    }
    await checkRows(24);
    await setHorizon('week'); await checkRows(7);
    await setHorizon('month'); await checkRows(30);
    await page.getByLabel('Дата (МСК)').fill('2025-12-01'); await checkRows(31);
    const downloaded = page.waitForEvent('download'); await page.getByRole('button',{name:'Скачать CSV'}).click();
    const download = await downloaded; const csv = fs.readFileSync(await download.path(),'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/);
    const fields = csv[0].split(','); assert.equal(csv.length,32);
    for (const line of csv.slice(1)) {
      const cells = line.split(','); const get = key => cells[fields.indexOf(key)];
      const expected = original.filter(r => r.route === get('route_id') && r.date === get('start').slice(0,10)).reduce((sum,r) => sum+r.value,0);
      close(Number(get('value')),expected);
      assert.equal(get('forecast_run_id'),await page.getByTestId('run').textContent());
    }
    await page.getByLabel('Маршрут',{exact:true}).selectOption('5');
    await page.waitForFunction(() => document.querySelector('[data-testid=total]')?.dataset.rawValue === '0');
    await checkRows(31);
    assert.equal(await page.getByText('Нулевой baseline: нет успешной истории обучения.',{exact:false}).count(),1);
    // Old responses cannot overwrite a newer filter selection.
    await page.route('**/handoff/query',async route => {const response = await route.fetch(); if (route.request().postDataJSON().route_ids[0] === '1') await new Promise(r => setTimeout(r,350)); await route.fulfill({response}).catch(e => {if (!/already handled|closed|aborted/i.test(e.message)) throw e;});});
    await page.getByLabel('Маршрут',{exact:true}).selectOption('1');
    assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
    await page.getByLabel('Маршрут',{exact:true}).selectOption('7');
    await page.waitForFunction(() => document.querySelector('tbody tr')?.dataset.route === '7'); await checkRows(31);
    await page.unroute('**/handoff/query');
    // Out-of-range weeks are explained and cannot be exported.
    await setHorizon('week');
    await page.getByLabel('Дата (МСК)').fill('2025-12-29');
    await page.getByRole('alert').waitFor(); assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
    await page.getByLabel('Дата (МСК)').fill('2025-11-01');
    await setHorizon('day'); await checkRows(24);
    for (const status of [503,410]) {
      await page.route('**/handoff/query',route => route.fulfill({status,contentType:'application/json',body:'{"error":{"code":"fixture"}}'}));
      await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click(); await page.getByRole('alert').waitFor();
      assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
      await page.unroute('**/handoff/query');
      const refreshed=page.waitForResponse(r => r.url().endsWith('/handoff/query') && r.status()===200);
      await page.getByRole('button',{name:status === 410 ? 'Обновить доступные данные' : 'Повторить запрос',exact:true}).click();
      await refreshed; await checkRows(24);
    }
    await page.route('**/handoff/export',route => route.fulfill({status:409,contentType:'application/json',body:'{"error":{"code":"fixture"}}'}));
    await page.getByRole('button',{name:'Скачать CSV'}).click(); await page.getByRole('alert').waitFor();
    assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
    await page.unroute('**/handoff/export'); await page.getByRole('button',{name:'Повторить запрос',exact:true}).click(); await checkRows(24);
    for (const empty of [false,true]) {
      await page.route('**/handoff/query',async route => {
        const response = await route.fetch(); const data = await response.json();
        for (const row of empty ? data.rows : [data.rows[12]]) {row.value=null; row.reference_value=null; row.lower_90=null; row.upper_90=null; row.priority_score=null; row.available_hours=0; row.coverage=0; row.status='no_data';}
        data.total=empty ? null : data.rows.reduce((sum,r) => sum+(r.value??0),0); data.coverage=empty ? 0 : 23/24; data.total_scope=empty ? 'no_data' : 'available_only';
        await route.fulfill({response,json:data});
      });
      await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click();
      await page.getByText(empty ? 'Нет данных (no_data):' : 'Неполное покрытие (partial):',{exact:false}).waitFor();
      assert.equal(await page.locator('tbody tr').nth(12).locator('[data-raw-value]').getAttribute('data-raw-value'),'');
      await page.unroute('**/handoff/query');
    }
    await page.getByRole('button',{name:'Обновить прогноз',exact:true}).click(); await checkRows(24);
    await page.getByRole('button',{name:'График',exact:true}).click();
    await page.screenshot({path:output+'/desktop.png',fullPage:true});
    const retainedView = await mapSvg.getAttribute('viewBox');
    await page.getByRole('button',{name:'Аналитика',exact:true}).click();
    assert.equal(await page.locator('.analytics-view tbody tr').count(),24);
    await page.getByRole('button',{name:'Карта',exact:true}).click();
    // ResizeObserver restores the viewport asynchronously after display:none.
    await page.waitForFunction(expected => document.querySelector('.tram-map__viewport svg')?.getAttribute('viewBox') === expected, retainedView);
    assert.equal(await mapSvg.getAttribute('viewBox'),retainedView);
    assert.equal(await mapViewport.evaluate(el => el.qaIdentity),'persistent');
    await page.getByRole('button',{name:'Настройки',exact:true}).click();
    await page.getByRole('dialog',{name:'Настройки',exact:true}).waitFor();
    await page.getByRole('dialog',{name:'Настройки',exact:true}).press('Escape');
    assert.equal(await page.getByRole('button',{name:'Настройки',exact:true}).getAttribute('aria-expanded'),'false');
    await page.getByRole('button',{name:'Свернуть карточку'}).click(); await page.getByRole('button',{name:'Открыть прогноз'}).click();
    await page.locator('.forecast-card').press('Escape');
    await page.waitForFunction(() => document.activeElement?.textContent === 'Открыть прогноз');
    await page.getByRole('button',{name:'Открыть прогноз'}).click();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),true);
    await page.screenshot({path:output+'/mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log(`PASS ${sourceKind} batch → API → UI → CSV; missing release and recovery, day/week/December/baseline, stale requests, MSK in non-MSK browser, 503/410/409, partial/no_data, keyboard, responsive, map remains mounted.`);
  } finally {await browser.close();}
})().catch(e => {console.error(e);process.exitCode=1;});
