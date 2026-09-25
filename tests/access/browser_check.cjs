// Optional browser QA. Playwright comes from the operator's test runtime, not production.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const input = fs.readFileSync(0, 'utf8');
  const { baseURL, username, password, screenshot } = JSON.parse(input);
  assert.equal(new URL(baseURL).hostname, 'localhost');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    // The temporary CA is not installed in the OS. Python tests validate its chain.
    const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
    for (const path of ['/', '/map-local/network.json', '/api/v1/forecast']) {
      assert.equal((await anonymous.request.get(baseURL + path)).status(), 401);
    }
    const unauthPage = await anonymous.newPage();
    try { await unauthPage.goto(baseURL); } catch (error) {
      assert.match(error.message, /ERR_INVALID_AUTH_CREDENTIALS/);
    }
    assert.equal(await unauthPage.getByRole('heading', { name: 'Пассажиропоток трамваев' }).count(), 0);
    await anonymous.close();
    const wrong = await browser.newContext({ ignoreHTTPSErrors: true,
      httpCredentials: { username, password: 'invalid-for-test' } });
    assert.equal((await wrong.request.get(baseURL + '/api/v1/forecast')).status(), 401);
    await wrong.close();
    const authorized = await browser.newContext({ ignoreHTTPSErrors: true,
      httpCredentials: { username, password }, viewport: { width: 1440, height: 1000 } });
    const page = await authorized.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(baseURL);
    await page.getByRole('alert').filter({hasText:'Готовый пакет прогноза отсутствует'}).waitFor();
    assert.equal(await page.locator('tbody tr').count(),0);
    assert.equal(await page.getByRole('button',{name:'Скачать CSV'}).isDisabled(),true);
    assert.equal((await authorized.request.get(baseURL + '/map-local/network.json')).status(),200);
    // Authentication still protects v1, but the product screen uses real handoff.
    const legacy = await (await authorized.request.get(baseURL+'/api/v1/forecast')).json();
    assert.deepEqual(legacy.points.map(p => p.value),[12,18,15,24,21,16]);
    await page.getByRole('button',{name:'Повторить запрос',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'Готовый пакет прогноза отсутствует'}).waitFor();
    assert.deepEqual(errors, []);
    if (screenshot) await page.screenshot({ path: screenshot, fullPage: true });
    await authorized.close();
    const fresh = await browser.newContext({ ignoreHTTPSErrors: true });
    assert.equal((await fresh.request.get(baseURL + '/api/v1/health')).status(), 401);
    await fresh.close();
    console.log('PASS: fresh anonymous/wrong-password contexts blocked; authenticated UI/map/v1; missing handoff stays explicit after retry; fresh context requires login again.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
