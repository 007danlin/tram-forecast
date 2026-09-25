import type { Ref } from 'react';
import './Workspace.css';
import { TramMap } from './TramMap';
import { ForecastCard } from './ForecastCard';
import { TimelinePanel } from './TimelinePanel';
import type { ForecastPoint } from './ForecastData';

export function Workspace({
  hidden, points, unit, isMock, loading, error, onRetry, fetchedAt,
  selectedIndex, onSelectIndex, cardOpen, onCardClose, onCardOpen,
  playing, onTogglePlay, reopenRef,
}: {
  hidden: boolean;
  points: ForecastPoint[];
  unit: string;
  isMock: boolean;
  loading: boolean;
  error: string;
  onRetry: () => void;
  fetchedAt: Date | null;
  selectedIndex: number | null;
  onSelectIndex: (i: number) => void;
  cardOpen: boolean;
  onCardClose: () => void;
  onCardOpen: () => void;
  playing: boolean;
  onTogglePlay: () => void;
  reopenRef: Ref<HTMLButtonElement>;
}) {
  return (
    <div className="workspace" style={{ display: hidden ? 'none' : 'block' }}>
      <div className="workspace__map-wrap">
        <TramMap />
      </div>
      <div className="workspace__overlay">
        {cardOpen
          ? <div className="workspace__overlay-card">
              <ForecastCard points={points} unit={unit} isMock={isMock} loading={loading} error={error} onRetry={onRetry}
                fetchedAt={fetchedAt} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex} onClose={onCardClose} />
            </div>
          : <div className="workspace__overlay-reopen">
              <button ref={reopenRef} type="button" className="forecast-card-reopen" onClick={onCardOpen}>Открыть прогноз</button>
            </div>}
        <div className="workspace__overlay-timeline">
          <TimelinePanel points={points} selectedIndex={selectedIndex} onSelectIndex={onSelectIndex}
            playing={playing} onTogglePlay={onTogglePlay} />
        </div>
      </div>
    </div>
  );
}
