// Cross-engine smoke for the agreed redesign. Run only against a local handoff stack.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { webkit } = require("playwright");
(async () => {
  const url = process.argv[2];
  assert.equal(new URL(url).hostname, "127.0.0.1");
  const output = "artifacts/verification/evening-shift";
  fs.mkdirSync(output, { recursive: true });
  const browser = await webkit.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      hasTouch: true,
      isMobile: true,
      acceptDownloads: true,
      timezoneId: "America/Los_Angeles",
    });
    context.setDefaultTimeout(15000);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url);
    await page.getByTestId("total").waitFor();
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    const total = await page
      .getByTestId("total")
      .getAttribute("data-raw-value");
    for (const theme of ["dark", "light"]) {
      if (theme === "light")
        await page
          .getByRole("button", { name: "Включить светлую тему", exact: true })
          .click();
      assert.equal(
        await page.getByTestId("total").getAttribute("data-raw-value"),
        total,
      );
      await page.screenshot({
        path: `${output}/webkit-${theme}-390.png`,
        fullPage: true,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
    }
    await page.getByRole("button", { name: "Ещё", exact: false }).click();
    await page.getByRole("button", { name: "1 нед", exact: true }).click();
    await page.getByTestId("total").waitFor();
    await page
      .getByRole("button", { name: "Ещё", exact: false })
      .press("Escape");
    await page
      .getByRole("button", { name: "График, таблица и сведения", exact: true })
      .click();
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    assert.equal(await page.locator(".forecast-card tbody tr").count(), 7);
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Скачать CSV", exact: true })
      .click();
    assert.ok((await download).suggestedFilename().endsWith(".csv"));
    await page
      .getByRole("button", { name: "Открыть меню", exact: true })
      .click();
    await page.getByRole("button", { name: "О данных", exact: true }).click();
    await page.getByRole("dialog", { name: "О данных", exact: true }).waitFor();
    await page
      .getByRole("button", { name: "Закрыть сведения", exact: true })
      .press("Escape");
    await page.waitForFunction(
      () =>
        document.activeElement.getAttribute("aria-label") === "Открыть меню",
    );
    await page
      .getByRole("button", { name: "Линии схемы", exact: true })
      .click();
    await page
      .getByLabel("Выбрать линию", { exact: true })
      .selectOption("brown-9");
    await page
      .getByRole("button", { name: "Линии схемы", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Увеличить область схемы", exact: true })
      .click();
    await page.getByRole("dialog", { name: "Увеличенная схема" }).waitFor();
    await page
      .getByRole("button", { name: "Закрыть увеличенную схему", exact: true })
      .press("Escape");
    assert.equal(
      await page
        .locator('.tram-map__viewport polyline[stroke-width="5"]')
        .count(),
      1,
    );
    await page.reload();
    await page.getByTestId("total").waitFor();
    assert.equal(
      await page.locator("html").getAttribute("data-theme"),
      "light",
    );
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(() =>
        [
          ...document.querySelectorAll(
            "body,h1,h2,p,button,input,select,summary,dt,dd,strong,span",
          ),
        ]
          .map((el) => ({
            el,
            size: parseFloat(getComputedStyle(el).fontSize) * 2,
          }))
          .forEach(({ el, size }) => {
            el.dataset.qaFont = el.style.fontSize;
            el.style.fontSize = size + "px";
          }),
      );
      await page.screenshot({
        path: `${output}/webkit-text-200-${width}.png`,
        fullPage: true,
      });
      const overflow = await page.evaluate(() =>
        [...document.querySelectorAll("body *")]
          .filter(
            (e) =>
              e.getBoundingClientRect().right > innerWidth + 1 &&
              !e.closest(".tram-map__viewport") &&
              e.getBoundingClientRect().width > 0,
          )
          .map((e) => e.tagName + "." + e.className)
          .slice(0, 10),
      );
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
        `text 200% ${width}: ${overflow}`,
      );
      await page.evaluate(() =>
        document.querySelectorAll("[data-qa-font]").forEach((el) => {
          el.style.fontSize = el.dataset.qaFont;
          delete el.dataset.qaFont;
        }),
      );
    }
    assert.deepEqual(errors, []);
    console.log(
      "PASS WebKit mobile: themes, storage, date/week/table/CSV, data dialog focus, map selection/fullscreen, 200% text at 390/1280.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
