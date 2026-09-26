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
        .filter((l) => l.lanes.some((id) => ids.has(id)))
        .map((l) => l.id),
    );
  }
for (const number of ["", "not-on-map"]) {
  const features = routeFeatures(network, number);
  assert.equal(features.selection, undefined);
  assert.deepEqual(features.stops, []);
  assert.deepEqual(features.labels, []);
}
console.log(
  "PASS every route selects its stops and labels; clear/unknown routes select nothing.",
);
