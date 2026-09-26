export function dateLabel(value: string, short = false) {
  if (!value) return "Период не выбран";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: short ? "short" : "long",
    year: "numeric",
    timeZone: "Europe/Moscow",
  }).format(new Date(value.length === 10 ? value + "T00:00:00+03:00" : value));
}
export function intervalLabel(start: string, end: string, daily: boolean) {
  return daily
    ? dateLabel(start, true)
    : `${start.slice(11, 16)}–${end.slice(11, 16) === "00:00" ? "24:00" : end.slice(11, 16)}`;
}
