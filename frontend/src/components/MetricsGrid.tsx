import type { Metrics } from '../api';

type Cell = { key: string; label: string; value: string; tone?: 'up' | 'down' };

const pct = (v: number | null, digits = 1) => (v === null || !Number.isFinite(v) ? '-' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`);
const num = (v: number | null, digits = 2) => (v === null || !Number.isFinite(v) ? '-' : v.toFixed(digits));
const tone = (v: number | null): 'up' | 'down' | undefined => (v === null || v === 0 ? undefined : v > 0 ? 'up' : 'down');

function hold(seconds: number) {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} d`;
}

export function metricCells(m: Metrics, quote: string): Cell[] {
  const money = (v: number) => `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${quote}`;
  return [
    { key: 'total_return_pct', label: 'Return', value: pct(m.total_return_pct), tone: tone(m.total_return_pct) },
    { key: 'benchmark_return_pct', label: 'Buy and hold', value: pct(m.benchmark_return_pct), tone: tone(m.benchmark_return_pct) },
    { key: 'excess_return_pct', label: 'Beat hold by', value: pct(m.excess_return_pct), tone: tone(m.excess_return_pct) },
    { key: 'max_drawdown_pct', label: 'Worst drop', value: `-${num(m.max_drawdown_pct, 1)}%`, tone: m.max_drawdown_pct > 0 ? 'down' : undefined },
    { key: 'sharpe', label: 'Sharpe', value: num(m.sharpe) },
    { key: 'trades', label: 'Trades', value: String(m.trades) },
    { key: 'win_rate_pct', label: 'Win rate', value: `${num(m.win_rate_pct, 0)}%` },
    { key: 'cagr_pct', label: 'Per year', value: pct(m.cagr_pct), tone: tone(m.cagr_pct) },
    { key: 'sortino', label: 'Sortino', value: num(m.sortino) },
    { key: 'volatility_pct', label: 'Volatility', value: `${num(m.volatility_pct, 1)}%` },
    { key: 'profit_factor', label: 'Profit factor', value: num(m.profit_factor) },
    { key: 'exposure_pct', label: 'In market', value: `${num(m.exposure_pct, 0)}%` },
    { key: 'avg_win_pct', label: 'Avg win', value: pct(m.avg_win_pct, 2), tone: tone(m.avg_win_pct) },
    { key: 'avg_loss_pct', label: 'Avg loss', value: pct(m.avg_loss_pct, 2), tone: tone(m.avg_loss_pct) },
    { key: 'best_trade_pct', label: 'Best trade', value: pct(m.best_trade_pct, 2), tone: tone(m.best_trade_pct) },
    { key: 'worst_trade_pct', label: 'Worst trade', value: pct(m.worst_trade_pct, 2), tone: tone(m.worst_trade_pct) },
    { key: 'avg_hold', label: 'Avg hold', value: hold(m.avg_hold_s) },
    { key: 'fees_paid', label: 'Fees paid', value: money(m.fees_paid) },
    { key: 'start_cash', label: 'Start', value: money(m.start_cash) },
    { key: 'final_equity', label: 'End', value: money(m.final_equity), tone: tone(m.final_equity - m.start_cash) },
  ];
}

export function MetricsGrid({ metrics, quote, compact = false }: { metrics: Metrics; quote: string; compact?: boolean }) {
  const cells = metricCells(metrics, quote).slice(0, compact ? 6 : undefined);
  return <dl className={`metrics-grid ${compact ? 'compact' : ''}`}>
    {cells.map(c => <div key={c.key} data-metric={c.key}><dt>{c.label}</dt><dd className={c.tone}>{c.value}</dd></div>)}
  </dl>;
}
