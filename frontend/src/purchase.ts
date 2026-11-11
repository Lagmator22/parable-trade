import type { LedgerEntry, PurchaseView } from './api';
import type { PriceLine } from './components/ui/LiveChart';
import { readPalette } from './components/ui/LiveChart';

const MICRO = 1_000_000;

export const tradesOf = (timeline: LedgerEntry[]) => timeline.filter(entry => entry.kind === 'run.trade' || entry.kind === 'run.refused');

export const receiptsOf = (timeline: LedgerEntry[]) => timeline.filter(entry => entry.kind !== 'run.trade' && entry.kind !== 'run.refused');

export function thresholdLines(purchase: PurchaseView): PriceLine[] {
  const run = purchase.run;
  if (!run || purchase.mode !== 'hold') return [];
  const palette = readPalette();
  const start = run.start_cash_usd / MICRO;
  return [
    { price: start * (1 + purchase.threshold.min_return_bps / 10_000), label: 'Needs', seriesId: 'equity', color: palette.green },
    { price: (run.peak_equity_usd / MICRO) * (1 - purchase.threshold.max_loss_bps / 10_000), label: 'Loss limit', seriesId: 'equity', color: palette.orange },
  ];
}
