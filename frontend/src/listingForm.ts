import type { ListingPayload } from './api';

export type FormState = {
  title: string;
  pitch: string;
  strategy: string;
  brain: string;
  price: string;
  probationMinutes: string;
  lossLimitPercent: string;
  minReturnPercent: string;
  maxTrade: string;
};

export type Built = { ok: true; payload: ListingPayload } | { ok: false; error: string };

export const emptyForm = (strategy = 'momentum', brain = 'rule'): FormState => ({
  title: '', pitch: '', strategy, brain, price: '25', probationMinutes: '10', lossLimitPercent: '3', minReturnPercent: '-1', maxTrade: '250',
});

type Range = { label: string; min: number; max: number };

function inRange(raw: string, { label, min, max }: Range): number | string {
  const value = Number(raw);
  if (!raw.trim() || !Number.isFinite(value)) return `${label} must be a number.`;
  if (value < min || value > max) return `${label} must be between ${min} and ${max}.`;
  return value;
}

export function buildPayload(form: FormState): Built {
  const title = form.title.trim();
  const pitch = form.pitch.trim();
  if (title.length < 3 || title.length > 80) return { ok: false, error: 'Title must be 3 to 80 characters.' };
  if (pitch.length < 10 || pitch.length > 500) return { ok: false, error: 'Pitch must be 10 to 500 characters.' };
  const price = inRange(form.price, { label: 'Price (USD)', min: 1, max: 500 });
  const minutes = inRange(form.probationMinutes, { label: 'Probation (minutes)', min: 1, max: 4320 });
  const loss = inRange(form.lossLimitPercent, { label: 'Loss limit (%)', min: 0.5, max: 20 });
  const minReturn = inRange(form.minReturnPercent, { label: 'Minimum return (%)', min: -5, max: 5 });
  const maxTrade = inRange(form.maxTrade, { label: 'Max trade (USD)', min: 10, max: 1000 });
  const failure = [price, minutes, loss, minReturn, maxTrade].find(value => typeof value === 'string');
  if (typeof failure === 'string') return { ok: false, error: failure };
  return {
    ok: true,
    payload: {
      title,
      pitch,
      strategy: form.strategy,
      brain: form.brain,
      max_trade_usd: Math.round((maxTrade as number) * 1_000_000),
      max_loss_bps: Math.round((loss as number) * 100),
      price_cents: Math.round((price as number) * 100),
      probation_s: Math.round((minutes as number) * 60),
      min_return_bps: Math.round((minReturn as number) * 100),
    },
  };
}
