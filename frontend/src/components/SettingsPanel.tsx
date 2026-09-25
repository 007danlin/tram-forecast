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
          <p>Приложение работает на синтетическом примере backend (<code>is_mock: true</code>). Показанные значения не отражают реальный пассажиропоток.</p>
        </section>

        <section>
          <h3>Реализованные настройки</h3>
          <p>Пока нет — в текущей версии нечего настраивать.</p>
        </section>

        <section>
          <h3>Пока недоступно</h3>
          <ul>
            <li>Выбор маршрута, остановки и направления — нужен согласованный справочник API.</li>
            <li>Горизонты «1 месяц» и «1 год» — нужны данные соответствующего периода.</li>
            <li>Часовой шаг таймлайна — нужны подтверждённые часовые данные.</li>
            <li>Экспорт CSV — нужен backend-экспорт.</li>
            <li>Диспетчерские сценарии — нужны согласованные коэффициенты и расчёт на backend.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
