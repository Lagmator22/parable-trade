import { afterEach, expect, test, vi } from 'vitest';
import { metrics } from '../../test/fixtures';
import { mount } from '../../test/mount';
import { stubFetch } from '../../test/net';
import { OptimizePanel } from './OptimizePanel';
import type { Build } from './useBuild';

afterEach(() => vi.unstubAllGlobals());

test('rows from a still running job are shown before it finishes', async () => {
  const { act } = await import('react');
  let polls = 0;
  stubFetch((_m, path) => {
    if (path === '/api/lab/optimize') return { job_id: 'j_1' };
    polls += 1;
    const row = { params: { fast: 8 }, train: metrics, test: metrics, overfit: false };
    return polls === 1
      ? { id: 'j_1', kind: 'optimize', status: 'running', progress: 0.4, message: 'trying', result: { rows: [row] }, error: null, created_at: 0 }
      : { id: 'j_1', kind: 'optimize', status: 'done', progress: 1, message: '', result: { rows: [row], grid_size: 20, evaluated: 20, train_bars: 70, test_bars: 30, base: { train: metrics, test: metrics } }, error: null, created_at: 0 };
  });
  const build = { spec: { params: {} }, data: { symbol: 'x' }, validation: { ok: true }, setSpec: () => {} } as unknown as Build;
  const view = await mount(<OptimizePanel build={build}/>);
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Find best')!);
  await act(async () => { await new Promise(r => setTimeout(r, 30)); });
  expect(view.host.textContent).toContain('fast 8');
  expect(view.host.textContent).not.toContain('tried');
  await act(async () => { await new Promise(r => setTimeout(r, 1100)); });
  expect(view.host.textContent).toContain('20/20 tried');
  await view.unmount();
});
