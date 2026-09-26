type Point = { x: number; y: number };

/** Smooth each observed run without moving samples or overshooting their range. */
export function smoothChartPath(points: readonly (Point | null)[]): string {
  const paths: string[] = [];
  let run: Point[] = [];
  const flush = () => {
    if (!run.length) return;
    const slopes = run.slice(1).map((p, i) =>
      (p.y - run[i].y) / (p.x - run[i].x),
    );
    const tangents = run.map((_, i) => {
      if (i === 0) return slopes[0] ?? 0;
      if (i === run.length - 1) return slopes[i - 1];
      const before = slopes[i - 1], after = slopes[i];
      // Flat sections and peaks have horizontal tangents. The harmonic mean
      // keeps the equally spaced samples' curve within each adjacent range.
      return before * after > 0 ? (2 * before * after) / (before + after) : 0;
    });
    let path = `M${run[0].x},${run[0].y}`;
    for (let i = 1; i < run.length; i++) {
      const a = run[i - 1], b = run[i], dx = (b.x - a.x) / 3;
      path += ` C${a.x + dx},${a.y + dx * tangents[i - 1]} ${b.x - dx},${b.y - dx * tangents[i]} ${b.x},${b.y}`;
    }
    paths.push(path);
    run = [];
  };
  for (const point of points) {
    if (point === null) flush();
    else run.push(point);
  }
  flush();
  return paths.join(" ");
}
