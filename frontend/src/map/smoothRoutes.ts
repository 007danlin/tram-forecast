import type { Lane } from "./loadMap";
type Point = [number, number];
export type Curve = [Point, Point, Point, Point];
export type SmoothLane = {
  id: string;
  d: string;
  points: Point[];
  curves: Curve[];
};
const length = (a: Point, b: Point) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const unit = (a: Point, b: Point): Point => {
  const d = length(a, b) || 1;
  return [(b[0] - a[0]) / d, (b[1] - a[1]) / d];
};
const key = (p: Point) => p.map((v) => v.toFixed(3)).join(",");
const at = (curve: Curve, t: number): Point => {
  const [a, b, c, d] = curve,
    u = 1 - t;
  return [0, 1].map(
    (i) =>
      u * u * u * a[i] +
      3 * u * u * t * b[i] +
      3 * u * t * t * c[i] +
      t * t * t * d[i],
  ) as Point;
};

/** Interpolate reviewed centre points, with short handles to avoid cutting corners.
 * Endpoint neighbours belong only to this route, so split paths keep a shared tangent.
 * The sampled version is also used for hit testing the visible curve.
 */
export function smoothRoute(lanes: Lane[]): SmoothLane[] {
  const clean = lanes.map((lane) => ({
    ...lane,
    points: lane.points.filter(
      (p, i, all) => !i || length(p, all[i - 1]) > 0.0001,
    ),
  }));
  const ends = new Map<string, { id: string; other: Point }[]>();
  for (const lane of clean)
    if (lane.points.length > 1) {
      const p = lane.points;
      for (const [end, other] of [
        [p[0], p[1]],
        [p[p.length - 1], p[p.length - 2]],
      ]) {
        const k = key(end),
          list = ends.get(k) ?? [];
        list.push({ id: lane.id, other });
        ends.set(k, list);
      }
    }
  return clean.map((lane) => {
    const p = lane.points;
    const neighbour = (end: Point, inside: Point) => {
      const direction = unit(inside, end);
      return ends
        .get(key(end))
        ?.filter((e) => e.id !== lane.id)
        .sort((a, b) => {
          const u = unit(end, a.other),
            v = unit(end, b.other);
          return (v[0] - u[0]) * direction[0] + (v[1] - u[1]) * direction[1];
        })[0]?.other;
    };
    const closed = p.length > 2 && key(p[0]) === key(p[p.length - 1]);
    const handles = p.map((point, i): Point => {
      const prev =
        p[i - 1] ?? (closed ? p[p.length - 2] : neighbour(point, p[1]));
      const next = p[i + 1] ?? (closed ? p[1] : neighbour(point, p[i - 1]));
      const a = prev ? unit(prev, point) : unit(point, next!);
      const b = next ? unit(point, next) : a;
      const norm = Math.hypot(a[0] + b[0], a[1] + b[1]);
      if (norm < 0.0001) return [0, 0];
      const size = Math.min(
        4,
        prev ? length(prev, point) / 3 : Infinity,
        next ? length(point, next) / 3 : Infinity,
      );
      return [((a[0] + b[0]) / norm) * size, ((a[1] + b[1]) / norm) * size];
    });
    const curves: Curve[] = p
      .slice(1)
      .map((end, i) => [
        p[i],
        [p[i][0] + handles[i][0], p[i][1] + handles[i][1]],
        [end[0] - handles[i + 1][0], end[1] - handles[i + 1][1]],
        end,
      ]);
    const format = (v: Point) => v.map((n) => Number(n.toFixed(4))).join(" ");
    return {
      id: lane.id,
      curves,
      d:
        `M${format(p[0])}` +
        curves.map((c) => `C${c.slice(1).map(format).join(" ")}`).join(""),
      points: [
        p[0],
        ...curves.flatMap((c) =>
          Array.from({ length: 8 }, (_, i) => at(c, (i + 1) / 8)),
        ),
      ],
    };
  });
}
