import type { Lane } from "./loadMap";

export type RouteSelection = {
  id: string;
  routes: string[];
  lanes: Lane[];
  unverified: boolean;
};

/** A PDF may split one route at crossings; colour is never route identity. */
export function groupRouteLanes(lanes: Lane[]): RouteSelection[] {
  const groups = new Map<string, RouteSelection>();
  for (const lane of lanes) {
    const routes = [...(lane.routes ?? [])].sort();
    // Keep the explicitly shared 6/6к corridor together; do not invent its split.
    const key = routes.length ? JSON.stringify(routes) : lane.id;
    let group = groups.get(key);
    if (!group) {
      group = { id: lane.id, routes, lanes: [], unverified: false };
      groups.set(key, group);
    }
    group.lanes.push(lane);
    group.unverified ||= !!lane.inferred && !lane.referenceVerified;
  }
  return [...groups.values()].sort((a, b) =>
    (a.routes[0] ?? a.id).localeCompare(b.routes[0] ?? b.id, "ru", {
      numeric: true,
    }),
  );
}

export const routeSelectionName = (selection: RouteSelection) =>
  `${selection.routes.length ? selection.routes.map((n) => "№ " + n).join(", ") : "Линия"}${selection.unverified ? " · номер уточняется" : ""}`;
