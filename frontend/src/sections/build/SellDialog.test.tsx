import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mount } from '../../test/mount';
import { stubFetch, type Call } from '../../test/net';
import { SellDialog } from './SellDialog';
import type { Build } from './useBuild';

const make = (symbol: string, proofId = 'pf_1') => ({
  spec: { name: 'Trend Fox', summary: 'Rides moves', symbol }, market: { symbol },
  saved: { agentId: 'a_1', versionId: 'v_1', proofId, key: 'k' },
}) as unknown as Build;

let calls: Call[] = [];
beforeEach(() => {
  window.location.hash = '';
  calls = stubFetch(() => ({ id: 'l_new0000001' }));
});
afterEach(() => vi.unstubAllGlobals());

const press = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text) as HTMLButtonElement;

test('lists a hold sale with the trial terms and the free test-drive', async () => {
  const onClose = vi.fn();
  const view = await mount(<SellDialog build={make('binance:BTCUSDT')} onClose={onClose}/>);
  expect(press(view.host, 'Pay if proven').disabled).toBe(false);
  expect(view.host.textContent).toContain('Allow free test-drive before buying');
  await view.click(press(view.host, 'List for sale'));
  expect(calls[0]).toMatchObject({ method: 'POST', path: '/api/listings' });
  expect(calls[0].body).toMatchObject({ version_id: 'v_1', proof_id: 'pf_1', title: 'Trend Fox', price_cents: 1900, mode: 'hold', trial_s: 86400, min_return_bps: 0, max_loss_bps: 1000, allow_test_drive: true });
  expect(window.location.hash).toBe('#agent/l_new0000001');
  expect(onClose).toHaveBeenCalled();
  await view.unmount();
});

test('instant mode hides the trial terms', async () => {
  const view = await mount(<SellDialog build={make('binance:BTCUSDT')} onClose={() => {}}/>);
  await view.click(press(view.host, 'Instant'));
  expect(view.host.textContent).not.toContain('Min return');
  await view.click(press(view.host, 'List for sale'));
  expect(calls[0].body).toMatchObject({ mode: 'instant' });
  await view.unmount();
});

test.each(['upload:d_ab12cd34ef', 'sample:BTCUSDT'])('disables Pay if proven for %s and sells instant', async symbol => {
  const view = await mount(<SellDialog build={make(symbol)} onClose={() => {}}/>);
  expect(press(view.host, 'Pay if proven').disabled).toBe(true);
  expect(press(view.host, 'Instant').getAttribute('aria-pressed')).toBe('true');
  expect(view.host.querySelector('[role=note]')?.textContent).toContain('instant only');
  await view.click(press(view.host, 'List for sale'));
  expect(calls[0].body).toMatchObject({ mode: 'instant' });
  await view.unmount();
});

test('validates the form and needs a stored proof', async () => {
  const view = await mount(<SellDialog build={make('binance:BTCUSDT', '')} onClose={() => {}}/>);
  expect(press(view.host, 'List for sale').disabled).toBe(true);
  await view.unmount();
});

test('short trials are only offered where 10 bars fit, and the reason is shown', async () => {
  const hourly = await mount(<SellDialog build={make('binance:BTCUSDT')} onClose={() => {}}/>);
  const twoMinutes = press(hourly.host, '2 min');
  expect(twoMinutes.disabled).toBe(true);
  expect(twoMinutes.title).toContain('at least 10 bars');
  expect(press(hourly.host, '1 day').disabled).toBe(false);
  await hourly.unmount();
  const fast = make('binance:BTCUSDT');
  (fast.spec as unknown as { interval: string }).interval = '1s';
  const view = await mount(<SellDialog build={fast} onClose={() => {}}/>);
  expect(press(view.host, '2 min').disabled).toBe(false);
  await view.click(press(view.host, '2 min'));
  await view.click(press(view.host, 'List for sale'));
  expect(calls[0].body).toMatchObject({ trial_s: 120 });
  await view.unmount();
});

test('the pitch follows the edited formulas instead of the stale AI summary', async () => {
  const edited = make('binance:BTCUSDT');
  (edited.spec as unknown as { built_by: string }).built_by = 'manual';
  (edited as unknown as { rules: unknown[] }).rules = [{ kind: 'entry', text: 'Buy when RSI is below 30' }];
  const view = await mount(<SellDialog build={edited} onClose={() => {}}/>);
  expect((view.host.querySelector('textarea') as HTMLTextAreaElement).value).toContain('Buy when RSI is below 30');
  await view.unmount();
});
