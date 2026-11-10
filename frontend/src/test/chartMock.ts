export const ColorType = { Solid: 'solid' };
export const CrosshairMode = { Normal: 0 };
export const LineStyle = { Solid: 0, Dashed: 2 };

export type FakeSeries = {
  kind: string; options: Record<string, unknown>; data: unknown[]; updates: unknown[]; markers: unknown[]; lines: unknown[];
  setData(d: unknown[]): void; update(p: unknown): void; setMarkers(m: unknown[]): void; applyOptions(o: Record<string, unknown>): void;
  createPriceLine(o: unknown): unknown; removePriceLine(h: unknown): void;
};
export type FakeChart = { series: FakeSeries[]; removed: boolean; options: Record<string, unknown>; fit: number };

export const charts: FakeChart[] = [];

function makeSeries(kind: string, options: Record<string, unknown>): FakeSeries {
  return {
    kind, options, data: [], updates: [], markers: [], lines: [],
    setData(d) { this.data = d; }, update(p) { this.updates.push(p); }, setMarkers(m) { this.markers = m; },
    applyOptions(o) { Object.assign(this.options, o); },
    createPriceLine(o) { this.lines.push(o); return o; }, removePriceLine(h) { this.lines = this.lines.filter(l => l !== h); },
  };
}

export function createChart(_el: unknown, options: Record<string, unknown>) {
  const chart: FakeChart = { series: [], removed: false, options, fit: 0 };
  charts.push(chart);
  const add = (kind: string) => (o: Record<string, unknown> = {}) => { const s = makeSeries(kind, o); chart.series.push(s); return s; };
  return {
    addLineSeries: add('line'), addAreaSeries: add('area'), addCandlestickSeries: add('candles'), addHistogramSeries: add('volume'),
    removeSeries(s: FakeSeries) { chart.series = chart.series.filter(x => x !== s); },
    priceScale: () => ({ applyOptions: () => undefined }),
    timeScale: () => ({ fitContent: () => { chart.fit += 1; } }),
    applyOptions(o: Record<string, unknown>) { Object.assign(chart.options, o); },
    remove() { chart.removed = true; },
  };
}
