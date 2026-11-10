import type { LedgerEntry, Run } from './api';
import type { Line } from './components/ui/Chart';
import { toMillis } from './format';

const toSeconds = (timestamp: number) => toMillis(timestamp) / 1000;
const dollars = (micro: number) => micro / 1_000_000;

function tradePoints(timeline: LedgerEntry[]): [number, number][] {
  return timeline
    .filter(entry => entry.kind === 'run.trade' && typeof entry.data.equity_after === 'number')
    .map(entry => [toSeconds(entry.at), dollars(entry.data.equity_after as number)] as [number, number])
    .sort((a, b) => a[0] - b[0]);
}

function flat(name: string, color: string, value: number, from: number, to: number): Line {
  return { name, color, dashed: true, guide: true, points: [[from, value], [to, value]] };
}

export function equityLines(run: Run, timeline: LedgerEntry[], minReturnBps: number, nowSeconds: number): Line[] {
  const start = dollars(run.start_cash_usd);
  const from = toSeconds(run.started_at);
  const current = run.status === 'alive' ? nowSeconds : toSeconds(run.ended_at ?? nowSeconds);
  const live = dollars(run.final_equity_usd ?? run.equity_usd);
  const trail: [number, number][] = [[from, start], ...tradePoints(timeline), [Math.max(current, from + 1), live]];
  const to = run.status === 'alive' ? Math.max(toSeconds(run.expires_at), current) : Math.max(current, from + 1);
  const lossFloor = dollars(run.peak_equity_usd) * (1 - run.rules.max_loss_bps / 10_000);
  return [
    { name: 'Equity', color: 'var(--ink)', points: trail },
    flat('Start', 'var(--grey)', start, from, to),
    flat('Min return', 'var(--green)', start * (1 + minReturnBps / 10_000), from, to),
    flat('Loss limit', 'var(--orange-text)', lossFloor, from, to),
  ];
}
