import { useEffect, useMemo, useRef, useState } from "react";
import { addDays, getResult, OVERVIEW } from "./handoff";
import type { Capabilities, Filters, Row } from "./handoff";

export type WeeklyComparison = { currentValue: number; averageValue: number; history: number[] };

const weekday = (day: string) => new Date(`${day}T00:00:00Z`).getUTCDay();

// Same hour-of-day, same weekday, across every prior week in the loaded package.
export function useWeeklyComparison(route: string, caps: Capabilities | null, point: Row | null): WeeklyComparison | null {
  const [rows, setRows] = useState<Row[] | null>(null);
  const cache = useRef<Map<string, Row[]>>(new Map());

  useEffect(() => {
    if (!caps || !route || route === OVERVIEW || !caps.resolutions.includes("hour")) { setRows(null); return; }
    const key = `${route}:${caps.forecast_run_id}`;
    const cached = cache.current.get(key);
    if (cached) { setRows(cached); return; }
    let active = true;
    const controller = new AbortController();
    (async () => {
      const endDay = caps.end.slice(0, 10);
      const collected: Row[] = [];
      let cursor = caps.start.slice(0, 10);
      while (cursor < endDay) {
        const chunkEnd = addDays(cursor, 30) > endDay ? endDay : addDays(cursor, 30);
        const filters: Filters = {
          route_ids: [route], resolution: "hour", forecast_run_id: caps.forecast_run_id,
          start: `${cursor}T00:00:00+03:00`, end: `${chunkEnd}T00:00:00+03:00`,
        };
        collected.push(...(await getResult(filters, controller.signal)).rows);
        cursor = chunkEnd;
      }
      if (active) { cache.current.set(key, collected); setRows(collected); }
    })().catch(() => { if (active) setRows(null); });
    return () => { active = false; controller.abort(); };
  }, [caps, route]);

  return useMemo(() => {
    if (!rows || !point || point.value === null) return null;
    const hour = point.start.slice(11, 13), day = weekday(point.start.slice(0, 10));
    const matches = rows
      .filter(r => r.value !== null && r.start.slice(11, 13) === hour && weekday(r.start.slice(0, 10)) === day)
      .sort((a, b) => a.start.localeCompare(b.start));
    const others = matches.filter(r => r.start !== point.start);
    if (!others.length) return null;
    const averageValue = others.reduce((sum, r) => sum + (r.value as number), 0) / others.length;
    return { currentValue: point.value, averageValue, history: matches.slice(-7).map(r => r.value as number) };
  }, [rows, point]);
}
