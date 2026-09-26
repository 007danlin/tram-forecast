const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");
const close = (a, b) =>
  assert.ok(Math.abs(a - b) <= 1e-9 + 1e-12 * Math.abs(b), `${a} != ${b}`);
(async () => {
  const { baseURL, forecast, output, sourceKind } = JSON.parse(
    fs.readFileSync(0, "utf8"),
  );
  assert.equal(new URL(baseURL).hostname, "127.0.0.1");
  const original = fs
    .readFileSync(forecast, "utf8")
    .trim()
    .split(/\r?\n/)
    .slice(1)
    .map((line) => {
      const [route, date, hour, prediction] = line.split(";");
      return { route, date, hour: Number(hour), value: Number(prediction) };
    });
  const browser = await chromium.launch({
    channel: process.env.QA_BROWSER || "chromium",
    headless: true,
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1366, height: 768 },
      timezoneId: "America/Los_Angeles",
      acceptDownloads: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    // A fresh clone has no private release: explain readiness, then recover.
    await page.route("**/handoff/ready", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"error":{"code":"handoff_unavailable"}}',
      }),
    );
    await page.goto(baseURL);
    await page.getByRole("alert").waitFor();
    assert.match(
      await page.getByRole("alert").textContent(),
      /пакет прогноза отсутствует или недоступен/,
    );
    assert.equal(await page.getByTestId("total").count(), 0);
    assert.equal(
      await page.getByRole("button", { name: "Скачать CSV" }).isDisabled(),
      true,
    );
    await page.unroute("**/handoff/ready");
    await page
      .getByRole("button", { name: "Повторить запрос", exact: true })
      .click();
    await page.getByTestId("total").waitFor();
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    await page.getByRole("button", { name: "Свернуть карточку" }).click();
    await page.locator(".tram-map__viewport svg").waitFor();
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    await page
      .locator(".tram-map__viewport")
      .evaluate((el) => (el.qaIdentity = "persistent"));
    const mapViewport = page.locator(".tram-map__viewport");
    const mapSvg = mapViewport.locator("svg");
    const network = await (
      await page.request.get(baseURL + "/map-local/network.json")
    ).json();
    await mapViewport.press("0");
    const initialView = await mapSvg.getAttribute("viewBox");
    await mapViewport.focus();
    await mapViewport.press("ArrowRight");
    await page.waitForFunction(
      (initial) =>
        document
          .querySelector(".tram-map__viewport svg")
          .getAttribute("viewBox") !== initial,
      initialView,
    );
    await mapViewport.press("+");
    await mapViewport.press("0");
    await page.waitForFunction(
      (initial) =>
        document
          .querySelector(".tram-map__viewport svg")
          .getAttribute("viewBox") === initial,
      initialView,
    );
    // All 45 map hit targets are exercised by map-continuity.cjs.
    await page.getByRole("button", { name: "Открыть прогноз" }).click();
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    const horizonLabels = { day: "1 день", week: "1 нед", month: "1 мес" };
    async function setHorizon(value) {
      await page
        .getByRole("button", { name: horizonLabels[value], exact: true })
        .click();
    }
    async function checkRows(count) {
      const selectedRoute = await page
        .getByLabel("Маршрут", { exact: true })
        .inputValue();
      const selectedDay = await page.getByLabel("Дата (МСК)").inputValue();
      const horizonText = await page
        .locator(".filter-bar__horizon [aria-pressed=true]")
        .getAttribute("aria-label");
      const selectedHorizon = Object.keys(horizonLabels).find(
        (key) => horizonLabels[key] === horizonText,
      );
      const firstDay =
        selectedHorizon === "month"
          ? selectedDay.slice(0, 7) + "-01"
          : selectedDay;
      const expectedRows = Array.from({ length: count }, (_, i) => {
        const stamp = new Date(
          Date.parse(firstDay + "T00:00:00Z") +
            i * (selectedHorizon === "day" ? 3600000 : 86400000),
        );
        const start = stamp.toISOString().slice(0, 19) + "+03:00";
        const value = original
          .filter(
            (r) =>
              r.route === selectedRoute &&
              r.date === start.slice(0, 10) &&
              (selectedHorizon === "day"
                ? r.hour === stamp.getUTCHours()
                : true),
          )
          .reduce((sum, r) => sum + r.value, 0);
        return { route: selectedRoute, start, value };
      });
      // A previous no_data result also has 24 rows: wait for the requested
      // values and keys, not merely row count, before inspecting the new view.
      await page.waitForFunction((expected) => {
        const rows = [...document.querySelectorAll("tbody tr")];
        return (
          rows.length === expected.length &&
          rows.every((row, i) => {
            const raw = row.querySelector("[data-raw-value]")?.dataset.rawValue;
            return (
              row.dataset.route === expected[i].route &&
              row.dataset.start === expected[i].start &&
              raw !== "" &&
              raw !== undefined &&
              Math.abs(Number(raw) - expected[i].value) <=
                1e-9 + 1e-12 * Math.abs(expected[i].value)
            );
          })
        );
      }, expectedRows);
      const rows = await page.locator("tbody tr").evaluateAll((elements) =>
        elements.map((row) => ({
          start: row.dataset.start,
          route: row.dataset.route,
          value: row.querySelector("[data-raw-value]").dataset.rawValue,
        })),
      );
      let total = 0;
      for (const row of rows) {
        const expected = original
          .filter(
            (r) =>
              r.route === row.route &&
              r.date === row.start.slice(0, 10) &&
              (count === 24
                ? r.hour === Number(row.start.slice(11, 13))
                : true),
          )
          .reduce((sum, r) => sum + r.value, 0);
        close(Number(row.value), expected);
        total += expected;
      }
      close(
        Number(await page.getByTestId("total").getAttribute("data-raw-value")),
        total,
      );
      assert.equal(
        await page
          .locator(".tram-map__viewport")
          .evaluate((el) => el.qaIdentity),
        "persistent",
      );
      assert.deepEqual(
        await mapSvg
          .locator("[data-selected-lane]")
          .evaluateAll((lines) =>
            lines.map((l) => l.dataset.selectedLane).sort(),
          ),
        network.lanes
          .filter((l) => l.routes.includes(selectedRoute))
          .map((l) => l.id)
          .sort(),
      );
    }
    await checkRows(24);
    await setHorizon("week");
    await checkRows(7);
    await setHorizon("month");
    await checkRows(30);
    await page.getByLabel("Дата (МСК)").fill("2025-12-01");
    await checkRows(31);
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "Скачать CSV" }).click();
    const download = await downloaded;
    const csv = fs
      .readFileSync(await download.path(), "utf8")
      .replace(/^\uFEFF/, "")
      .trim()
      .split(/\r?\n/);
    const fields = csv[0].split(",");
    assert.equal(csv.length, 32);
    for (const line of csv.slice(1)) {
      const cells = line.split(",");
      const get = (key) => cells[fields.indexOf(key)];
      const expected = original
        .filter(
          (r) =>
            r.route === get("route_id") && r.date === get("start").slice(0, 10),
        )
        .reduce((sum, r) => sum + r.value, 0);
      close(Number(get("value")), expected);
      assert.equal(
        get("forecast_run_id"),
        await page.getByTestId("run").textContent(),
      );
    }
    await page.getByLabel("Маршрут", { exact: true }).selectOption("5");
    await page.waitForFunction(
      () =>
        document.querySelector("[data-testid=total]")?.dataset.rawValue === "0",
    );
    await checkRows(31);
    assert.equal(
      await page
        .getByText("Нет истории обучения: модель возвращает 0.", {
          exact: false,
        })
        .count(),
      1,
    );
    // Old responses cannot overwrite a newer filter selection.
    await page.route("**/handoff/query", async (route) => {
      const response = await route.fetch();
      if (route.request().postDataJSON().route_ids[0] === "1")
        await new Promise((r) => setTimeout(r, 350));
      await route.fulfill({ response }).catch((e) => {
        if (!/already handled|closed|aborted/i.test(e.message)) throw e;
      });
    });
    await page.getByLabel("Маршрут", { exact: true }).selectOption("1");
    assert.equal(
      await page.getByRole("button", { name: "Скачать CSV" }).isDisabled(),
      true,
    );
    await page.getByLabel("Маршрут", { exact: true }).selectOption("7");
    await page.waitForFunction(
      () => document.querySelector("tbody tr")?.dataset.route === "7",
    );
    await checkRows(31);
    await page.unroute("**/handoff/query");
    // Out-of-range errors survive chart/table/details changes; export stays blocked.
    await page.getByRole("button", { name: "График", exact: true }).click();
    await setHorizon("week");
    await page.getByLabel("Дата (МСК)").fill("2025-12-29");
    await page.getByRole("alert").waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Скачать CSV" }).isDisabled(),
      true,
    );
    assert.equal(
      await page.locator(".app-shell__badge--ok").textContent(),
      "Данные загружены",
    );
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    await page.getByRole("alert").waitFor();
    await page.locator(".forecast-card__details summary").click();
    await page.getByRole("alert").waitFor();
    await page.getByLabel("Дата (МСК)").fill("2025-11-01");
    await setHorizon("day");
    await checkRows(24);
    for (const status of [503, 410]) {
      await page.route("**/handoff/query", (route) =>
        route.fulfill({
          status,
          contentType: "application/json",
          body: '{"error":{"code":"fixture"}}',
        }),
      );
      await page
        .getByRole("button", { name: "Обновить прогноз", exact: true })
        .click();
      await page.getByRole("alert").waitFor();
      assert.equal(
        await page.getByRole("button", { name: "Скачать CSV" }).isDisabled(),
        true,
      );
      await page.unroute("**/handoff/query");
      const refreshed = page.waitForResponse(
        (r) => r.url().endsWith("/handoff/query") && r.status() === 200,
      );
      await page
        .getByRole("button", {
          name:
            status === 410 ? "Обновить доступные данные" : "Повторить запрос",
          exact: true,
        })
        .click();
      await refreshed;
      await checkRows(24);
    }
    await page.route("**/handoff/export", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: '{"error":{"code":"fixture"}}',
      }),
    );
    await page.getByRole("button", { name: "Скачать CSV" }).click();
    await page.getByRole("alert").waitFor();
    assert.equal(
      await page.locator(".app-shell__badge--ok").textContent(),
      "Данные загружены",
    );
    assert.equal(
      await page.getByRole("button", { name: "Скачать CSV" }).isDisabled(),
      true,
    );
    await page.unroute("**/handoff/export");
    await page
      .getByRole("button", { name: "Повторить запрос", exact: true })
      .click();
    await checkRows(24);
    for (const empty of [false, true]) {
      await page.route("**/handoff/query", async (route) => {
        const response = await route.fetch();
        const data = await response.json();
        for (const row of empty ? data.rows : [data.rows[12]]) {
          row.value = null;
          row.reference_value = null;
          row.lower_90 = null;
          row.upper_90 = null;
          row.priority_score = null;
          row.available_hours = 0;
          row.coverage = 0;
          row.status = "no_data";
        }
        data.total = empty
          ? null
          : data.rows.reduce((sum, r) => sum + (r.value ?? 0), 0);
        data.coverage = empty ? 0 : 23 / 24;
        data.total_scope = empty ? "no_data" : "available_only";
        await route.fulfill({ response, json: data });
      });
      await page
        .getByRole("button", { name: "Обновить прогноз", exact: true })
        .click();
      await page
        .getByText(
          empty ? "Нет данных за период." : "Есть пропуски · покрытие",
          { exact: false },
        )
        .waitFor();
      assert.equal(
        await page
          .locator("tbody tr")
          .nth(12)
          .locator("[data-raw-value]")
          .getAttribute("data-raw-value"),
        "",
      );
      const timeControl = page.getByLabel("Точка временного ряда");
      await timeControl.focus();
      await timeControl.press("Home");
      for (let i = 0; i < 12; i++) await timeControl.press("ArrowRight");
      assert.equal(await page.getByTestId("map-demand").textContent(), "Нет данных");
      assert.equal(await page.getByTestId("map-demand").getAttribute("data-raw-value"), "");
      if (empty) assert.equal(await page.getByRole("button", {name:"Пик", exact:true}).isDisabled(), true);
      await page.unroute("**/handoff/query");
    }
    await page
      .getByRole("button", { name: "Обновить прогноз", exact: true })
      .click();
    await checkRows(24);
    await page.getByRole("button", { name: "График", exact: true }).click();
    await page
      .locator(".forecast-card__details")
      .evaluate((el) => (el.open = false));
    await page.screenshot({ path: output + "/desktop.png", fullPage: true });
    const retainedView = await mapSvg.getAttribute("viewBox");
    await page.getByRole("button", { name: "Аналитика", exact: true }).click();
    assert.equal(await page.locator(".analytics-view tbody tr").count(), 24);
    await page
      .getByRole("button", { name: "Карта и прогноз", exact: true })
      .click();
    // ResizeObserver restores the viewport asynchronously after display:none.
    await page.waitForFunction(
      (expected) =>
        document
          .querySelector(".tram-map__viewport svg")
          ?.getAttribute("viewBox") === expected,
      retainedView,
    );
    assert.equal(await mapSvg.getAttribute("viewBox"), retainedView);
    assert.equal(
      await mapViewport.evaluate((el) => el.qaIdentity),
      "persistent",
    );
    await page.getByRole("button", { name: "О данных", exact: true }).click();
    await page.getByRole("dialog", { name: "О данных", exact: true }).waitFor();
    await page
      .getByRole("dialog", { name: "О данных", exact: true })
      .press("Escape");
    assert.equal(
      await page
        .getByRole("button", { name: "О данных", exact: true })
        .getAttribute("aria-expanded"),
      "false",
    );
    await page.getByRole("button", { name: "Свернуть карточку" }).click();
    await page.getByRole("button", { name: "Открыть прогноз" }).click();
    await page.locator(".forecast-card").press("Escape");
    await page.waitForFunction(
      () => document.activeElement?.textContent === "Открыть прогноз",
    );
    await page.getByRole("button", { name: "Открыть прогноз" }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      true,
    );
    await page.screenshot({ path: output + "/mobile.png", fullPage: true });
    const mobileView = await mapSvg.getAttribute("viewBox");
    await page.getByRole("button", { name: "Увеличить", exact: true }).click();
    await page.waitForFunction(
      (before) =>
        document
          .querySelector(".tram-map__viewport svg")
          ?.getAttribute("viewBox") !== before,
      mobileView,
    );
    // Theme changes retain context, camera, point selection and result without network.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page
      .getByRole("button", { name: "Включить тёмную тему", exact: true })
      .click();
    const totalBefore = await page
      .getByTestId("total")
      .getAttribute("data-raw-value");
    const cameraBefore = await mapSvg.getAttribute("viewBox");
    const routeBefore = await page
      .getByLabel("Маршрут", { exact: true })
      .inputValue();
    let queries = 0;
    const countQuery = (request) => {
      if (request.url().endsWith("/handoff/query")) queries++;
    };
    page.on("request", countQuery);
    await page
      .getByRole("button", { name: "Включить светлую тему", exact: true })
      .click();
    assert.equal(
      await page.locator("html").getAttribute("data-theme"),
      "light",
    );
    assert.equal(
      await page.getByTestId("total").getAttribute("data-raw-value"),
      totalBefore,
    );
    assert.equal(await mapSvg.getAttribute("viewBox"), cameraBefore);
    assert.equal(
      await page.getByLabel("Маршрут", { exact: true }).inputValue(),
      routeBefore,
    );
    assert.equal(queries, 0);
    page.off("request", countQuery);
    await page.reload();
    await page.getByTestId("total").waitFor();
    assert.equal(
      await page.locator("html").getAttribute("data-theme"),
      "light",
    );
    assert.equal(
      await page.evaluate(() => localStorage.getItem("tramflow.theme.v1")),
      "light",
    );
    await page.locator(".tram-map__state").waitFor({ state: "hidden" });
    // Fullscreen is the same mounted map, with keyboard dismissal and restored focus.
    await mapViewport.evaluate((el) => (el.qaIdentity = "expanded-persistent"));
    await page
      .getByRole("button", { name: "Увеличить сайт", exact: true })
      .click();
    await page.getByRole("dialog", { name: "Увеличенная схема" }).waitFor();
    await page
      .getByRole("button", { name: "Закрыть увеличенную схему" })
      .press("Escape");
    assert.equal(
      await mapViewport.evaluate((el) => el.qaIdentity),
      "expanded-persistent",
    );
    // Every acceptance viewport, both themes, no page-level horizontal overflow.
    for (const theme of ["dark", "light"]) {
      await page.setViewportSize({ width: 1280, height: 800 });
      await page
        .getByRole("button", {
          name:
            theme === "dark" ? "Включить тёмную тему" : "Включить светлую тему",
          exact: true,
        })
        .click();
      for (const [width, height] of [
        [360, 800],
        [390, 844],
        [844, 390],
        [768, 1024],
        [1024, 768],
        [1280, 800],
        [1366, 768],
        [1440, 900],
      ]) {
        await page.setViewportSize({ width, height });
        await page.screenshot({
          path: output + `/evening-${theme}-${width}.png`,
          fullPage: true,
        });
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          true,
          `overflow ${theme} ${width}`,
        );
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.getByLabel("Точка временного ряда").isVisible(), true);
    await page.getByRole("button", { name: "Таблица", exact: true }).click();
    assert.equal(await page.locator(".forecast-card tbody tr").count(), 24);
    await setHorizon("week");
    await page.waitForFunction(
      () => document.querySelectorAll(".forecast-card tbody tr").length === 7,
    );
    // Separate fresh context: blocked storage still permits a working theme switch.
    const restricted = await browser.newContext({
      viewport: { width: 1280, height: 800 },
    });
    await restricted.addInitScript(() =>
      Object.defineProperty(window, "localStorage", {
        get() {
          throw new DOMException("blocked", "SecurityError");
        },
      }),
    );
    const restrictedPage = await restricted.newPage();
    await restrictedPage.goto(baseURL);
    assert.equal(
      await restrictedPage.locator("html").getAttribute("data-theme"),
      "dark",
    );
    await restrictedPage
      .getByRole("button", { name: "Включить светлую тему", exact: true })
      .click();
    assert.equal(
      await restrictedPage.locator("html").getAttribute("data-theme"),
      "light",
    );
    await restricted.close();
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("button", { name: "График", exact: true }).click();
    await setHorizon("day");
    await page.getByTestId("total").waitFor();
    // A theme change during an in-flight export must not cancel or change it.
    await page.route("**/handoff/export", async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({ response });
    });
    const exported = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Скачать CSV", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Включить тёмную тему", exact: true })
      .click();
    assert.ok((await exported).suggestedFilename().endsWith(".csv"));
    await page.unroute("**/handoff/export");
    // Existing selection survives a drag returning to its origin and a two-finger pinch.
    await page.getByLabel("Маршрут", { exact: true }).selectOption("11");
    await page.getByTestId("total").waitFor();
    const chosen = await mapSvg
      .locator("[data-selected-lane]")
      .evaluateAll((lines) =>
        lines.map((line) => [
          line.dataset.selectedLane,
          line.getAttribute("d"),
        ]),
      );
    const box = await mapViewport.boundingBox(),
      cx = box.x + box.width / 2,
      cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 50, cy + 30, { steps: 5 });
    await page.mouse.move(cx, cy, { steps: 5 });
    await page.mouse.up();
    assert.deepEqual(
      await mapSvg
        .locator("[data-selected-lane]")
        .evaluateAll((lines) =>
          lines.map((line) => [
            line.dataset.selectedLane,
            line.getAttribute("d"),
          ]),
        ),
      chosen,
    );
    const cdp = await context.newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [
        { id: 1, x: cx - 40, y: cy },
        { id: 2, x: cx + 40, y: cy },
      ],
    });
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { id: 1, x: cx - 80, y: cy },
        { id: 2, x: cx + 80, y: cy },
      ],
    });
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    assert.deepEqual(
      await mapSvg
        .locator("[data-selected-lane]")
        .evaluateAll((lines) =>
          lines.map((line) => [
            line.dataset.selectedLane,
            line.getAttribute("d"),
          ]),
        ),
      chosen,
    );
    await cdp.detach();
    // Map failure is local: forecast and CSV do not disappear.
    const broken = await context.newPage();
    await broken.route("**/map-local/schematic.svg", (r) => r.abort());
    await broken.goto(baseURL);
    await broken.locator(".tram-map__state[role=alert]").waitFor();
    await broken.getByTestId("total").waitFor();
    assert.equal(
      await broken
        .getByRole("button", { name: "Скачать CSV", exact: true })
        .isEnabled(),
      true,
    );
    await broken.close();
    // Double text sizes while preserving layout/content; all actions remain reachable.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      const styles = await page.evaluate(
        () =>
          [
            ...document.querySelectorAll(
              "body,h1,h2,p,button,input,select,summary,dt,dd,strong,span",
            ),
          ]
            .map((el) => ({
              el,
              size: parseFloat(getComputedStyle(el).fontSize) * 2,
            }))
            .map(({ el, size }) => {
              const prev = el.style.fontSize;
              el.dataset.qaFont = prev;
              el.style.fontSize = size + "px";
              return true;
            }).length,
      );
      assert.ok(styles > 10);
      await page.screenshot({
        path: output + `/text-200-${width}.png`,
        fullPage: true,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
        `200% text overflow ${width}`,
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
      `PASS ${sourceKind} batch → API → UI → CSV; missing release and recovery, day/week/December/baseline, stale requests, MSK in non-MSK browser, 503/410/409, partial/no_data, keyboard, responsive, map remains mounted.`,
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
