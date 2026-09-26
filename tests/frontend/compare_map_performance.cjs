// Same-machine diagnostic, not a backend load benchmark. No forecast values saved.
const { chromium } = require("playwright");
const fs = require("node:fs");
(async () => {
  const [before, after, destination] = process.argv.slice(2);
  for (const url of [before, after])
    if (new URL(url).hostname !== "127.0.0.1")
      throw new Error("Local URLs only");
  const browser = await chromium.launch({ headless: true });
  const results = {};
  try {
    for (const [name, url] of [
      ["before", before],
      ["after", after],
    ]) {
      const samples = [];
      for (let i = 0; i < 3; i++) {
        const context = await browser.newContext({
          viewport: { width: 1280, height: 800 },
        });
        await context.addInitScript(() => {
          window.qaLongTasks = [];
          new PerformanceObserver((list) =>
            window.qaLongTasks.push(
              ...list
                .getEntries()
                .map((e) => ({ start: e.startTime, duration: e.duration })),
            ),
          ).observe({ type: "longtask", buffered: true });
        });
        const page = await context.newPage();
        await page.goto(url);
        await page.getByTestId("total").waitFor();
        const controlsMs = await page.evaluate(() => performance.now());
        await page.locator(".tram-map__viewport svg").waitFor();
        await page.locator(".tram-map__state").waitFor({ state: "hidden" });
        await page.evaluate(() => document.fonts.ready);
        const mapReadyMs = await page.evaluate(() => performance.now());
        const viewport = page.locator(".tram-map__viewport");
        const box = await viewport.boundingBox();
        const panStart = await page.evaluate(() => performance.now());
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.down();
        await page.mouse.move(
          box.x + box.width / 2 + 120,
          box.y + box.height / 2 + 60,
          { steps: 40 },
        );
        await page.mouse.up();
        const measurement = await page.evaluate(
          (start) => ({
            mapResources: performance
              .getEntriesByType("resource")
              .filter((e) => e.name.includes("/map-local/"))
              .map((e) => ({
                name: e.name.split("/").pop(),
                bytes: e.decodedBodySize,
                duration: e.duration,
              })),
            panLongTasks: window.qaLongTasks.filter((t) => t.start >= start),
            maxStartupTask: Math.max(
              0,
              ...window.qaLongTasks
                .filter((t) => t.start < start)
                .map((t) => t.duration),
            ),
          }),
          panStart,
        );
        samples.push({ controlsMs, mapReadyMs, ...measurement });
        await context.close();
      }
      const median = (key) =>
        samples.map((s) => s[key]).sort((a, b) => a - b)[1];
      results[name] = {
        medianControlsMs: median("controlsMs"),
        medianMapReadyMs: median("mapReadyMs"),
        samples,
      };
    }
    fs.writeFileSync(
      destination,
      JSON.stringify(
        {
          environment:
            "Chromium headless, macOS, 1280x800, local Vite, cold browser contexts; 3 samples; no network throttling",
          ...results,
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify(
        Object.fromEntries(
          Object.entries(results).map(([k, v]) => [
            k,
            {
              controlsMs: Math.round(v.medianControlsMs),
              mapReadyMs: Math.round(v.medianMapReadyMs),
              panLongTasks: v.samples.map((s) => s.panLongTasks.length),
            },
          ]),
        ),
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
