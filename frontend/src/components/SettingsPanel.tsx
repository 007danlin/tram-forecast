import { useEffect, useRef } from "react";
import { SourceMonitor } from "./SourceMonitor";
import { DataDetails } from "./DataDetails";
import { Button, Icon } from "./ui";
import "./SettingsPanel.css";
export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="settings-panel"
      aria-labelledby="data-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <div className="settings-panel__head">
        <h2 id="data-title">О данных</h2>
        <Button
          className="icon-button"
          aria-label="Закрыть сведения"
          onClick={onClose}
          autoFocus
        >
          <Icon name="close" />
        </Button>
      </div>
      <SourceMonitor />
      <details className="data-passport"><summary>Прогноз: данные и ограничения</summary>
      <DataDetails />
      </details>
    </dialog>
  );
}
