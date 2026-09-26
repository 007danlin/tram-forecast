import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

try {
  const map = JSON.parse(
    readFileSync(
      new URL("../public/map-local/network.json", import.meta.url),
      "utf8",
    ),
  );
  if (
    !Array.isArray(map.viewBox) ||
    map.viewBox.length !== 4 ||
    !map.viewBox.every(Number.isFinite) ||
    map.viewBox[2] <= 0 ||
    map.viewBox[3] <= 0
  ) {
    throw new Error("Некорректный viewBox карты");
  }
  for (const key of ["lanes", "stops", "labels", "landmarks", "metro"]) {
    if (!Array.isArray(map[key]) || map[key].length === 0) {
      throw new Error(
        `Карта неполная: отсутствует ${key}. Нужен итоговый файл после всех шагов подготовки.`,
      );
    }
  }
  if (!map.legend || Object.keys(map.legend).length === 0)
    throw new Error("Отсутствует легенда маршрутов");
  const vector = readFileSync(
    new URL("../public/map-local/schematic.svg", import.meta.url),
  );
  const reference = JSON.parse(
    readFileSync(
      new URL("../public/map-local/schematic.meta.json", import.meta.url),
      "utf8",
    ),
  );
  if (
    reference.source_sha256 !== map.sha256 ||
    createHash("sha256").update(vector).digest("hex") !== reference.sha256
  )
    throw new Error(
      "Векторная схема не соответствует проверенному источнику/контрольной сумме",
    );
  if (/<(?:image|script)\b|(?:href|src)=[\"\']https?:/i.test(vector.toString()))
    throw new Error(
      "Векторная схема не должна содержать растр, скрипты или внешние ресурсы",
    );
  const favicon = readFileSync(
    new URL("../public/favicon.svg", import.meta.url),
  );
  if (
    createHash("sha256").update(favicon).digest("hex") !==
    reference.favicon_sha256
  )
    throw new Error("Иконка вкладки не соответствует извлечённому оригиналу");
  if (
    !reference.excluded_poster_paths?.includes(3058) ||
    !reference.excluded_poster_paths?.includes(14609)
  )
    throw new Error("Рамка/легенда печатной схемы не исключены");
  const svg = vector.toString();
  if (reference.station_label_count !== map.labels.length)
    throw new Error("Несовпадение числа подписей SVG");
  for (const label of map.labels) {
    if (
      !label.originalGlyphs?.length ||
      !svg.includes(`id="station-label-${label.id}"`)
    )
      throw new Error(`Нет оригинальной подписи ${label.id}`);
    for (const id of label.originalGlyphs)
      if (!svg.includes(`id="glyph-${id}"`))
        throw new Error(`Нет контура подписи ${id}`);
  }
  if (!map.stationSymbols?.length ||
      reference.station_symbol_count !== map.stationSymbols.length)
    throw new Error("Отсутствуют проверенные значки станций");
  const laneIds = new Set(map.lanes.map((lane) => lane.id));
  const labelIds = new Set(map.labels.map((label) => label.id));
  const symbolIds = new Set();
  for (const group of map.stationSymbols) {
    if (symbolIds.has(group.id) || !group.lanes.length ||
        group.lanes.some((id) => !laneIds.has(id)) ||
        group.labels.some((id) => !labelIds.has(id)) ||
        group.bounds.length !== 4 || !group.bounds.every(Number.isFinite) ||
        group.bounds[2] <= group.bounds[0] || group.bounds[3] <= group.bounds[1] ||
        !group.originalPaths.length || !svg.includes(`id="station-symbol-${group.id}"`))
      throw new Error(`Неполные значки станции ${group.id}`);
    symbolIds.add(group.id);
    for (const id of group.originalPaths)
      if (!svg.includes(`id="glyph-${id}"`))
        throw new Error(`Нет исходного контура значка ${id}`);
  }
  console.log(
    "Карта присутствует: " +
      ["lanes", "stops", "labels", "landmarks", "metro"]
        .map((k) => `${k}=${map[k].length}`)
        .join(", "),
  );
} catch (error) {
  console.error("Сборка остановлена: " + error.message);
  console.error(
    "Добавьте готовый frontend/public/map-local/network.json в тот же PR, что и изменения карты. Получателям достаточно git pull; PDF и OCR не нужны.",
  );
  process.exitCode = 1;
}
