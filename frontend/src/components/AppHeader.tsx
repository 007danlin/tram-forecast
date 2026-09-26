import { useEffect, useRef, useState, type Ref } from "react";
import type { Theme } from "../theme/useTheme";
import { Button, Icon } from "./ui";
import "./AppShell.css";
export type ViewName = "map" | "analytics";
export type ConnectionStatus = "checking" | "ok" | "error";
export function AppHeader({
  view,
  onViewChange,
  settingsOpen,
  onOpenSettings,
  settingsButtonRef,
  theme,
  onThemeChange,
}: {
  view: ViewName;
  onViewChange: (v: ViewName) => void;
  settingsOpen: boolean;
  onOpenSettings: () => void;
  settingsButtonRef: Ref<HTMLButtonElement>;
  theme: Theme;
  onThemeChange: (t: Theme) => void;
}) {
  const [menu, setMenu] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menu) return;
    navRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const close = (e: PointerEvent) => {
      if (
        !navRef.current?.contains(e.target as Node) &&
        !menuRef.current?.contains(e.target as Node)
      )
        setMenu(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);
  return (
    <header
      className="app-shell__header"
      onKeyDown={(e) => {
        if (e.key === "Escape" && menu) {
          setMenu(false);
          menuRef.current?.focus();
        }
      }}
    >
      <a
        href="#"
        className="app-shell__brand"
        onClick={(e) => {
          e.preventDefault();
          onViewChange("map");
        }}
        aria-label="TramFlow — карта и прогноз"
      >
        <span className="brand-dot" aria-hidden="true" />
        <span className="brand-name">TramFlow</span>
        <span className="brand-tagline">Прогноз пассажиропотока</span>
      </a>
      <div className="header-actions">
        <nav
          ref={navRef}
          id="main-nav"
          className={`app-shell__nav${menu ? " is-open" : ""}`}
          aria-label="Разделы приложения"
        >
          <button
            type="button"
            aria-current={view === "map" ? "page" : undefined}
            onClick={() => {
              onViewChange("map");
              setMenu(false);
            }}
          >
            Карта и прогноз
          </button>
          <button
            type="button"
            aria-current={view === "analytics" ? "page" : undefined}
            onClick={() => {
              onViewChange("analytics");
              setMenu(false);
            }}
          >
            Аналитика
          </button>
          <button
            type="button"
            ref={settingsButtonRef}
            aria-haspopup="dialog"
            aria-expanded={settingsOpen}
            onClick={() => {
              onOpenSettings();
              setMenu(false);
            }}
          >
            О данных
          </button>
        </nav>
        <div className="theme-switch" role="group" aria-label="Тема оформления">
          <Button
            className="theme-option"
            aria-label="Включить тёмную тему"
            aria-pressed={theme === "dark"}
            onClick={() => onThemeChange("dark")}
          >
            <Icon name="moon" />
            <span>Тёмная</span>
          </Button>
          <Button
            className="theme-option"
            aria-label="Включить светлую тему"
            aria-pressed={theme === "light"}
            onClick={() => onThemeChange("light")}
          >
            <Icon name="sun" />
            <span>Светлая</span>
          </Button>
        </div>
        <Button
          className="theme-mobile icon-button"
          aria-label={`Включить ${theme === "dark" ? "светлую" : "тёмную"} тему`}
          onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} />
        </Button>
        <button
          ref={menuRef}
          className="button icon-button nav-toggle"
          aria-label={menu ? "Закрыть меню" : "Открыть меню"}
          aria-expanded={menu}
          aria-controls="main-nav"
          onClick={() => setMenu((m) => !m)}
        >
          <Icon name={menu ? "close" : "menu"} />
        </button>
      </div>
    </header>
  );
}
