import { createRef } from 'react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { charts } from '../../test/chartMock';
import { mount } from '../../test/mount';
import { LiveChart, cleanSeries, tick, type LiveChartHandle } from './LiveChart';

vi.mock('lightweight-charts', async () => await import('../../test/chartMock'));

const bars = [[3, 1, 2, 0.5, 1.5, 10], [1, 1, 2, 0.5, 1.2, 10], [1, 1, 2, 0.5, 1.3, 10], [2, 1.3, 2, 1, 1.4, 5]] as [number, number, number, number, number, number][];

describe('LiveChart', () => {
  beforeEach(() => { charts.length = 0; document.documentElement.removeAttribute('data-theme'); });

  it('uses clock ticks on short spans and dates on long ones', () => {
    expect(tick(1_700_000_000, 600)).toMatch(/\d\d:\d\d:\d\d/);
    expect(tick(1_700_000_000, 7200)).toMatch(/^\d\d:\d\d$/);
    expect(tick(1_700_000_000, 10 * 86400)).not.toMatch(/:/);
  });

  it('sorts and de-duplicates data', () => {
    expect(cleanSeries([[3, 1], [1, 2], [1, 5]]).map(r => r.join(':'))).toEqual(['1:5', '3:1']);
  });

  it('renders candles with markers and an aria label', async () => {
    const view = await mount(<LiveChart label="Price" showVolume series={[{ id: 'p', kind: 'candles', name: 'P', data: bars }]} markers={[{ t: 2.5, side: 'buy' }, { t: 3, side: 'sell', text: 'stop' }]}/>);
    expect(view.host.querySelector('[aria-label="Price"]')).not.toBeNull();
    const chart = charts[0];
    const candles = chart.series.find(s => s.kind === 'candles')!;
    expect(candles.data).toHaveLength(3);
    expect((candles.data as { time: number }[]).map(d => d.time)).toEqual([1, 2, 3]);
    expect((candles.markers as { time: number; text: string }[]).map(m => [m.time, m.text])).toEqual([[2, 'Buy'], [3, 'stop']]);
    expect(chart.series.some(s => s.kind === 'volume')).toBe(true);
    await view.unmount();
    expect(chart.removed).toBe(true);
  });

  it('drops marker labels when there are many markers', async () => {
    const many = Array.from({ length: 14 }, (_, i) => ({ t: 1 + (i % 3) * 0.5, side: 'buy' as const, text: 'entry' }));
    const view = await mount(<LiveChart label="Price" series={[{ id: 'p', kind: 'candles', name: 'P', data: bars }]} markers={many}/>);
    const candles = charts[0].series.find(s => s.kind === 'candles')!;
    expect((candles.markers as { text: string }[]).every(m => m.text === '')).toBe(true);
    await view.unmount();
  });

  it('keeps appended points when the parent re-renders', async () => {
    const ref = createRef<LiveChartHandle>();
    const data: [number, number][] = [[1, 100], [2, 101]];
    const spec = [{ id: 'e', kind: 'line' as const, name: 'E', data }];
    const view = await mount(<LiveChart ref={ref} label="Eq" series={spec} priceLines={[{ price: 100, label: 'A' }]}/>);
    const line = charts[0].series[0];
    act(() => { ref.current!.append('e', [3, 102]); });
    expect(line.updates).toHaveLength(1);
    const before = line.data;
    await view.rerender(<LiveChart ref={ref} label="Eq" series={spec} priceLines={[{ price: 100, label: 'A' }]}/>);
    expect(line.data).toBe(before);
    await view.unmount();
  });

  it('rebases lines to percent and appends points', async () => {
    const ref = createRef<LiveChartHandle>();
    const view = await mount(<LiveChart ref={ref} label="Eq" percent series={[{ id: 'e', kind: 'line', name: 'E', data: [[1, 100], [2, 110]] }]}/>);
    const line = charts[0].series[0];
    const values = (line.data as { value: number }[]).map(d => d.value);
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(10, 6);
    act(() => ref.current!.append('e', [3, 120]));
    const update = line.updates[0] as { time: number; value: number };
    expect(update.time).toBe(3);
    expect(update.value).toBeCloseTo(20, 6);
    await view.unmount();
  });

  it('rereads colours when the theme changes', async () => {
    document.documentElement.style.setProperty('--card', '#111111');
    const view = await mount(<LiveChart label="T" series={[{ id: 'e', kind: 'line', name: 'E', data: [[1, 1]] }]}/>);
    const layout = () => (charts[0].options.layout as { background: { color: string } }).background.color;
    expect(layout()).toBe('#111111');
    document.documentElement.style.setProperty('--card', '#222222');
    await act(async () => { document.documentElement.dataset.theme = 'dark'; await Promise.resolve(); });
    expect(layout()).toBe('#222222');
    document.documentElement.style.removeProperty('--card');
    await view.unmount();
  });
});
