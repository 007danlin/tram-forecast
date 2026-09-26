import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { groupRouteLanes, routeFeatures } from "../src/map/routeSelection.ts";
const network = JSON.parse(
  readFileSync(new URL("../public/map-local/network.json", import.meta.url)),
);
const groups = groupRouteLanes(network.lanes);
const near = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.001;
const ends = (l) => [l.points[0], l.points.at(-1)];
for (const group of groups) {
  const pending = new Set(group.lanes.map((l) => l.id));
  const reached = [group.lanes[0]];
  pending.delete(reached[0].id);
  for (let i = 0; i < reached.length; i++)
    for (const next of group.lanes) {
      if (
        pending.has(next.id) &&
        ends(next).some((a) => ends(reached[i]).some((b) => near(a, b)))
      ) {
        pending.delete(next.id);
        reached.push(next);
      }
    }
  assert.equal(
    pending.size,
    0,
    `Route ${group.routes}: disconnected ${[...pending]}`,
  );
  for (const lane of group.lanes) {
    assert.ok(lane.points.length >= 2);
    assert.deepEqual(
      [...lane.routes].sort(),
      group.routes,
      `Route ${group.routes}: unrelated member ${lane.id}`,
    );
    for (const p of lane.points)
      assert.ok(p.length === 2 && p.every(Number.isFinite));
  }
}
const route = (number) => groups.find((g) => g.routes.includes(number));
assert.deepEqual(
  route("36").lanes.map((l) => l.id),
  ["red-1", "red-6", "red-17", "red-18", "red-1336"],
);
assert.deepEqual(
  route("Т2").lanes.map((l) => l.id),
  ["red-2", "red-10", "red-15", "red-13t2"],
);
assert.equal(route("11").lanes.length, 2);
assert.equal(route("50").lanes.length, 3);
assert.notEqual(route("1").id, route("11").id); // Same colour is not the same route.
assert.equal(new Set(groups.flatMap((g) => g.lanes.map((l) => l.id))).size, 45);
assert.deepEqual(
  [...new Set(groups.flatMap((g) => g.routes))].sort(),
  Object.keys(network.legend).sort(),
);
// The terminal loop must close around the original white diamond, not cross it.
const fifty = route("50").lanes;
assert.ok(
  near(
    fifty.find((l) => l.id === "teal-2").points.at(-1),
    fifty.find((l) => l.id === "teal-7").points.at(-1),
  ),
);
assert.ok(fifty.find((l) => l.id === "teal-2").points.some((p) => p[0] > 455));
assert.ok(fifty.find((l) => l.id === "teal-7").points.some((p) => p[0] < 445));
assert.ok(fifty.find((l) => l.id === "teal-3").points.at(-1)[1] < 582);
console.log(
  `PASS ${groups.length} map choices / ${Object.keys(network.legend).length} route numbers / ${network.lanes.length} stable lanes: connected selections, isolated same-colour routes, complete terminal loop.`,
);

for (const group of groups)
  for (const number of group.routes) {
    const features = routeFeatures(network, number),
      ids = new Set(group.lanes.map((l) => l.id));
    assert.deepEqual(features.selection, group);
    assert.ok(features.stops.length > 0, `No stops for ${number}`);
    assert.ok(features.labels.length > 0, `No labels for ${number}`);
    assert.deepEqual(
      features.stops.map((s) => s.id),
      network.stops.filter((s) => ids.has(s.lane)).map((s) => s.id),
    );
    assert.deepEqual(
      features.labels.map((l) => l.id),
      network.labels
        .filter((l) => l.lanes.some((id) => ids.has(id)) ||
          features.stationSymbols.some((g) => g.labels.includes(l.id)))
        .map((l) => l.id),
    );
    assert.deepEqual(
      features.stationSymbols.map((g) => g.id),
      network.stationSymbols.filter((g) => g.lanes.some((id) => ids.has(id)))
        .map((g) => g.id),
    );
    for (const label of features.labels)
      for (const group of network.stationSymbols.filter((g) => g.labels.includes(label.id)))
        assert.ok(features.stationSymbols.includes(group), `Missing station symbols: ${label.text}`);
  }
