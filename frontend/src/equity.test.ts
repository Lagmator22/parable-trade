import { describe, expect, it } from 'vitest';
import { chartDomain } from './components/ui/Chart';
import { equityLines } from './equity';
import type { Run } from './api';

const run = {
  id: 1, seller_id: 's', listing_id: null, purchase_id: null, purpose: 'practice', name: 'r', status: 'alive', cause: null, fingerprint: '',
  start_cash_usd: 10_000_000_000, peak_equity_usd: 10_010_000_000, final_equity_usd: null, equity_usd: 10_010_000_000,
  pnl_bps: 10, drawdown_bps: 0, started_at: 1000, expires_at: 2000, ended_at: null, trades: 0, refusals: 0, seconds_left: 900,
  rules: { strategy: '', brain: '', start_cash_usd: 0, max_trade_usd: 0, max_loss_bps: 2000, lease_seconds: 1000 },
} as Run;

describe('chart domain', () => {
  it('follows the equity line, not the guides', () => {
    const lines = equityLines(run, [], 500, 1500);
    const d = chartDomain(lines)!;
    expect(d.y0).toBeGreaterThan(9_900);
    expect(d.y1).toBeLessThan(10_100);
  });

  it('draws a line when all values are equal', () => {
    const d = chartDomain([{ name: 'a', color: 'x', points: [[0, 5], [1, 5]] }])!;
    expect(d.y1).toBeGreaterThan(d.y0);
    const z = chartDomain([{ name: 'a', color: 'x', points: [[0, 0], [1, 0]] }])!;
    expect(z.y1).toBeGreaterThan(z.y0);
  });

  it('ignores non-finite points', () => {
    expect(chartDomain([{ name: 'a', color: 'x', points: [[0, NaN]] }])).toBeNull();
  });
});
