// Variant A: selected interval, local time navigation and responsive controls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium, webkit} = require('playwright');
(async () => {
  const base = process.argv[2];
  assert.equal(new URL(base).hostname, '127.0.0.1');
  const engine = process.env.QA_ENGINE === 'webkit' ? webkit : chromium;
  const browser = await engine.launch();
  const output = process.argv[3] || 'artifacts/verification/compact-card';
  fs.mkdirSync(output, {recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:950}, timezoneId:'America/Los_Angeles'});
    const errors = [], queries = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => {if(r.url().endsWith('/query')) queries.push(r);});
    const response = page.waitForResponse(r => r.url().endsWith('/handoff/query') && r.ok());
    await page.goto(base);
    const data = await (await response).json();
    await page.getByTestId('total').waitFor();
    const rows = data.rows;
    const peak = rows.reduce((best, p, i) => p.value !== null && (best < 0 || p.value > rows[best].value) ? i : best, -1);
    const range = page.getByLabel('Точка временного ряда');
    const before = queries.length;
    const checkPoint = async i => {
      assert.equal(await range.inputValue(), String(i));
      assert.equal(Number(await page.getByTestId('map-demand').getAttribute('data-raw-value')), rows[i].value);
      assert.equal(Number(await page.getByTestId('total').getAttribute('data-raw-value')), data.total);
    };
    await page.getByRole('button',{name:'Пик',exact:true}).click();
    await checkPoint(peak);
    if(peak > 0) {
      await range.focus(); await range.press('ArrowLeft'); await checkPoint(peak-1);
      await page.getByRole('region',{name:'Карточка прогноза'}).getByRole('button',{name:'Пик',exact:true}).click();
      await page.locator('.neighbor-values button').first().click(); await checkPoint(peak-1);
    }
    assert.equal(queries.length, before, 'Time navigation must not send new queries');
    assert.equal(await page.locator('.workspace-timeline').count(),0);
    assert.equal(await page.locator('.forecast-card .timeline-panel').count(),1);
    await page.getByRole('button',{name:'Пик',exact:true}).click();
    for (const theme of ['dark','light']) {
      await page.setViewportSize({width:1440,height:950});
      await page.getByRole('button',{name:theme === 'dark' ? 'Включить тёмную тему' : 'Включить светлую тему', exact:true}).click();
      await page.screenshot({path:`${output}/${theme}-desktop.png`, fullPage:true});
      for (const width of [390, 320]) {
        await page.setViewportSize({width,height:844});
        assert.equal(await range.isVisible(),true);
        assert.equal(await page.getByRole('button',{name:'1 нед',exact:true}).isVisible(),true);
        assert.equal(await page.getByRole('button',{name:'Таблица',exact:true}).isVisible(),true);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        const card = await page.locator('.workspace-card').boundingBox();
        const map = await page.locator('.map-shell').boundingBox();
        assert.ok(card.y < map.y, 'Forecast controls precede the map on mobile');
        await page.screenshot({path:`${output}/${theme}-${width}.png`, fullPage:true});
      }
    }
    await page.setViewportSize({width:1024,height:768});
    await page.getByRole('button',{name:'Год',exact:true}).click();
    assert.equal(Math.round((await page.locator('.workspace-card').boundingBox()).width), 992);
    await page.getByRole('button',{name:'1 день',exact:true}).click();
    await page.getByTestId('total').waitFor();
    await page.getByRole('button',{name:'Свернуть карточку'}).click();
    assert.equal(Math.round((await page.locator('.map-shell').boundingBox()).width), 992);
    await page.getByRole('button',{name:'Открыть прогноз'}).click();
    assert.deepEqual(errors,[]);
    console.log(`PASS ${engine.name()}: selected value vs total, peak/keyboard/neighbors without queries, 320/390 mobile, both themes`);
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exitCode=1;});
