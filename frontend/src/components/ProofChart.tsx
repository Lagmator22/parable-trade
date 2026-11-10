import { useMemo } from 'react';
import type { Bar, CurvePoint, Marker } from '../api';
import { LiveChart, type ChartMarker } from './ui/LiveChart';

type Props = { curve: CurvePoint[]; markers?: Marker[]; bars?: Bar[]; quote: string; label: string; percent?: boolean };

export function ProofChart({ curve, markers = [], bars, quote, label, percent = false }: Props) {
  const strategy = useMemo(() => curve.map(p => [p[0], p[1]] as [number, number]), [curve]);
  const hold = useMemo(() => curve.map(p => [p[0], p[2]] as [number, number]), [curve]);
  const marks = useMemo<ChartMarker[]>(() => markers.map(m => ({ t: m.t, side: m.side, text: m.text || undefined })), [markers]);
  const fmt = (v: number) => `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${quote}`;
  return <div className="proof-chart">
    {bars && bars.length > 0 && <LiveChart label={`${label} price`} height={260} markers={marks}
      series={[{ id: 'price', kind: 'candles', name: 'Price', data: bars }]}/>}
    <LiveChart label={`${label} equity`} percent={percent} yFormat={fmt}
      series={[
        { id: 'equity', kind: 'area', name: 'Strategy', color: '--ink', data: strategy },
        { id: 'hold', kind: 'line', name: 'Buy and hold', color: '--grey', dashed: true, data: hold },
      ]}/>
    <p className="chart-note">Solid: strategy. Dashed: buy and hold. Drag to pan, wheel to zoom.</p>
  </div>;
}
