import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Info, Me } from '../../api';
import { mount } from '../../test/mount';
import { BuildPage } from './BuildPage';

vi.mock('lightweight-charts', async () => await import('../../test/chartMock'));

const metrics = {
  total_return_pct: 12.5, benchmark_return_pct: 4, excess_return_pct: 8.5, cagr_pct: null, max_drawdown_pct: 6, volatility_pct: 20, sharpe: 1.1,
  sortino: 1.4, trades: 7, win_rate_pct: 57, profit_factor: 1.8, avg_win_pct: 3, avg_loss_pct: -1.5, best_trade_pct: 6, worst_trade_pct: -3,
  exposure_pct: 40, avg_hold_bars: 5, avg_hold_s: 18000, fees_paid: 12, start_cash: 10000, final_equity: 11250,
};
const spec = {
  name: 'Trend', summary: 'Follows trend', symbol: 'sample:BTCUSDT', interval: '1h', built_by: 'template:trend', params: { fast: { value: 12, min: 5, max: 30, step: 1 } },
  entry: 'cross_above(ema(close, fast), ema(close, 26))', exit: '', size_pct: 100, stop_loss_pct: 5, take_profit_pct: 0, trailing_stop_pct: 0, fee_bps: 10, slippage_bps: 5,
};
const data = { symbol: 'sample:BTCUSDT', interval: '1h', start: 1, end: 3600, bars: 3, data_hash: 'h', source_kind: 'sample', quote: 'USDT' };
const bars = [[0, 1, 2, 1, 1.5, 1], [3600, 1.5, 2, 1, 1.8, 1], [7200, 1.8, 2.2, 1.7, 2, 1]];
const me: Me = { seller: { id: 's_1', name: 'Ada', verified: true, email_masked: 'a***' }, paypal_mode: 'mock' };
const info = { templates: [{ id: 'trend', label: 'Trend', blurb: 'Ride moves', family: 'trend' }] } as unknown as Info;

const calls: { method: string; path: string; body: unknown; headers: Record<string, string> }[] = [];

function route(method: string, path: string): unknown {
  if (path.startsWith('/api/markets/popular')) return [{ symbol: 'sample:BTCUSDT', name: 'Bitcoin', kind: 'crypto', quote: 'USDT', provider: 'sample', intervals: ['1h'], live: false }];
  if (path.startsWith('/api/markets/candles')) return { symbol: 'sample:BTCUSDT', interval: '1h', quote: 'USDT', source_kind: 'sample', bars, data_hash: 'h' };
  if (path.startsWith('/api/ai/questionnaire')) return { questions: [
    { id: 'family', text: 'Style', options: [{ id: 'trend', label: 'Trend' }, { id: 'dip', label: 'Dip' }] },
    { id: 'speed', text: 'Speed', options: [{ id: 'fast', label: 'Fast' }, { id: 'medium', label: 'Medium' }] },
  ] };
  if (path.startsWith('/api/ai/models')) return { platform: [{ id: 'gemini:x', provider: 'gemini', model: 'x', label: 'Gemini X', available: true, free: true }], own: [], free_tries: { limit: 5, used: 0, remaining: 5 } };
  if (path === '/api/ai/compile') return { spec, summary: 'Follows trend', rules: [{ kind: 'entry', text: 'Buy when EMA(12) crosses above EMA(26)' }], built_by: 'template:trend', attempts: 1, free_tries: { limit: 5, used: 0, remaining: 5 } };
  if (path === '/api/lab/validate') return { ok: true, errors: [], spec_hash: 'sh', rules: [{ kind: 'entry', text: 'Buy when EMA(12) crosses above EMA(26)' }] };
  if (path === '/api/lab/backtest') return { metrics, curve: [[0, 10000, 10000], [3600, 11250, 10400]], trades: [], markers: [{ t: 3600, side: 'buy', price: 1.5, text: '' }], data, quote: 'USDT', start_cash: 10000, spec_hash: 'sh', engine_version: 'lab-1', result_hash: 'r'.repeat(64) };
  if (path === '/api/agents') return { id: 'a_1', name: 'Trend', symbol: 'sample:BTCUSDT', interval: '1h', status: 'draft', latest_version_id: null, listing_id: null, updated_at: 0, headline: null, versions: [] };
  if (path === '/api/agents/a_1/versions') return { id: 'v_1', n: 1, name: 'Trend', spec_hash: 'sh', built_by: 'template:trend', created_at: 0, agent_id: 'a_1', summary: '', steps_text: '', spec };
  if (path === '/api/agents/a_1/versions/v_1/backtest') return { id: 'pf_1', kind: 'backtest', spec_hash: 'sh', symbol: 'sample:BTCUSDT', interval: '1h', data, metrics, curve: [], trades_count: 7, engine_version: 'lab-1', result_hash: 'r', ledger_seq: 1, matched: null, by: 'seller', created_at: 0, trades: [], markers: [] };
  throw new Error(`unrouted ${method} ${path}`);
}

describe('Build flow', () => {
  beforeEach(() => {
    calls.length = 0;
    localStorage.clear();
    sessionStorage.clear();
    vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      calls.push({ method, path, body: init.body ? JSON.parse(init.body as string) : undefined, headers: (init.headers ?? {}) as Record<string, string> });
      return new Response(JSON.stringify(route(method, path)), { status: 200 });
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  const settle = (fn: () => void) => vi.waitFor(fn, { timeout: 3000, interval: 20 });
  const press = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find(b => b.textContent?.includes(text)) as HTMLButtonElement | undefined;

  it('goes template, validate, backtest, save', async () => {
    const view = await mount(<BuildPage agentId="" me={me} info={info}/>);
    await settle(() => expect(press(view.host, 'Bitcoin')).toBeDefined());
    await view.click(press(view.host, 'Bitcoin')!);
    await settle(() => expect(press(view.host, 'Ride moves')?.disabled).toBe(false));
    await settle(() => expect(calls.some(c => c.path === '/api/ai/questionnaire')).toBe(true));
    await view.click(press(view.host, 'Ride moves')!);
    await settle(() => expect(calls.find(c => c.path === '/api/ai/compile')).toBeDefined());
    const compile = calls.find(c => c.path === '/api/ai/compile')!;
    expect(compile.body).toMatchObject({ symbol: 'sample:BTCUSDT', interval: '1h', answers: { family: 'trend', speed: 'medium' } });
    await settle(() => expect(view.host.textContent).toContain('Formulas are valid.'));
    expect(view.host.textContent).toContain('Buy when EMA(12) crosses above EMA(26)');

    await settle(() => expect(press(view.host, 'Backtest')?.disabled).toBe(false));
    await view.click([...view.host.querySelectorAll('button')].filter(b => b.textContent === 'Backtest').pop()!);
    await settle(() => expect(view.host.querySelector('[data-metric="total_return_pct"]')?.textContent).toContain('+12.5%'));
    expect(view.host.querySelectorAll('[data-metric]').length).toBe(20);

    await settle(() => expect(press(view.host, 'Save version')?.disabled).toBe(false));
    await view.click(press(view.host, 'Save version')!);
    await settle(() => expect(press(view.host, 'Saved')).toBeDefined());
    expect(calls.map(c => `${c.method} ${c.path}`)).toEqual(expect.arrayContaining(['POST /api/agents', 'POST /api/agents/a_1/versions', 'POST /api/agents/a_1/versions/v_1/backtest']));
    expect(press(view.host, 'Sell')?.disabled).toBe(false);
    await act(async () => { await new Promise(r => setTimeout(r, 10)); });
    await view.unmount();
  });
});
