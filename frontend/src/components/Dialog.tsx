import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Button, Icon } from './ui';
import './SettingsPanel.css';

export function Dialog({title, onClose, children}: {title: string; onClose: () => void; children: ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null), titleId = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {dialog?.close(); if (trigger?.isConnected) trigger.focus();};
  }, []);
  return <dialog ref={ref} className="settings-panel" aria-labelledby={titleId}
    onCancel={e => {e.preventDefault(); onClose();}}
    onClick={e => {
      if (e.target !== e.currentTarget) return;
      const r = e.currentTarget.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) onClose();
    }}>
    <div className="settings-panel__head"><h2 id={titleId}>{title}</h2><Button className="icon-button" aria-label="Закрыть окно" onClick={onClose} autoFocus><Icon name="close"/></Button></div>
    {children}
  </dialog>;
}
