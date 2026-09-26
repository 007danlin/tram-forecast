import { useState } from 'react';
import { neutralCoefficients } from '../handoff';
import { useForecastData } from '../useForecast';
import { Button } from './ui';
import './ScenarioPanel.css';
const factors = [['weather', 'Погода'], ['closures', 'Перекрытия'], ['changes', 'Изменения движения'], ['event', 'Мероприятия']] as const;
export function ScenarioPanel({onClose}: {onClose: () => void}) {
  const f = useForecastData();
  const [draft, setDraft] = useState({...f.coefficients});
  const supported = f.caps?.scenario?.coefficients ?? ['weather', 'event'];
  if (!f.caps?.scenario_supported || !f.route || f.routeUnavailable) return <p>Для выбранного маршрута поправки недоступны.</p>;
  return <form className="scenario-panel" onSubmit={e => {e.preventDefault(); f.changeCoefficients(draft); onClose();}}>
    <p className="panel-intro">Измените спрос вручную. Это ваши допущения, а не влияние онлайн-источников.</p>
    <div className="scenario-panel__factors">{factors.filter(([key]) => supported.includes(key)).map(([key, label]) => {
      const percent = Math.round((draft[key] - 1) * 100);
      return <label key={key}><span>{label}</span><output>{percent > 0 ? '+' : ''}{percent}%</output>
        <input type="range" aria-label={`Поправка: ${label}`} aria-valuetext={`${percent}%`} min="-50" max="50" step="5" value={percent} onChange={e => setDraft({...draft, [key]: Math.round((1 + Number(e.target.value) / 100) * 100) / 100})}/>
        <span className="scenario-panel__limits"><span>−50%</span><span>+50%</span></span>
      </label>;
    })}</div>
    <p className="panel-note">0% — без изменений. Поправки перемножаются; CSV сохранит исходный прогноз и результат.</p>
    <div className="panel-actions"><Button onClick={() => setDraft({...neutralCoefficients})}>Сбросить поправки</Button><Button variant="primary" type="submit">Применить</Button></div>
  </form>;
}
