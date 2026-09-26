import { useEffect, useRef } from 'react';
import './SettingsPanel.css';

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);
  return (
    <div className="settings-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="settings-panel" role="dialog" aria-modal="true" aria-label="Настройки"
        onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
        <div className="settings-panel__head">
          <h2>Настройки</h2>
          <button ref={closeRef} type="button" className="settings-panel__close" onClick={onClose} aria-label="Закрыть настройки">✕</button>
        </div>

        <section>
          <h3>Режим данных</h3>
          <p>Приложение показывает готовый исторический ML-пакет через handoff API. Доступный период и маршруты задаёт пакет; без него прогноз недоступен. Схема самостоятельна и не связана с селектором прогноза.</p>
        </section>

        <section>
          <h3>Реализованные настройки</h3>
          <p>Пока нет — в текущей версии нечего настраивать.</p>
        </section>

        <section>
          <h3>Пока недоступно</h3>
          <ul>
            <li>Остановочный прогноз и направления — нужны подтверждённые данные.</li>
            <li>Годовой экран — нужны согласованные качественные сценарии.</li>
            <li>Диспетчерские сценарии — нужны согласованные коэффициенты и расчёт на backend.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
