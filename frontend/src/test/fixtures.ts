import type { Info, Listing, Run, SellerRecord } from '../api';

export const record: SellerRecord = {
  runs: 8, alive: 0, ended: 8, survived: 6, loss_limit: 2, stopped: 0, survival_rate: 0.75,
  avg_return_bps: 40, worst_return_bps: -290, best_return_bps: 180, total_trades: 120, total_refusals: 3,
  practice_runs: 6, probation_runs: 2, probation_passed: 2, probation_failed: 0,
};

export const listing: Listing = {
  id: 'l_abc1234567',
  title: 'Momentum Mule',
  pitch: 'Follows the trend and cuts losses fast.',
  seller: { id: 's_1', name: 'Ada Seller', verified: true },
  rules: { strategy: 'momentum', brain: 'gemini:gemini-3.5-flash-lite', start_cash_usd: 1_000_000_000, max_trade_usd: 250_000_000, max_loss_bps: 300, lease_seconds: 600 },
  fingerprint: '0xabc',
  price_cents: 2500,
  probation_s: 600,
  min_return_bps: -100,
  active: true,
  created_at: 1_700_000_000,
  seller_record: record,
  stats: { purchases: 3, passed: 2, failed: 1, held_cents: 0, paid_out_cents: 4500 },
};

export const mockInfo: Info = {
  paypal_mode: 'mock', paypal_client_id: '', currency: 'USD', platform_fee_bps: 1000, price_source: 'sim', eth_price_usd: 3000,
  strategies: [{ id: 'momentum', text: 'Follow the trend.' }], brains: [{ brain: 'rule', available: true }], analyst: 'rules',
  ledger_head: { seq: 10, hash: 'a'.repeat(64) },
};

export const run: Run = {
  id: 7, seller_id: 's_1', listing_id: listing.id, purchase_id: 'p_1', purpose: 'probation', name: 'bot', fingerprint: '0xabc',
  status: 'alive', cause: null, start_cash_usd: 1_000_000_000, peak_equity_usd: 1_010_000_000, final_equity_usd: null,
  started_at: 1_700_000_000, expires_at: 1_700_000_600, ended_at: null, trades: 2, refusals: 0, equity_usd: 1_005_000_000,
  pnl_bps: 50, drawdown_bps: 10, seconds_left: 300, rules: listing.rules,
};
