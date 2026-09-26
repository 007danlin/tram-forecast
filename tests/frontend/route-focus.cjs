// Unified map/dropdown selection, unsupported routes, and stale-result protection.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium, webkit } = require("playwright");
(async () => {
  const base = process.argv[2];
  assert.equal(new URL(base).hostname, "127.0.0.1");
  const engine = process.env.QA_ENGINE === "webkit" ? webkit : chromium;
  const browser = await engine.launch({ headless: true });
  const out = "artifacts/verification/route-focus";
  fs.mkdirSync(out, { recursive: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      acceptDownloads: true,
    });
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    const errors = [],
      requests = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (r.url().endsWith("/handoff/query")) requests.push(r.postDataJSON());
    });
    const dropdown = page.getByLabel("Маршрут", { exact: true });
    const svg = page.locator(".tram-map__viewport svg");
    await page.goto(base);
    await page.getByTestId("total").waitFor();
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    await dropdown.selectOption("11");
    await page.getByTestId("total").waitFor();
    assert.equal(requests.at(-1).route_ids[0], "11");
    assert.equal(await page.locator("[data-selected-lane]").count(), 2);
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    assert.equal(
      await page.locator("tbody tr").first().getAttribute("data-route"),
      "11",
    );
    const camera = await svg.getAttribute("viewBox"),
      count = requests.length;
    await page
      .getByRole("button", { name: "Включить светлую тему", exact: true })
      .click();
    assert.equal(await svg.getAttribute("viewBox"), camera);
    assert.equal(requests.length, count);
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Скачать CSV", exact: true })
      .click();
    const csv = fs.readFileSync(await (await download).path(), "utf8");
    const rows = csv
      .replace(/^\uFEFF/, "")
      .trim()
      .split(/\r?\n/)
      .map((r) => r.split(","));
    const ri = rows[0].indexOf("route_id");
    assert.ok(ri >= 0);
    assert.ok(rows.slice(1).every((r) => r[ri] === "11"));

    // A late response for an available route cannot fill an unsupported selection.
    let release, fetched;
    const hold = new Promise((resolve) => (release = resolve)),
      started = new Promise((resolve) => (fetched = resolve));
    await page.route("**/handoff/query", async (route) => {
      const response = await route.fetch();
      fetched();
      await hold;
      await route.fulfill({ response }).catch(() => {});
    });
    await dropdown.selectOption("1");
    await started;
    await dropdown.selectOption("36");
    release();
    await page
      .getByText("Для этого маршрута нет прогноза в подключённом пакете.", {
        exact: true,
      })
      .waitFor();
    assert.equal(await page.getByTestId("total").count(), 0);
    assert.equal(await page.locator("tbody tr").count(), 0);
    assert.equal(
      await page
        .getByRole("button", { name: "Скачать CSV", exact: true })
        .isDisabled(),
      true,
    );
    assert.equal(await page.locator("[data-selected-lane]").count(), 5);
    assert.ok((await page.locator("[data-selected-stop]").count()) > 30);
    assert.equal(await page.locator('[data-selected-label="l358"]').count(), 1);
    assert.equal(await page.locator('[data-selected-label="l318"]').count(), 0);
    assert.equal(
      requests.some((r) => r.route_ids.includes("36")),
      false,
    );
    await page.unroute("**/handoff/query");
    // Day changes preserve map focus and never query an unsupported route.
    const focused = await svg.getAttribute("viewBox");
    await page.getByLabel("Дата (МСК)").fill("2025-11-02");
    assert.equal(await svg.getAttribute("viewBox"), focused);
    assert.equal(await page.getByTestId("total").count(), 0);
    await page
      .getByRole("button", { name: "Снять выделение линии", exact: true })
      .click();
    assert.equal(await dropdown.inputValue(), "");
    assert.equal(
      await page
        .locator(
          "[data-selected-lane],[data-selected-stop],[data-selected-label]",
        )
        .count(),
      0,
    );
    assert.equal(
      await page
        .locator(".map-layer--reference")
        .evaluate((e) => getComputedStyle(e).opacity),
      "1",
    );
    assert.equal(await page.getByTestId("total").count(), 0);
    await dropdown.selectOption("11");
    await page.getByTestId("total").waitFor();
    assert.equal(requests.at(-1).route_ids[0], "11");

    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 844 });
      for (const theme of ["light", "dark"]) {
        if ((await page.locator("html").getAttribute("data-theme")) !== theme)
          await page
            .getByRole("button", {
              name:
                theme === "light"
                  ? "Включить светлую тему"
                  : "Включить тёмную тему",
              exact: true,
            })
            .click();
        for (const route of ["36", "11"]) {
          await dropdown.selectOption(route);
          if (route === "11") await page.getByTestId("total").waitFor();
          await page.screenshot({
            path: `${out}/${engine.name()}-${width}-${theme}-${route}.png`,
            fullPage: true,
          });
          assert.equal(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth,
            ),
            true,
          );
        }
      }
    }
    // Slow capabilities must not replace a route already chosen on the map/list.
    const slow = await context.newPage();
    let resume;
    const paused = new Promise((resolve) => (resume = resolve));
    await slow.route("**/handoff/capabilities", async (route) => {
      const response = await route.fetch();
      await paused;
      await route.fulfill({ response });
    });
    await slow.goto(base, { waitUntil: "domcontentloaded" });
    await slow.locator(".tram-map__state").waitFor({ state: "hidden" });
    await slow.getByLabel("Маршрут", { exact: true }).selectOption("36");
    resume();
    await slow
      .getByText("Для этого маршрута нет прогноза в подключённом пакете.", {
        exact: true,
      })
      .waitFor();
    assert.equal(
      await slow.getByLabel("Маршрут", { exact: true }).inputValue(),
      "36",
    );
    assert.equal(await slow.getByTestId("total").count(), 0);
    await slow.close();
    // The full map remains selectable when no release is connected.
    const offline = await context.newPage();
    await offline.route("**/handoff/ready", (r) =>
      r.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"error":{"code":"handoff_unavailable"}}',
      }),
    );
    await offline.goto(base);
    await offline.getByRole("alert").waitFor();
    await offline.getByLabel("Маршрут", { exact: true }).selectOption("36");
    assert.equal(await offline.locator("[data-selected-lane]").count(), 5);
    assert.equal(await offline.getByTestId("total").count(), 0);
    assert.equal(
      await offline
        .getByRole("button", { name: "Скачать CSV", exact: true })
        .isDisabled(),
      true,
    );
    await offline.close();
    // API routes remain usable if the geometry request fails.
    const missing = await context.newPage();
    await missing.route("**/map-local/network.json", (r) => r.abort());
    await missing.goto(base);
    await missing.getByTestId("total").waitFor();
    await missing.getByLabel("Маршрут", { exact: true }).selectOption("11");
    await missing.getByTestId("total").waitFor();
    assert.equal(
      await missing
        .getByRole("button", { name: "Скачать CSV", exact: true })
        .isEnabled(),
      true,
    );
    await missing.close();
    assert.deepEqual(errors, []);
    console.log(
      `PASS ${engine.name()}: shared selection, route CSV, no stale/unsupported forecast, clear selection, slow/missing API, missing geometry, desktop/mobile themes.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
