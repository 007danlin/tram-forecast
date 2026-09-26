// Option 1: bounded desktop workspace and separate mobile map/forecast panes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium, webkit} = require('playwright');
const {visible, setTheme, mobilePane, closeDialog} = require('./ui.cjs');
(async () => {
  const base = process.argv[2];
  assert.equal(new URL(base).hostname, '127.0.0.1');
  const engine = process.env.QA_ENGINE === 'webkit' ? webkit : chromium;
  const browser = await engine.launch();
  const output = process.argv[3] || 'artifacts/verification/compact-card';
  fs.mkdirSync(output, {recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900}, timezoneId:'America/Los_Angeles'});
    const errors = [], queries = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => {if(r.url().endsWith('/query')) queries.push(r);});
    const response = page.waitForResponse(r => r.url().endsWith('/handoff/query') && r.ok());
    await page.goto(base);
    const data = await (await response).json();
    await page.getByTestId('total').waitFor();
    const peak = data.rows.reduce((best,p,i) => p.value !== null && (best < 0 || p.value > data.rows[best].value) ? i : best, -1);
    const range = visible(page.getByLabel('Точка временного ряда'));
    const waitMapSize = () => page.waitForFunction(() => {
      const viewport = document.querySelector('.tram-map__viewport');
      const view = viewport.querySelector('svg').viewBox.baseVal;
      return Math.abs(view.width / view.height - viewport.clientWidth / viewport.clientHeight) < 1e-6;
    });
    const before = queries.length;
    const checkPoint = async i => {
      assert.equal(await range.inputValue(), String(i));
      assert.equal(Number(await page.getByTestId('map-demand').getAttribute('data-raw-value')), data.rows[i].value);
      assert.equal(Number(await page.getByTestId('total').getAttribute('data-raw-value')), data.total);
    };
    await page.getByRole('button',{name:'Час пик',exact:true}).click();
    await checkPoint(peak);
    if (peak > 0) {await range.press('ArrowLeft'); await checkPoint(peak-1); await range.press('ArrowRight'); await checkPoint(peak);}
    assert.equal(queries.length, before, 'Time navigation must not send queries');
    await page.getByRole('button',{name:'На год',exact:true}).click();
    assert.match(await page.getByRole('dialog').textContent(), /Численного прогноза пока нет/);
    assert.equal(await page.getByRole('dialog').getByRole('button',{name:'Скачать CSV'}).count(), 0);
    await closeDialog(page);
    await checkPoint(peak);
    assert.equal(queries.length, before, 'Opening qualitative assumptions must preserve the numerical result');
    for (const theme of ['dark','light']) {
      await setTheme(page, theme);
      for (const [width,height] of [[1440,900],[1366,768],[1280,720],[1024,650]]) {
        await page.setViewportSize({width,height});
        const layout = await page.evaluate(() => ({page:document.documentElement.scrollHeight,height:innerHeight,width:document.documentElement.scrollWidth,viewport:innerWidth,card:document.querySelector('.workspace-card').scrollHeight,visible:document.querySelector('.workspace-card').clientHeight}));
        assert.ok(layout.page <= layout.height && layout.width <= layout.viewport, 'Desktop must fit the window');
        assert.ok(layout.card <= layout.visible + 1, 'Normal forecast and CSV fit the card');
        await page.getByRole('button',{name:'Аналитика',exact:true}).click();
        assert.ok(await page.locator('.analytics-chart').isVisible());
        assert.ok(await page.locator('.analytics-table').isVisible());
        await page.waitForFunction(() => {
          const svg = document.querySelector('.analytics-chart .forecast-chart svg');
          const box = svg.getBoundingClientRect();
          return Math.abs(svg.viewBox.baseVal.width - box.width) < 1 && Math.abs(svg.viewBox.baseVal.height - box.height) < 1;
        });
        const chart = await page.locator('.analytics-chart .forecast-chart svg').evaluate(svg => {
          const box = svg.getBoundingClientRect(), line = svg.querySelector('path').getBoundingClientRect();
          return {width:box.width,height:box.height,lineWidth:line.width,lineHeight:line.height};
        });
        assert.ok(chart.lineWidth > chart.width * .75 && chart.lineHeight > chart.height * .5, 'Curve must fill the available plot, without SVG letterboxing');
        assert.match(await page.getByTestId('analytics-demand').textContent(), /посадок/);
        assert.match(await visible(page.getByTestId('total')).textContent(), /посадок/);
        const controls = await page.evaluate(() => ({route:document.querySelector('.route-field select').getBoundingClientRect().height,day:document.querySelector('.filter-bar__horizon button').getBoundingClientRect().height}));
        assert.ok(Math.abs(controls.route-controls.day) <= 1, 'Route and period controls have equal height');
        assert.equal(await page.getByRole('button',{name:'Маршруты',exact:true}).count(),0);
        assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight));
        await page.getByRole('button',{name:'Карта',exact:true}).click();
        await page.screenshot({path:`${output}/${theme}-${width}.png`});
      }
      for (const width of [390,360,320]) {
        await page.setViewportSize({width,height:844});
        await mobilePane(page, 'Прогноз');
        assert.ok(await page.locator('.workspace-card').isVisible());
        assert.equal(await page.locator('.map-shell').isVisible(),false);
        assert.ok(await range.isVisible());
        await checkPoint(peak);
        assert.ok(await page.getByRole('button',{name:'1 нед',exact:true}).isVisible());
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.screenshot({path:`${output}/${theme}-${width}.png`,fullPage:true});
        await mobilePane(page, 'Карта');
        assert.ok(await page.locator('.workspace-card').isVisible());
        assert.ok(await page.locator('.map-shell').isVisible());
        assert.equal(await page.locator('.forecast-card__visual').isVisible(),false);
        const mobileLayout = await page.evaluate(() => ({map:document.querySelector('.map-shell').getBoundingClientRect().bottom,card:document.querySelector('.workspace-card').getBoundingClientRect().top,actions:document.querySelector('.forecast-card__quick-actions').getBoundingClientRect().bottom,nav:document.querySelector('.mobile-navigation').getBoundingClientRect().top}));
        assert.ok(mobileLayout.map < mobileLayout.card && mobileLayout.actions < mobileLayout.nav, 'Map and summary actions fit above mobile navigation');
        await waitMapSize();
        const camera = await page.locator('.tram-map__viewport svg').getAttribute('viewBox');
        await visible(page.getByRole('button',{name:'График',exact:true})).click();
        assert.ok(await range.isVisible());
        await mobilePane(page, 'Карта');
        await waitMapSize();
        assert.equal(await page.locator('.tram-map__viewport svg').getAttribute('viewBox'),camera);
        await mobilePane(page, 'Прогноз');
        await checkPoint(peak);
      }
      await page.setViewportSize({width:1440,height:900});
    }
    assert.deepEqual(errors,[]);
    console.log(`PASS ${engine.name()}: selected/total/peak, no time/year queries, desktop graph+table, mobile panes, both themes`);
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exitCode=1;});
