const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium, webkit } = require("playwright");
(async () => {
  const base = process.argv[2];
  assert.equal(new URL(base).hostname, "127.0.0.1");
  const engine = process.env.QA_ENGINE === "webkit" ? webkit : chromium;
  const browser = await engine.launch({ headless: true });
  const out = "artifacts/verification/map-continuity";
  fs.mkdirSync(out, { recursive: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    const network = await (
      await page.request.get(base + "/map-local/network.json")
    ).json();
    await page
      .getByRole("button", { name: "Увеличить область схемы", exact: true })
      .click();
    await page.getByRole("button", { name: "Вся схема", exact: true }).click();
    const selected = () =>
      page
        .locator("[data-selected-lane]")
        .evaluateAll((es) => es.map((e) => e.dataset.selectedLane).sort());
    const expected = (lane) =>
      network.lanes
        .filter(
          (l) =>
            JSON.stringify([...l.routes].sort()) ===
            JSON.stringify([...lane.routes].sort()),
        )
        .map((l) => l.id)
        .sort();
    await page
      .getByRole("button", { name: "Линии схемы", exact: true })
      .click();
    const options = await page
      .getByLabel("Выбрать линию", { exact: true })
      .locator("option")
      .evaluateAll((es) =>
        es
          .filter((e) => e.value)
          .map((e) => ({ id: e.value, name: e.textContent })),
      );
    assert.equal(options.length, 35);
    for (const option of options) {
      await page
        .getByLabel("Выбрать линию", { exact: true })
        .selectOption(option.id);
      assert.deepEqual(
        await selected(),
        expected(network.lanes.find((l) => l.id === option.id)),
        option.name,
      );
    }
    await page
      .getByRole("button", { name: "Линии схемы", exact: true })
      .click();
    // Every original fragment is still hittable and selects all of its route, not its colour.
    for (const lane of network.lanes) {
      const segment = lane.points
        .slice(1)
        .map((p, i) => ({
          p,
          a: lane.points[i],
          length: Math.hypot(
            p[0] - lane.points[i][0],
            p[1] - lane.points[i][1],
          ),
        }))
        .sort((a, b) => b.length - a.length)[0];
      const target = [
        (segment.p[0] + segment.a[0]) / 2,
        (segment.p[1] + segment.a[1]) / 2,
      ];
      const point = await page
        .locator(".tram-map__viewport svg")
        .evaluate((svg, p) => {
          const v = svg.viewBox.baseVal,
            r = svg.getBoundingClientRect();
          return {
            x: r.x + ((p[0] - v.x) * r.width) / v.width,
            y: r.y + ((p[1] - v.y) * r.height) / v.height,
          };
        }, target);
      await page.mouse.click(point.x, point.y);
      const candidates = page.getByRole("group", {
        name: "Уточните линию",
        exact: true,
      });
      if (await candidates.isVisible()) {
        const option = options.find((o) => expected(lane).includes(o.id));
        await candidates
          .getByRole("button", { name: option.name, exact: true })
          .click();
      }
      assert.deepEqual(await selected(), expected(lane), `Click ${lane.id}`);
    }
    // High-zoom screenshots at every repaired crossing and terminal loop.
    for (const [name, id, x, y, scale] of [
      ["36-semenovskaya", "red-1", 789, 533, 7],
      ["11-bogorodskoe", "brown-9", 724, 385, 10],
      ["36-perovo", "red-1", 895, 613, 12],
      ["t2-perovo", "red-2", 895, 613, 12],
      ["36-novogireevo", "red-1", 992, 563, 8],
      ["t2-novogireevo", "red-2", 992, 563, 8],
      ["50-terminal", "teal-2", 450, 589, 14],
    ]) {
      await page
        .getByRole("button", { name: "Вся схема", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Линии схемы", exact: true })
        .click();
      const representative = options.find((o) =>
        expected(network.lanes.find((l) => l.id === id)).includes(o.id),
      );
      await page
        .getByLabel("Выбрать линию", { exact: true })
        .selectOption(representative.id);
      await page
        .getByRole("button", { name: "Линии схемы", exact: true })
        .click();
      const bounds = await page.locator(".tram-map__viewport svg").evaluate(
        (svg, p) => {
          const v = svg.viewBox.baseVal,
            r = svg.getBoundingClientRect();
          return {
            x: r.x + ((p[0] - v.x) * r.width) / v.width,
            y: r.y + ((p[1] - v.y) * r.height) / v.height,
            scale: r.width / v.width,
            cx: r.x + r.width / 2,
            cy: r.y + r.height / 2,
          };
        },
        [x, y],
      );
      await page.mouse.move(bounds.x, bounds.y);
      await page.mouse.wheel(0, -Math.log(scale / bounds.scale) / 0.0015);
      await page.waitForFunction(
        (before) =>
          document.querySelector(".tram-map__viewport svg").viewBox.baseVal
            .width < before,
        bounds.scale ? 1280 / bounds.scale : 2000,
      );
      const anchor = await page.locator(".tram-map__viewport svg").evaluate(
        (svg, p) => {
          const v = svg.viewBox.baseVal,
            r = svg.getBoundingClientRect();
          return {
            x: r.x + ((p[0] - v.x) * r.width) / v.width,
            y: r.y + ((p[1] - v.y) * r.height) / v.height,
          };
        },
        [x, y],
      );
      await page.mouse.move(anchor.x, anchor.y);
      await page.mouse.down();
      await page.mouse.move(bounds.cx, bounds.cy, { steps: 10 });
      await page.mouse.up();
      await page.screenshot({ path: `${out}/${engine.name()}-${name}.png` });
    }
    assert.deepEqual(errors, []);
    console.log(
      `PASS ${engine.name()}: 35 route choices, all 45 lane clicks, entire matching route selected, 7 crossing/loop screenshots.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
