import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { TramMap } from './components/TramMap';

type Forecast = { is_mock: true; unit: 'passengers'; points: { timestamp: string; value: number }[] };

async function getJson(path: string, signal: AbortSignal) {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function validateForecast(data: Forecast): Forecast {
  if (data.is_mock !== true || data.unit !== 'passengers' || !Array.isArray(data.points) || !data.points.length ||
    !data.points.every(p => Number.isInteger(p.value) && p.value >= 0 && typeof p.timestamp === 'string' &&
      /(?:Z|[+-]\d{2}:\d{2})$/.test(p.timestamp) && Number.isFinite(Date.parse(p.timestamp)))) {
    throw new Error('Некорректный ответ API');
  }
  return data;
}

function App() {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [connection, setConnection] = useState('Проверяем соединение…');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setLoading(true); setError(''); setForecast(null); setConnection('Проверяем соединение…');
    async function load() {
      try {
        const health = await getJson('/api/v1/health', controller.signal);
        if (health.status !== 'ok') throw new Error('Неожиданный статус сервиса');
        if (active) setConnection('Backend подключён');
        const data = validateForecast(await getJson('/api/v1/forecast', controller.signal));
        if (active) setForecast(data);
      } catch {
        if (active) {
          setConnection('Не удалось получить данные');
          setError('Проверьте, что backend запущен и доступен, затем повторите запрос.');
        }
      } finally {
        window.clearTimeout(timeout);
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [attempt]);
  const points = forecast?.points ?? [];
  const max = Math.max(1, ...points.map(p => p.value));
  const line = points.map((p, i) => `${40 + i * 520 / Math.max(1, points.length - 1)},${190 - p.value / max * 160}`).join(' ');
  return <><TramMap /><main>
    <p className="eyebrow">TRAMFLOW / ПРОВЕРКА ИНТЕГРАЦИИ</p>
    <h1>Пассажиропоток трамваев</h1>
    <p className="notice">Тестовые данные — не реальный прогноз</p>
    <p role="status">{connection}</p>
    {loading && <p>Загружаем тестовый ряд…</p>}
    {error && <p role="alert">{error}</p>}
    {forecast && <section aria-label="Тестовый временной ряд">
      <h2>Синтетический пример · пассажиры</h2>
      <svg viewBox="0 0 600 230" role="img" aria-label="График тестового пассажиропотока. Точные значения приведены в таблице ниже.">
        <line x1="40" y1="190" x2="560" y2="190" stroke="#adb8c8" />
        <text x="12" y="195">0</text><text x="8" y="30">{max}</text>
        <polyline points={line} fill="none" stroke="#2563eb" strokeWidth="3" />
        {points.map((p, i) => <circle key={`${p.timestamp}-${i}`} cx={40 + i * 520 / Math.max(1, points.length - 1)} cy={190 - p.value / max * 160} r="4" fill="#2563eb" />)}
        <text x="40" y="220">{points[0].timestamp.slice(11, 16)}</text>
        <text x="560" y="220" textAnchor="end">{points[points.length - 1].timestamp.slice(11, 16)}</text>
      </svg>
      <table><caption>Время с часовым смещением, без перевода в часовой пояс браузера</caption><thead><tr><th>Время (ISO 8601)</th><th>Пассажиры</th></tr></thead>
        <tbody>{points.map((p, i) => <tr key={i}><td><time dateTime={p.timestamp}>{p.timestamp}</time></td><td>{p.value}</td></tr>)}</tbody>
      </table>
    </section>}
    <button disabled={loading} onClick={() => setAttempt(a => a + 1)}>Повторить запрос</button>
  </main></>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
