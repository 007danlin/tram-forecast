import { useEffect, useRef, useState } from 'react';
import type { Theme } from '../theme/useTheme';
import { Button, Icon } from './ui';
import './AppShell.css';
export type ViewName = 'map' | 'analytics' | 'routes';
export function AppHeader({ view, onViewChange, onOpenSettings, onOpenYear, yearAvailable, theme, onThemeChange }: {
  view: ViewName; onViewChange: (v: ViewName) => void; onOpenSettings: () => void;
  onOpenYear: () => void; yearAvailable: boolean;
  theme: Theme; onThemeChange: (t: Theme) => void;
}) {
  const [menu, setMenu] = useState(false);
  const navRef = useRef<HTMLElement>(null), menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menu) return;
    navRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const close = (e: PointerEvent) => {if (!navRef.current?.contains(e.target as Node) && !menuRef.current?.contains(e.target as Node)) setMenu(false);};
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [menu]);
  return <header className="app-shell__header" onKeyDown={e => {if (e.key === 'Escape' && menu) {setMenu(false); menuRef.current?.focus();}}}>
    <a href="#" className="app-shell__brand" onClick={e => {e.preventDefault(); onViewChange('map');}} aria-label="TramFlow — карта и прогноз">
      <span className="brand-dot" aria-hidden="true"/><span className="brand-name">TramFlow</span>
    </a>
    <div className="header-actions">
      <nav ref={navRef} id="main-nav" className={`app-shell__nav${menu ? ' is-open' : ''}`} aria-label="Разделы приложения">
        {([['map', 'Карта'], ['analytics', 'Аналитика']] as const).map(([value, label]) =>
          <button key={value} aria-current={view === value ? 'page' : undefined} onClick={() => {onViewChange(value); setMenu(false);}}>{label}</button>)}
        <button aria-haspopup="dialog" onClick={onOpenSettings}>О данных</button>
        <button className="nav-year" aria-haspopup="dialog" disabled={!yearAvailable} onClick={() => {menuRef.current?.focus(); setMenu(false); onOpenYear();}}>На год</button>
        <button className="nav-theme" onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")} aria-label={`Включить ${theme === "dark" ? "светлую" : "тёмную"} тему`}>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</button>
      </nav>
      <Button className="mobile-data" variant="ghost" aria-haspopup="dialog" onClick={onOpenSettings}>Данные</Button>
      <Button className="theme-toggle" aria-label={`Включить ${theme === 'dark' ? 'светлую' : 'тёмную'} тему`} onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}>
        <Icon name={theme === 'dark' ? 'moon' : 'sun'}/><span>{theme === 'dark' ? 'Тёмная' : 'Светлая'}</span>
      </Button>
      <button ref={menuRef} className="button icon-button nav-toggle" aria-label={menu ? 'Закрыть меню' : 'Открыть меню'} aria-expanded={menu} aria-controls="main-nav" onClick={() => setMenu(m => !m)}>{menu ? <Icon name="close"/> : <span aria-hidden="true">···</span>}</button>
    </div>
  </header>;
}
