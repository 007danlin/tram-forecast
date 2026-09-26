import type { Ref } from 'react';
import './AppShell.css';

export type ViewName = 'map' | 'analytics';

export type ConnectionStatus = 'checking' | 'ok' | 'error';

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  checking: 'Проверяем соединение…',
  ok: 'Пакет подключён',
  error: 'Пакет недоступен',
};

export function AppHeader({
  view, onViewChange, onOpenSettings, settingsOpen, settingsButtonRef, connection,
}: {
  view: ViewName;
  onViewChange: (v: ViewName) => void;
  onOpenSettings: () => void;
  settingsOpen: boolean;
  settingsButtonRef?: Ref<HTMLButtonElement>;
  connection: ConnectionStatus;
}) {
  return (
    <header className="app-shell__header">
      <div className="app-shell__brand">
        <img className="app-shell__logo" src="/tram-icon.png" alt="" aria-hidden="true" />
        <div className="app-shell__brand-text">
          <p className="app-shell__brand-name">
            TramFlow
            <span className="app-shell__badge">Исторический прогноз</span>
            <span className={`app-shell__badge app-shell__badge--${connection}`} role="status">{STATUS_LABEL[connection]}</span>
          </p>
          <p className="app-shell__brand-tagline">Прогнозирование пассажиропотока трамваев</p>
        </div>
      </div>
      <nav className="app-shell__nav" aria-label="Разделы приложения">
        <button type="button" className="app-shell__nav-btn" aria-current={view === 'map' ? 'page' : undefined}
          onClick={() => onViewChange('map')}>Карта</button>
        <button type="button" className="app-shell__nav-btn" aria-current={view === 'analytics' ? 'page' : undefined}
          onClick={() => onViewChange('analytics')}>Аналитика</button>
        <button ref={settingsButtonRef} type="button" className="app-shell__nav-btn" aria-current={settingsOpen ? 'page' : undefined}
          aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={onOpenSettings}>Настройки</button>
      </nav>
      <span className="app-shell__workplace" title="Рабочее место (демо-подпись, не авторизация)">ЕДЦ</span>
    </header>
  );
}
