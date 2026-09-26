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
    const dropdown = page.getByLabel("Маршрут", { exact: true });
    assert.equal(
      await page
        .getByRole("button", { name: "Линии схемы", exact: true })
        .count(),
      0,
    );
    const options = [
      ...new Map(
        network.lanes.map((lane) => [
          JSON.stringify([...lane.routes].sort()),
          lane,
        ]),
      ).values(),
    ];
    assert.equal(options.length, 35);
    for (const lane of options) {
      await dropdown.selectOption(lane.routes[0]);
      assert.deepEqual(await selected(), expected(lane), lane.routes.join("/"));
      const ids = new Set(expected(lane));
      assert.deepEqual(
        await page
          .locator("[data-selected-stop]")
          .evaluateAll((es) => es.map((e) => e.dataset.selectedStop).sort()),
        network.stops
          .filter((s) => ids.has(s.lane))
          .map((s) => s.id)
          .sort(),
      );
      assert.deepEqual(
        await page
          .locator("[data-selected-label]")
          .evaluateAll((es) => es.map((e) => e.dataset.selectedLabel).sort()),
        network.labels
          .filter((l) => l.lanes.some((id) => ids.has(id)) ||
            network.stationSymbols.some((g) => g.labels.includes(l.id) &&
              g.lanes.some((id) => ids.has(id))))
          .map((l) => l.id)
          .sort(),
      );
      assert.equal(
        await page
          .locator(".map-layer--reference")
          .evaluate((e) => getComputedStyle(e).opacity),
        "0.4",
      );
      assert.deepEqual(
        await page.locator("[data-selected-symbol]")
          .evaluateAll((es) => es.map((e) => e.dataset.selectedSymbol).sort()),
        network.stationSymbols.filter((g) => g.lanes.some((id) => ids.has(id)))
          .map((g) => g.id).sort(),
        `Station symbols ${lane.routes.join("/")}`,
      );
    }
    await page
      .getByRole("button", { name: "Увеличить сайт", exact: true })
      .click();
    // Every original fragment is still hittable and selects all of its route, not its colour.
    for (const lane of network.lanes) {
      await page
        .getByRole("button", { name: "Вся схема", exact: true })
        .click();
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
          .getByRole("button", {
            name: option.routes.map((n) => "№ " + n).join(", "),
            exact: true,
          })
          .click();
      }
      assert.deepEqual(await selected(), expected(lane), `Click ${lane.id}`);
      const ids = new Set(expected(lane));
      assert.deepEqual(
        await page.locator("[data-selected-symbol]")
          .evaluateAll((es) => es.map((e) => e.dataset.selectedSymbol).sort()),
        network.stationSymbols.filter((g) => g.lanes.some((id) => ids.has(id)))
          .map((g) => g.id).sort(),
        `Station symbols after map click ${lane.id}`,
      );
      assert.equal(
        await dropdown.inputValue(),
        lane.routes[0],
        `Shared map/dropdown selection ${lane.id}`,
      );
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
      ["50-miit", "teal-3", 450, 514, 14],
      ["1-chertanovskaya", "brown-1", 559, 1137, 14],
      ["t2-chertanovskaya", "red-2", 550, 1119, 14],
      ["7-sokolniki", "orange-4", 690, 499, 14],
      ["5-belorussky", "purple-7", 373, 576, 14],
      ["13-three-stations", "yellow-1", 617, 599, 14],
      ["47-kolomenskaya", "cyan-4", 658, 998, 14],
      ["4-rokossovskogo", "blue-3", 851, 386, 12],
      ["7-rokossovskogo", "orange-4", 851, 386, 12],
      ["10-shchukinskaya", "lilac-2", 333, 456, 12],
      ["12-dubrovka", "gray-0", 770, 839, 12],
      ["28-sokol", "gray-1", 407, 455, 12],
      ["t1-metrogorodok", "green2-0", 902, 315, 12],
      ["16-danilovskaya", "teal-1", 550, 953, 14],
    ]) {
      await page
        .getByRole("button", { name: "Закрыть увеличенную схему", exact: true })
        .click();
      await dropdown.selectOption(
        network.lanes.find((l) => l.id === id).routes[0],
      );
      await page
        .getByRole("button", { name: "Увеличить сайт", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Вся схема", exact: true })
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
      const shot = await page.screenshot({ path: `${out}/${engine.name()}-${name}.png` });
      if (name.endsWith("-rokossovskogo")) {
        // Sample the actual rendered screen: DOM presence alone would miss a
        // faded/broken external SVG use. Both plates stay bright for either route.
        const pixels = await page.evaluate(async (png) => {
          const image = new Image();
          image.src = "data:image/png;base64," + png;
          await image.decode();
          const canvas = document.createElement("canvas");
          canvas.width = image.width;
          canvas.height = image.height;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(image, 0, 0);
          const matrix = document.querySelector(".tram-map__viewport svg").getScreenCTM();
          return [[828, 390.5], [841, 390.5]].map(([x, y]) => {
            const p = new DOMPoint(x, y).matrixTransform(matrix);
            return Array.from(ctx.getImageData(Math.round(p.x), Math.round(p.y), 1, 1).data);
          });
        }, shot.toString("base64"));
        for (const [i, expected] of [[0, 131, 200, 255], [246, 134, 31, 255]].entries())
          assert.ok(expected.every((channel, j) => Math.abs(channel - pixels[i][j]) <= 4),
            `${name}: station plate ${i === 0 ? 4 : 7} is faded: ${pixels[i]}`);
      }
    }
    assert.deepEqual(errors, []);
    console.log(
      `PASS ${engine.name()}: 35 route choices, all 45 lane clicks, matching station symbols, 21 crossing/loop/transfer/terminal screenshots.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
