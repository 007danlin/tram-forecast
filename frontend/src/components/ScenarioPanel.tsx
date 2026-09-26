import { neutralCoefficients } from '../handoff';
import { format, useForecastData } from '../useForecast';
import { Button } from './ui';
import './ScenarioPanel.css';

const factors = [
  ['weather', 'Погода'], ['closures', 'Перекрытия'],
  ['changes', 'Изменения движения'], ['event', 'Мероприятия'],
] as const;

export function ScenarioPanel() {
  const f = useForecastData();
  if (!f.caps?.scenario_supported || !f.route || f.routeUnavailable || f.horizon === 'year') return null;
  // Older backends only support weather/event. Do not silently send unsupported fields.
  const supported = f.caps.scenario?.coefficients ?? ['weather', 'event'];
  return <details className="scenario-panel">
    <summary>Корректирующие коэффициенты{f.scenarioActive ? ' · сценарий' : ''}</summary>
    <p>Ручной сценарий для выбранного маршрута и периода. Категории соответствуют мониторингу; значения задаёте вы.</p>
    <p>1 — без изменений. Поправки перемножаются. При смене маршрута, даты или периода они сбрасываются.</p>
    <div className="scenario-panel__factors">{factors.filter(([key]) => supported.includes(key)).map(([key, label]) =>
      <label key={key}><span>{label}</span><output>{format(f.coefficients[key])}×</output>
        <input type="range" aria-label={`Коэффициент: ${label}`} min="0.5" max="1.5" step="0.05"
          value={f.coefficients[key]} onChange={e => f.changeCoefficients({...f.coefficients, [key]: Number(e.target.value)})}/>
      </label>)}</div>
    <p>Общий множитель: <strong>{format(Object.values(f.coefficients).reduce((a,b) => a*b, 1))}×</strong></p>
    {f.scenario && <p role="status">За период: база {format(f.scenario.base.total)} → сценарий {format(f.scenario.total)}. Разница: {format(f.scenario.delta_total)}.</p>}
    <Button onClick={() => f.changeCoefficients(neutralCoefficients)} disabled={!f.scenarioActive}>Сбросить поправки</Button>
    <p className="scenario-panel__note">Онлайн-снимки относятся к другому периоду, чем исторический прогноз. Поправки не вычисляются из них автоматически и не являются подтверждённым эффектом модели. Не учитывайте одно ограничение повторно в двух категориях.</p>
  </details>;
}
