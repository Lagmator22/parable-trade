import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { charts } from '../../test/chartMock';
import { mount } from '../../test/mount';
import { stubFetch, type Call } from '../../test/net';
import { RunChart } from './RunChart';

vi.mock('lightweight-charts', async () => await import('../../test/chartMock'));

let calls: Call[] = [];
let batch = 0;
const batches = [
  [[100, 1_000_000_000, 50_00000000]],
  [[160, 1_020_000_000, 55_00000000], [220, 1_030_000_000, 60_00000000]],
];

beforeEach(() => {
  charts.length = 0;
  batch = 0;
  calls = stubFetch(() => ({ run_id: 5, quote: 'USDT', start_cash: 1_000_000_000, points: batches[Math.min(batch++, 1)] }));
});
afterEach(() => vi.unstubAllGlobals());

const wait = async (ms: number) => { const { act } = await import('react'); await act(async () => { await new Promise(r => setTimeout(r, ms)); }); };

test('loads the curve then appends only new points live, with buy and hold from price', async () => {
  const view = await mount(<RunChart runId={5} alive label="Live" every={40}/>);
  await wait(10);
  await wait(120);
  const [equity, hold] = charts[0].series;
  expect(equity.data).toHaveLength(1);
  expect(equity.updates.length).toBeGreaterThanOrEqual(2);
  expect((equity.updates[0] as { time: number; value: number })).toEqual({ time: 160, value: 1020 });
  expect((hold.updates[0] as { value: number }).value).toBeCloseTo(1100, 5);
  expect(calls[1].path).toBe('/api/runs/5/points?since=100');
  await view.unmount();
});

test('a finished run is fetched once and not polled', async () => {
  const view = await mount(<RunChart runId={5} alive={false} label="Done" every={20}/>);
  await wait(100);
  expect(calls).toHaveLength(1);
  await view.unmount();
});
