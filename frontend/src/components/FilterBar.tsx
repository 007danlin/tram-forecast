import { forwardRef, useEffect, useRef, useState } from 'react';
import './FilterBar.css';

const API_HINT = 'Требуется подключение данных и фильтров API';

export const FilterBar = forwardRef<HTMLDivElement, { dataDateLabel: string; overlay?: boolean }>(
  function FilterBar({ dataDateLabel, overlay }, ref) {
  const [moreOpen, setMoreOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!moreOpen) return;
    const onDocPointer = (e: PointerEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) setMoreOpen(false);
    };
    const onDocKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMoreOpen(false); };
    document.addEventListener('pointerdown', onDocPointer);
    document.addEventListener('keydown', onDocKey);
    return () => { document.removeEventListener('pointerdown', onDocPointer); document.removeEventListener('keydown', onDocKey); };
  }, [moreOpen]);

  return (
    <div ref={ref} className={`filter-bar${overlay ? ' filter-bar--overlay' : ''}`} role="search" aria-label="Фильтры прогноза">
      <div className="filter-bar__row">
        <div className="filter-bar__field">
          <label htmlFor="filter-route"><img className="filter-bar__field-icon" src="/tram-icon.png" alt="" aria-hidden="true" /> Маршрут</label>
          <select id="filter-route" className="filter-bar__control" disabled title={API_HINT}>
            <option>Синтетический пример</option>
          </select>
        </div>
        <div className="filter-bar__field">
          <label htmlFor="filter-stop"><span aria-hidden="true">📍</span> Остановка</label>
          <select id="filter-stop" className="filter-bar__control" disabled title={API_HINT}>
            <option>Выберите…</option>
          </select>
        </div>
        <div className="filter-bar__field">
          <label htmlFor="filter-date"><span aria-hidden="true">📅</span> Дата</label>
          <input id="filter-date" className="filter-bar__control filter-bar__control--date" disabled readOnly value={dataDateLabel} title="Дата синтетического ряда; выбор даты недоступен в v1" />
        </div>
        <div className="filter-bar__field">
          <label id="filter-horizon-label"><span aria-hidden="true">⏱</span> Горизонт</label>
          <div className="filter-bar__horizon" role="group" aria-labelledby="filter-horizon-label">
            <button type="button" className="filter-bar__horizon-btn" aria-pressed="true">1 день</button>
            <button type="button" className="filter-bar__horizon-btn" aria-pressed="false" disabled title={API_HINT}>1 мес</button>
            <button type="button" className="filter-bar__horizon-btn" aria-pressed="false" disabled title="Сценарий: допущение диспетчера, не реальный прогноз. Требуется согласование расчёта">1 год</button>
          </div>
        </div>
        <div className="filter-bar__more" ref={popoverRef}>
          <button type="button" className="filter-bar__more-btn" aria-haspopup="dialog" aria-expanded={moreOpen}
            aria-label="Ещё фильтры: направление и сброс" onClick={() => setMoreOpen(o => !o)}>⋯</button>
          {moreOpen && (
            <div className="filter-bar__popover" role="dialog" aria-label="Дополнительные фильтры">
              <div className="filter-bar__field">
                <label htmlFor="filter-direction">Направление</label>
                <select id="filter-direction" className="filter-bar__control" disabled title={API_HINT}>
                  <option>Не определено</option>
                </select>
              </div>
              <button type="button" className="filter-bar__reset" disabled title="Пока нет применённых фильтров для сброса">Сбросить фильтры</button>
              <p className="filter-bar__note">{API_HINT}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
