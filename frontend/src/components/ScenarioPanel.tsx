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
    <div className="scenario-panel__factors">{factors.filter(([key]) => supported.includes(key)).map(([key, label]) =>
      <label key={key}><span>{label}</span><output>{format(f.coefficients[key])}×</output>
        <input type="range" aria-label={`Коэффициент: ${label}`} min="0.5" max="1.5" step="0.05"
          value={f.coefficients[key]} onChange={e => f.changeCoefficients({...f.coefficients, [key]: Number(e.target.value)})}/>
      </label>)}</div>
    <Button onClick={() => f.changeCoefficients(neutralCoefficients)} disabled={!f.scenarioActive}>Сбросить поправки</Button>
  </details>;
}
