import { useState } from 'react';
import { SourceMonitor } from './SourceMonitor';
import { DataDetails } from './DataDetails';
import { Dialog } from './Dialog';
import { Button } from './ui';
export function SettingsPanel({onClose}: {onClose: () => void}) {
  const [tab, setTab] = useState<'forecast' | 'sources' | 'passport'>('sources');
  return <Dialog title="О данных" onClose={onClose}>
    <div className="data-tabs" role="group" aria-label="Сведения о данных">
      {([['forecast', 'Прогноз'], ['sources', 'Источники'], ['passport', 'Паспорт']] as const).map(([value, label]) => <Button key={value} variant="ghost" aria-pressed={tab === value} onClick={() => setTab(value)}>{label}</Button>)}
    </div>
    <div hidden={tab !== 'sources'}><SourceMonitor /></div>
    {tab !== 'sources' && <DataDetails passport={tab === 'passport'} />}
  </Dialog>;
}
