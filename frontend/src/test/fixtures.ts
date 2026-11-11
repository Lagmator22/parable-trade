import type { Info, LedgerEntry, Metrics, ProofView, PublicListing, PurchaseView, Run, SellerRecord } from '../api';

export const record: SellerRecord = {
  runs: 8, alive: 0, ended: 8, survived: 6, loss_limit: 2, stopped: 0, survival_rate: 0.75,
  avg_return_bps: 40, worst_return_bps: -290, best_return_bps: 180, total_trades: 120, total_refusals: 3,
  practice_runs: 6, probation_runs: 2, probation_passed: 2, probation_failed: 0,
};

export const metrics: Metrics = {
  total_return_pct: 12.5, benchmark_return_pct: 4, excess_return_pct: 8.5, cagr_pct: null, max_drawdown_pct: 6, volatility_pct: 20, sharpe: 1.1,
  sortino: 1.4, trades: 7, win_rate_pct: 57, profit_factor: 1.8, avg_win_pct: 3, avg_loss_pct: -1.5, best_trade_pct: 6, worst_trade_pct: -3,
  exposure_pct: 40, avg_hold_bars: 5, avg_hold_s: 18000, fees_paid: 12, start_cash: 10000, final_equity: 11250,
};

export const data = { symbol: 'binance:BTCUSDT', interval: '1h', start: 1_700_000_000, end: 1_700_360_000, bars: 100, data_hash: 'd'.repeat(64), source_kind: 'market' as const, quote: 'USDT' };

export const proof: ProofView = {
  id: 'pf_1', kind: 'backtest', spec_hash: 's'.repeat(64), symbol: data.symbol, interval: '1h', data, metrics,
  curve: [[1_700_000_000, 10000, 10000], [1_700_003_600, 10500, 10100], [1_700_007_200, 11250, 10400]], trades_count: 7,
  engine_version: 'lab-1', result_hash: 'a'.repeat(64), ledger_seq: 4, matched: null, by: 'seller', created_at: 1_700_000_000,
};

export const listing: PublicListing = {
  id: 'l_abc1234567', title: 'Momentum Mule', pitch: 'Follows the trend and cuts losses fast.',
  price_cents: 2500, mode: 'hold', trial_s: 600, min_return_bps: -100, max_loss_bps: 300, allow_test_drive: true,
  symbol: data.symbol, interval: '1h', quote: 'USDT', kind: 'crypto', active: true, created_at: 1_700_000_000,
  built_by: 'gemini:gemini-3.5-flash-lite', spec_hash: proof.spec_hash,
  headline: { total_return_pct: 12.5, benchmark_return_pct: 4, max_drawdown_pct: 6, sharpe: 1.1, win_rate_pct: 57, trades: 7 },
  sparkline: proof.curve, data, proof_id: proof.id,
  track: { run_id: 9, status: 'alive', since: 1_700_000_000, seconds: 7200, equity_pct: 1.2, start_equity: 1000, equity: 1012, price: 42000, points: 5, runs_total: 2, runs_ended_early: 1, quote: 'USDT' },
  reruns: { count: 3, matched: 3 }, seller: { id: 's_1', name: 'Ada Seller', verified: true }, seller_record: record,
  stats: { purchases: 3, passed: 2, failed: 1, held_cents: 0, paid_out_cents: 4500 },
};

export const instantListing: PublicListing = { ...listing, id: 'l_instant0001', mode: 'instant', title: 'Instant Fox', track: null };

export const mockInfo: Info = {
  paypal_mode: 'mock', paypal_client_id: '', currency: 'USD', platform_fee_bps: 1000, price_source: 'sim', analyst: 'rules',
  ledger_head: { seq: 10, hash: 'a'.repeat(64) },
};

export const run: Run = {
  id: 7, seller_id: 's_1', listing_id: listing.id, purchase_id: 'p_1', purpose: 'probation', name: 'bot',
  status: 'alive', cause: null, quote: 'USDT', start_cash_usd: 1_000_000_000, peak_equity_usd: 1_010_000_000, final_equity_usd: null,
  started_at: 1_700_000_000, expires_at: 1_700_000_600, ended_at: null, trades: 2, refusals: 0, equity_usd: 1_005_000_000,
  pnl_bps: 50, drawdown_bps: 10, seconds_left: 300, lifetime_s: 600,
};

export const entry = (seq: number, kind: string, extra: Record<string, unknown> = {}): LedgerEntry =>
  ({ seq, at: 1_700_000_100 + seq, kind, subject: 'purchase:p_1', data: extra, prev_hash: '', hash: 'f'.repeat(64) });

export const purchase = (over: Partial<PurchaseView> = {}): PurchaseView => ({
  id: 'p_1', status: 'probation', mode: 'hold', listing, amount_cents: 2500, fee_cents: 250, payout_cents: 2250,
  paypal_order_id: '…ORDER1', paypal_authorization_id: '…AUTH12', paypal_capture_id: '', paypal_payout_batch_id: '', payout_status: '',
  threshold: { min_return_bps: -100, max_loss_bps: 300 }, run, verdict: null, timeline: [entry(1, 'purchase.created')], error: '',
  created_at: 1_700_000_000, updated_at: 1_700_000_050, license: null, ...over,
});

export const license = {
  key: 'PARABLE-AAAA-BBBB', format: 'parable-agent' as const, engine_version: 'lab-1', spec_hash: 's'.repeat(64), spec: {} as never,
  steps_text: '', proof_id: 'pf_1', run_hint: 'Run it on Parable from My agents.',
};
