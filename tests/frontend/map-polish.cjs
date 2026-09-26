const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium, webkit } = require("playwright");
(async () => {
  const base = process.argv[2];
  assert.equal(new URL(base).hostname, "127.0.0.1");
  const engine = process.env.QA_ENGINE === "webkit" ? webkit : chromium;
  const browser = await engine.launch({ headless: true });
  const out = "artifacts/verification/map-polish";
  fs.mkdirSync(out, { recursive: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    assert.equal(await page.title(), "TramFlow");
    const icon = await page.locator("link[rel=icon]").getAttribute("href");
    const response = await page.request.get(new URL(icon, base).href);
    assert.equal(response.status(), 200);
    assert.match(await response.text(), /viewBox="952 134 132 132"/);
    await page.getByLabel("Маршрут", { exact: true }).selectOption("50");
    assert.equal(await page.locator("path[data-selected-lane]").count(), 3);
    assert.equal(await page.locator("polyline[data-selected-lane]").count(), 0);
    const d = await page
      .locator('[data-selected-lane="teal-3"]')
      .getAttribute("d");
    assert.ok(d.includes("C"));
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 844 });
      for (const theme of ["dark", "light"]) {
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
        await page.getByLabel("Маршрут", { exact: true }).selectOption("");
        await page
          .getByRole("button", { name: "Вся схема", exact: true })
          .click();
        const svg = page.locator(".tram-map__viewport svg");
        const before = await svg.getAttribute("viewBox");
        await page
          .getByRole("button", { name: "Уменьшить", exact: true })
          .click();
        assert.equal(
          await svg.getAttribute("viewBox"),
          before,
          "Minimum zoom still fits whole map",
        );
        assert.equal(
          await svg.evaluate((e) => getComputedStyle(e).backgroundColor),
          "rgb(237, 238, 237)",
        );
        assert.equal(
          await page
            .locator(".tram-map__stage")
            .evaluate((e) => getComputedStyle(e).backgroundColor),
          "rgb(237, 238, 237)",
        );
        await page.screenshot({
          path: `${out}/${engine.name()}-${width}-${theme}-whole.png`,
          fullPage: true,
        });
      }
    }
    // Enlarged clean map corners: no poster emblem, footer heading or white frame.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page
      .getByRole("button", { name: "Увеличить область схемы", exact: true })
      .click();
    for (const [name, x, y, scale] of [
      ["emblem-removed", 1018, 200, 4],
      ["footer-removed", 210, 1287, 4],
    ]) {
      await page
        .getByRole("button", { name: "Вся схема", exact: true })
        .click();
      const info = await page.locator(".tram-map__viewport svg").evaluate(
        (svg, p) => {
          const b = svg.viewBox.baseVal,
            r = svg.getBoundingClientRect();
          return {
            x: r.x + ((p[0] - b.x) * r.width) / b.width,
            y: r.y + ((p[1] - b.y) * r.height) / b.height,
            scale: r.width / b.width,
          };
        },
        [x, y],
      );
      await page.mouse.move(info.x, info.y);
      await page.mouse.wheel(0, -Math.log(scale / info.scale) / 0.0015);
      await page.waitForFunction((s) => {
        const e = document.querySelector(".tram-map__viewport svg");
        return e.getBoundingClientRect().width / e.viewBox.baseVal.width > s;
      }, info.scale * 1.1);
      await page.screenshot({ path: `${out}/${engine.name()}-${name}.png` });
    }
    assert.deepEqual(errors, []);
    console.log(
      `PASS ${engine.name()}: smooth selected paths, TramFlow title, local heart favicon, seamless paper at minimum zoom, mobile/desktop themes.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
