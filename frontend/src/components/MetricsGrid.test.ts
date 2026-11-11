import { expect, test } from 'vitest';
import type { Metrics } from '../api';
import { metricCells } from './MetricsGrid';

const base = {
  total_return_pct: -3, benchmark_return_pct: 0, excess_return_pct: -3, cagr_pct: null, max_drawdown_pct: 3, volatility_pct: 10,
  sharpe: -869.14, sortino: 250, trades: 4, win_rate_pct: 0, profit_factor: null, avg_win_pct: 0, avg_loss_pct: -1,
  best_trade_pct: 0, worst_trade_pct: -1, exposure_pct: 5, avg_hold_bars: 2, avg_hold_s: 60, fees_paid: 1, start_cash: 10000, final_equity: 9700,
} as Metrics;

test('absurd ratios are capped for display', () => {
  const cells = Object.fromEntries(metricCells(base, 'USDT').map(c => [c.key, c.value]));
  expect(cells.sharpe).toBe('<-99');
  expect(cells.sortino).toBe('>99');
  expect(metricCells({ ...base, sharpe: 1.234 }, 'USDT').find(c => c.key === 'sharpe')?.value).toBe('1.23');
});
