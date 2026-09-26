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
    // Render the shipped SVG in the browser. These PDF-verified interior samples
    // catch white compound frames accidentally covering the lower Kremlin tower.
    const kremlin = await page.evaluate(async () => {
      const source = await (await fetch("/map-local/schematic.svg")).text();
      const svg = new DOMParser().parseFromString(source, "image/svg+xml")
        .documentElement;
      svg.setAttribute("viewBox", "536 665 17 35");
      svg.setAttribute("width", "408");
      svg.setAttribute("height", "840");
      let url = URL.createObjectURL(new Blob(
        [new XMLSerializer().serializeToString(svg)],
        { type: "image/svg+xml" },
      ));
      try {
        const image = new Image();
        image.src = url;
        await image.decode();
        const canvas = document.createElement("canvas");
        canvas.width = 408;
        canvas.height = 840;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(image, 0, 0);
        const sample = (x, y, originX = 536, originY = 665) => Array.from(ctx.getImageData(
          Math.round((x - originX) * 24), Math.round((y - originY) * 24), 1, 1,
        ).data);
        const result = {
          red: [
            [544, 678.7], [544, 688.5], [544, 691.48],
            [544, 693.3], [539.5, 693.3], [548.3, 693.3],
            ...Array.from({ length: 6 }, (_, i) => [541.52 + i * 0.951, 689.4]),
          ].map(([x, y]) => sample(x, y)),
          white: [
            [538.9, 693.3], [544, 691.23], [544, 691.79],
            ...Array.from({ length: 7 }, (_, i) => [541.045 + i * 0.951, 689.4]),
          ].map(([x, y]) => sample(x, y)),
          png: canvas.toDataURL("image/png").split(",")[1],
        };
        // Bratsevo also combines rectangles with ordinary line subpaths.
        // Their winding must agree, otherwise the facade turns solid white.
        URL.revokeObjectURL(url);
        svg.setAttribute("viewBox", "116 315 17 35");
        url = URL.createObjectURL(new Blob(
          [new XMLSerializer().serializeToString(svg)],
          { type: "image/svg+xml" },
        ));
        image.src = url;
        await image.decode();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0);
        result.brown = [[124, 334.1], [129.5, 329], [132.5, 325.4]]
          .map(([x, y]) => sample(x, y, 116, 315));
        return result;
      } finally {
        URL.revokeObjectURL(url);
      }
    });
    for (const [i, pixel] of kremlin.red.entries())
      assert.ok(pixel[0] > 190 && pixel[1] < 70 && pixel[2] < 70 && pixel[3] === 255,
        `Kremlin red wall/neck/stripe ${i} must not be covered: ${pixel}`);
    for (const [i, pixel] of kremlin.white.entries())
      assert.ok(pixel.every((channel) => channel > 245),
        `Kremlin white window/border ${i} must remain visible: ${pixel}`);
    for (const [i, pixel] of kremlin.brown.entries())
      assert.ok([171, 106, 87, 255].every((c, j) => Math.abs(c - pixel[j]) < 8),
        `Bratsevo facade ${i} must retain mixed-path cutouts: ${pixel}`);
    fs.writeFileSync(`${out}/${engine.name()}-kremlin-detail.png`,
      Buffer.from(kremlin.png, "base64"));
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
      ["kremlin-restored", 544, 684, 12],
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
      `PASS ${engine.name()}: Kremlin walls, seven windows and borders; smooth selected paths, TramFlow title, local heart favicon, seamless paper at minimum zoom, mobile/desktop themes.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
