import type { SaleMode, Track } from '../api';
import { SOURCE_LABEL } from '../format';

export function ModePill({ mode }: { mode: SaleMode }) {
  return <span className={`pill mode-${mode}`}>{mode === 'hold' ? 'Pay if proven' : 'Instant'}</span>;
}

export function DataPill({ kind }: { kind: string }) {
  return <span className={`pill data-${kind}`}>{SOURCE_LABEL[kind] ?? kind}</span>;
}

export function LivePill({ track }: { track: Track | null }) {
  if (!track || track.status !== 'alive') return null;
  return <span className="pill live-pill"><span className="live"/> Live</span>;
}

export function Stamp({ tone, children }: { tone: 'good' | 'bad' | 'neutral'; children: string }) {
  return <div className={`stamp stamp-${tone}`} role="status">{children}</div>;
}
