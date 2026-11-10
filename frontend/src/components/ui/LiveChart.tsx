import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import {
  ColorType, CrosshairMode, LineStyle, createChart,
  type IChartApi, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts';

export type Bar = [number, number, number, number, number, number];
export type LineSeriesSpec = { id: string; kind: 'line' | 'area'; name: string; color?: string; dashed?: boolean; data: [number, number][]; scale?: 'left' | 'right' };
export type CandleSeriesSpec = { id: string; kind: 'candles'; name: string; data: Bar[] };
export type SeriesSpec = LineSeriesSpec | CandleSeriesSpec;
export type ChartMarker = { t: number; side: 'buy' | 'sell'; text?: string; seriesId?: string };
export type PriceLine = { price: number; label: string; color?: string; dashed?: boolean; seriesId?: string };
export type LiveChartHandle = { append(seriesId: string, point: [number, number] | Bar): void; fit(): void };
export type LiveChartProps = {
  series: SeriesSpec[]; markers?: ChartMarker[]; priceLines?: PriceLine[]; height?: number; label: string;
  showVolume?: boolean; percent?: boolean; yFormat?: (v: number) => string; xFormat?: (t: number) => string;
};

type Palette = Record<'ink' | 'orange' | 'blue' | 'green' | 'grey' | 'paper' | 'card' | 'rule', string>;
type Entry = { api: ISeriesApi<'Line'> | ISeriesApi<'Area'> | ISeriesApi<'Candlestick'>; kind: SeriesSpec['kind']; scale: string; base: number | null; last: number };

const NAMES = ['ink', 'orange', 'blue', 'green', 'grey', 'paper', 'card', 'rule'] as const;
const FALLBACK: Palette = { ink: '#0b0b0b', orange: '#ff4f00', blue: '#2547d0', green: '#17784a', grey: '#5c5c5c', paper: '#f5f5f4', card: '#ffffff', rule: '#d4d4d1' };
const CYCLE = ['ink', 'orange', 'blue', 'green', 'grey'] as const;

export function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const out = { ...FALLBACK };
  for (const name of NAMES) {
    const value = style.getPropertyValue(`--${name}`).trim();
    if (value) out[name] = value;
  }
  return out;
}

export function cleanSeries<T extends number[]>(rows: T[]): T[] {
  const sorted = rows.filter(r => Number.isFinite(r[0])).slice().sort((a, b) => a[0] - b[0]);
  const out: T[] = [];
  for (const row of sorted) {
    if (out.length && out[out.length - 1][0] === row[0]) out[out.length - 1] = row;
    else out.push(row);
  }
  return out;
}

function lineData(rows: [number, number][], percent: boolean) {
  const clean = cleanSeries(rows).filter(r => Number.isFinite(r[1]));
  const base = clean.length && percent && clean[0][1] !== 0 ? clean[0][1] : null;
  return { base, data: clean.map(([t, v]) => ({ time: t as UTCTimestamp, value: base === null ? v : (v / base - 1) * 100 })) };
}

function snap(times: number[], t: number): number | null {
  if (!times.length) return null;
  let lo = 0, hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid - 1;
  }
  return times[lo];
}

const isPhone = () => typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 640px)').matches;

