import { readFileSync } from 'node:fs';

try {
  const map = JSON.parse(readFileSync(new URL('../public/map-local/network.json', import.meta.url), 'utf8'));
  if (!Array.isArray(map.viewBox) || map.viewBox.length !== 4 ||
      !map.viewBox.every(Number.isFinite) || map.viewBox[2] <= 0 || map.viewBox[3] <= 0) {
    throw new Error('Некорректный viewBox карты');
  }
  for (const key of ['lanes', 'stops', 'labels', 'landmarks', 'metro']) {
    if (!Array.isArray(map[key]) || map[key].length === 0) {
      throw new Error(`Карта неполная: отсутствует ${key}. Нужен итоговый файл после всех шагов подготовки.`);
    }
  }
  if (!map.legend || Object.keys(map.legend).length === 0) throw new Error('Отсутствует легенда маршрутов');
  console.log('Карта присутствует: ' + ['lanes', 'stops', 'labels', 'landmarks', 'metro'].map(k => `${k}=${map[k].length}`).join(', '));
} catch (error) {
  console.error('Сборка остановлена: ' + error.message);
  console.error('Добавьте готовый frontend/public/map-local/network.json в тот же PR, что и изменения карты. Получателям достаточно git pull; PDF и OCR не нужны.');
  process.exitCode = 1;
}