for (const number of ["", "not-on-map"]) {
  const features = routeFeatures(network, number);
  assert.equal(features.selection, undefined);
  assert.deepEqual(features.stops, []);
  assert.deepEqual(features.labels, []);
  assert.deepEqual(features.stationSymbols, []);
}
const symbols = (number) => routeFeatures(network, number).stationSymbols.map((g) => g.id);
for (const route of ["1", "16"]) {
  assert.ok(symbols(route).includes("transfer-275")); // Southern Chertanovskaya
  assert.ok(!symbols(route).includes("transfer-273")); // T2 terminal is separate
}
assert.ok(symbols("Т2").includes("transfer-273"));
assert.ok(!symbols("Т2").includes("transfer-275"));
assert.ok(symbols("50").includes("transfer-108")); // Terminal Novoslobodskaya
assert.ok(symbols("13").includes("transfer-109")); // MCD at Three Stations
assert.ok(!symbols("13").includes("transfer-023")); // Adjacent terminus belongs to 4/7
// Printed terminal plates restore station associations missed by OCR.
for (const [number, labelId, groupId] of [
  ["10", "l068", "transfer-038"],
  ["28", "l067", "transfer-039"],
  ["12", "l340", "transfer-199"],
]) {
  const features = routeFeatures(network, number);
  assert.ok(features.labels.some((l) => l.id === labelId), `Faded terminal name ${number}`);
  assert.ok(features.stationSymbols.some((g) => g.id === groupId), `Missing terminal plates ${number}`);
}
for (const number of ["4", "7"]) {
  const rokossovskogo = routeFeatures(network, number).stationSymbols
    .find((g) => g.id === "transfer-023");
  // PDF paths for both 4 and 7; selection must not filter the other number out.
  assert.ok([14148, 14150].every((id) => rokossovskogo.originalPaths.includes(id)));
}
console.log(
  "PASS every route selects its stops, labels and station symbols; separate same-name stations, clear/unknown selections.",
);

// Smooth paths retain all reviewed knots/endpoints and stay in the same corridor.
const { smoothRoute } = await import("../src/map/smoothRoutes.ts");
for (const group of groups) {
  const smooth = smoothRoute(group.lanes);
  assert.deepEqual(
    smooth.map((l) => l.id),
    group.lanes.map((l) => l.id),
  );
  const joints = new Map();
  for (const line of smooth) {
    const first = line.curves[0],
      last = line.curves.at(-1);
    for (const [point, control] of [
      [first[0], first[1]],
      [last[3], last[2]],
    ]) {
      const key = point.map((n) => n.toFixed(3)).join(",");
      const directions = joints.get(key) ?? [];
      directions.push([control[0] - point[0], control[1] - point[1]]);
      joints.set(key, directions);
    }
  }
  for (const directions of joints.values())
    if (directions.length === 2)
      for (const axis of [0, 1])
        assert.ok(
          Math.abs(directions[0][axis] + directions[1][axis]) < 1e-8,
          `Sharp fragment join in ${group.routes}`,
        );
  for (const line of smooth) {
    const original = group.lanes.find((l) => l.id === line.id);
    assert.deepEqual(line.points[0], original.points[0]);
    assert.deepEqual(line.points.at(-1), original.points.at(-1));
    assert.ok(line.d.includes("C") && !/NaN|Infinity/.test(line.d));
    for (let i = 1; i < line.curves.length; i++) {
      const a = line.curves[i - 1],
        b = line.curves[i];
      assert.deepEqual(a[3], b[0]);
      for (const axis of [0, 1])
        assert.ok(
          Math.abs(a[3][axis] - a[2][axis] - (b[1][axis] - b[0][axis])) < 1e-8,
          `Tangent discontinuity ${line.id}`,
        );
    }
    // Handles cannot drag the path out of the local neighbourhood or form wide loops.
    for (const c of line.curves)
      for (const [a, b] of [
        [c[0], c[1]],
        [c[2], c[3]],
      ])
        assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1]) <= 4.000001);
  }
}
console.log(
  "PASS 45 smooth paths: exact endpoints, continuous tangents, bounded controls.",
);