export const LiveChart = forwardRef<LiveChartHandle, LiveChartProps>(function LiveChart(props, ref) {
  const { series, markers, priceLines, height, label, showVolume, percent = false } = props;
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const entries = useRef(new Map<string, Entry>());
  const volume = useRef<ISeriesApi<'Histogram'> | null>(null);
  const palette = useRef<Palette>(FALLBACK);
  const latest = useRef(props);
  const fitted = useRef(false);
  latest.current = props;
  const px = height ?? (isPhone() ? 200 : 320);

  const paletteKey = useRef(0);

  function colorFor(spec: SeriesSpec, index: number) {
    if (spec.kind !== 'candles' && spec.color) return spec.color.startsWith('--') ? palette.current[spec.color.slice(2) as keyof Palette] ?? spec.color : spec.color;
    return palette.current[CYCLE[index % CYCLE.length]];
  }

  function theme() {
    palette.current = readPalette();
    paletteKey.current += 1;
    chart.current?.applyOptions({
      layout: { background: { type: ColorType.Solid, color: palette.current.card }, textColor: palette.current.grey, fontFamily: 'IBM Plex Mono, monospace' },
      grid: { vertLines: { color: palette.current.rule }, horzLines: { color: palette.current.rule } },
      rightPriceScale: { borderColor: palette.current.ink },
      leftPriceScale: { borderColor: palette.current.ink },
      timeScale: { borderColor: palette.current.ink },
    });
  }

  function sync() {
    const api = chart.current;
    if (!api) return;
    const { series: specs, percent: pct = false, showVolume: vol, markers: marks = [], priceLines: lines = [] } = latest.current;
    const wanted = new Set(specs.map(s => s.id));
    for (const [id, entry] of entries.current) {
      if (!wanted.has(id)) { api.removeSeries(entry.api); entries.current.delete(id); }
    }
    specs.forEach((spec, index) => {
      const color = colorFor(spec, index);
      const scale = spec.kind === 'candles' ? 'right' : spec.scale ?? 'right';
      let entry = entries.current.get(spec.id);
      if (entry && (entry.kind !== spec.kind || entry.scale !== scale)) {
        api.removeSeries(entry.api);
        entries.current.delete(spec.id);
        entry = undefined;
      }
      if (!entry) {
        if (spec.kind === 'candles') {
          const created = api.addCandlestickSeries({ title: spec.name, upColor: palette.current.green, downColor: palette.current.orange, borderUpColor: palette.current.green, borderDownColor: palette.current.orange, wickUpColor: palette.current.green, wickDownColor: palette.current.orange });
          entry = { api: created, kind: spec.kind, scale, base: null, last: 0 };
        } else {
          const options = { title: spec.name, color, lineWidth: 2 as const, priceScaleId: scale, lineStyle: spec.dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false };
          const created = spec.kind === 'area'
            ? api.addAreaSeries({ ...options, lineColor: color, topColor: `${color}33`, bottomColor: `${color}00` })
            : api.addLineSeries(options);
          entry = { api: created, kind: spec.kind, scale, base: null, last: 0 };
        }
        entries.current.set(spec.id, entry);
      }
      if (spec.kind === 'candles') {
        const rows = cleanSeries(spec.data);
        (entry.api as ISeriesApi<'Candlestick'>).setData(rows.map(r => ({ time: r[0] as UTCTimestamp, open: r[1], high: r[2], low: r[3], close: r[4] })));
        entry.last = rows.length ? rows[rows.length - 1][0] : 0;
      } else {
        const { base, data } = lineData(spec.data, pct);
        entry.base = base;
        entry.last = data.length ? (data[data.length - 1].time as number) : 0;
        entry.api.applyOptions({ color, lineStyle: spec.dashed ? LineStyle.Dashed : LineStyle.Solid } as never);
        (entry.api as ISeriesApi<'Line'>).setData(data);
      }
    });
    syncVolume(vol ? specs : []);
    syncMarkers(specs, marks);
    syncLines(specs, lines);
    const total = specs.reduce((n, s) => n + s.data.length, 0);
    if (total > 0 && !fitted.current) { api.timeScale().fitContent(); fitted.current = true; }
    if (total === 0) fitted.current = false;
  }

  function syncVolume(specs: SeriesSpec[]) {
    const api = chart.current;
    if (!api) return;
    const candles = specs.find((s): s is CandleSeriesSpec => s.kind === 'candles');
    if (!candles) {
      if (volume.current) { api.removeSeries(volume.current); volume.current = null; }
      return;
    }
    if (!volume.current) {
      volume.current = api.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume' });
      api.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    }
    volume.current.setData(cleanSeries(candles.data).map(r => ({ time: r[0] as UTCTimestamp, value: r[5], color: `${r[4] >= r[1] ? palette.current.green : palette.current.orange}66` })));
  }

  function syncMarkers(specs: SeriesSpec[], marks: ChartMarker[]) {
    if (!specs.length) return;
    const groups = new Map<string, SeriesMarker<Time>[]>();
    for (const spec of specs) groups.set(spec.id, []);
    for (const mark of marks) {
      const id = mark.seriesId && groups.has(mark.seriesId) ? mark.seriesId : specs[0].id;
      const spec = specs.find(s => s.id === id)!;
      const time = snap(cleanSeries(spec.data as number[][]).map(r => r[0]), mark.t);
      if (time === null) continue;
      const buy = mark.side === 'buy';
      groups.get(id)!.push({ time: time as UTCTimestamp, position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown', color: buy ? palette.current.green : palette.current.orange, text: mark.text ?? (buy ? 'Buy' : 'Sell') });
    }
    for (const [id, list] of groups) {
      const entry = entries.current.get(id);
      if (entry) entry.api.setMarkers(list.sort((a, b) => (a.time as number) - (b.time as number)));
    }
  }

  const lineHandles = useRef<{ entry: Entry['api']; handle: ReturnType<ISeriesApi<'Line'>['createPriceLine']> }[]>([]);

  function syncLines(specs: SeriesSpec[], lines: PriceLine[]) {
    for (const { entry, handle } of lineHandles.current) entry.removePriceLine(handle);
    lineHandles.current = [];
    for (const line of lines) {
      const entry = entries.current.get(line.seriesId ?? specs[0]?.id ?? '');
      if (!entry) continue;
      const handle = (entry.api as ISeriesApi<'Line'>).createPriceLine({ price: line.price, color: line.color ?? palette.current.grey, lineWidth: 1, lineStyle: line.dashed === false ? LineStyle.Solid : LineStyle.Dashed, axisLabelVisible: true, title: line.label });
      lineHandles.current.push({ entry: entry.api, handle });
    }
  }

  useImperativeHandle(ref, () => ({
    fit: () => chart.current?.timeScale().fitContent(),
    append(seriesId, point) {
      const entry = entries.current.get(seriesId);
      if (!entry) return;
      if (point.length === 6) {
        const [t, open, high, low, close, vol] = point as Bar;
        (entry.api as ISeriesApi<'Candlestick'>).update({ time: t as UTCTimestamp, open, high, low, close });
        if (volume.current) volume.current.update({ time: t as UTCTimestamp, value: vol, color: `${close >= open ? palette.current.green : palette.current.orange}66` });
        entry.last = Math.max(entry.last, t);
        return;
      }
      const [t, v] = point as [number, number];
      if (t < entry.last) return;
      if (entry.base === null && latest.current.percent && v !== 0) entry.base = v;
      const value = entry.base === null ? v : (v / entry.base - 1) * 100;
      (entry.api as ISeriesApi<'Line'>).update({ time: t as UTCTimestamp, value });
      entry.last = t;
    },
  }), []);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const api = createChart(element, {
      width: element.clientWidth || 600, height: px,
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: true, handleScale: true,
      leftPriceScale: { visible: false },
      localization: {
        priceFormatter: (v: number) => (latest.current.percent ? `${v.toFixed(1)}%` : latest.current.yFormat ? latest.current.yFormat(v) : v.toLocaleString(undefined, { maximumFractionDigits: 6 })),
        timeFormatter: (t: number) => (latest.current.xFormat ? latest.current.xFormat(t) : new Date(t * 1000).toLocaleString([], { hour12: false })),
      },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: number) => (latest.current.xFormat ? latest.current.xFormat(t) : new Date(t * 1000).toLocaleDateString()) },
    });
    chart.current = api;
    entries.current.clear();
    fitted.current = false;
    theme();
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => api.applyOptions({ width: element.clientWidth }));
      observer.observe(element);
    }
    const mutation = new MutationObserver(() => { theme(); sync(); });
    mutation.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    sync();
    return () => {
      observer?.disconnect();
      mutation.disconnect();
      api.remove();
      chart.current = null;
      entries.current.clear();
      lineHandles.current = [];
      volume.current = null;
    };
  }, []);

  useEffect(() => { chart.current?.applyOptions({ height: px }); }, [px]);
  const signature = useMemo(() => `${percent}|${showVolume}`, [percent, showVolume]);
  useEffect(() => { fitted.current = false; }, [signature]);
  useEffect(() => { sync(); }, [series, markers, priceLines, signature]);

  return <div className="live-chart" ref={host} role="img" aria-label={label} style={{ height: px }}/>;
});
