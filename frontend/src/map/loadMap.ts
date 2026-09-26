export type Lane = {
  id: string;
  colorKey: string;
  color: string;
  points: [number, number][];
  routes?: string[];
  inferred?: boolean;
  referenceVerified?: boolean;
};
export type LabelLine = { t: string; dx: number; dy: number; w: number };
export type MapLabel = {
  id: string;
  text: string;
  x: number;
  y: number;
  angle: number;
  lines: LabelLine[];
  fs: number;
  bold: boolean;
  lanes: string[];
};
export type Shape = { d: string; f: string; o?: number; eo?: number };
export type IconGroup = {
  id: string;
  x: number;
  y: number;
  w: number;
  shapes: Shape[];
};
export type Stop = {
  id: string;
  routes: string[];
  lane: string;
  x: number;
  y: number;
  label: string | null;
};
export type Network = {
  source: string;
  sha256: string;
  viewBox: [number, number, number, number];
  lanes: Lane[];
  stops?: Stop[];
  labels?: MapLabel[];
  landmarks?: (IconGroup & { h: number })[];
  metro?: IconGroup[];
  legend?: Record<string, string>; // номер маршрута → цвет
};

export const MAP_BASE = `${import.meta.env.BASE_URL}map-local/`;

/**
 * Загружает локальную геометрию сети (network.json, готовится scripts/map/extract_lanes.py).
 * Бросает Error('MISSING'), если ресурсы не подготовлены.
 */
export async function loadNetwork(signal: AbortSignal): Promise<Network> {
  let response: Response;
  try {
    response = await fetch(`${MAP_BASE}network.json`, { signal });
  } catch {
    throw new Error("Не удалось загрузить ресурсы карты.");
  }
  if (
    !response.ok ||
    !(response.headers.get("content-type") ?? "").includes("json")
  )
    throw new Error("MISSING");
  const n = (await response.json()) as Network;
  if (
    !Array.isArray(n.viewBox) ||
    n.viewBox.length !== 4 ||
    !Array.isArray(n.lanes)
  ) {
    throw new Error(
      "Ресурсы карты имеют неожиданный формат. Подготовьте их заново: python scripts/map/extract_lanes.py",
    );
  }
  return n;
}

/** Читаемый цвет текста на плашке номера. */
export function inkFor(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#1c2230" : "#ffffff";
}

const num = (n: string) => (parseInt(n, 10) || 0) + (/^[^\d]/.test(n) ? -1 : 0);
export const byRouteNumber = (a: string, b: string) =>
  num(a) - num(b) || a.localeCompare(b);

export type LaneLabel = { key: string; x: number; y: number; text: string };

/** Позиции подписей номеров вдоль линии: одна или несколько, разнесены по индексу линии, чтобы в пучках не накладывались. */
export function laneLabels(lane: Lane, index: number): LaneLabel[] {
  if (!lane.routes?.length) return [];
  const seg: number[] = [0];
  for (let i = 1; i < lane.points.length; i++) {
    const [x0, y0] = lane.points[i - 1],
      [x1, y1] = lane.points[i];
    seg.push(seg[i - 1] + Math.hypot(x1 - x0, y1 - y0));
  }
  const total = seg[seg.length - 1];
  if (total < 40) return []; // короткие перемычки не подписываем
  const count = Math.max(1, Math.round(total / 260));
  const out: LaneLabel[] = [];
  for (let k = 0; k < count; k++) {
    const t = (k + 0.5) / count + (((index % 5) - 2) * 0.03) / count;
    const d = Math.min(total, Math.max(0, t * total));
    let i = 1;
    while (i < seg.length - 1 && seg[i] < d) i++;
    const f = (d - seg[i - 1]) / Math.max(1e-6, seg[i] - seg[i - 1]);
    out.push({
      key: `${lane.id}:${k}`,
      text: lane.routes.join(" · "),
      x:
        lane.points[i - 1][0] + f * (lane.points[i][0] - lane.points[i - 1][0]),
      y:
        lane.points[i - 1][1] + f * (lane.points[i][1] - lane.points[i - 1][1]),
    });
  }
  return out;
}
