export type PaypalMode = 'sandbox' | 'live' | 'mock';
export type RunCause = 'expired' | 'loss_limit' | 'stopped';
export type RunPurpose = 'practice' | 'probation' | 'track';
export type RiskLevel = 'low' | 'medium' | 'high';
export type SaleMode = 'hold' | 'instant';
export type SourceKind = 'market' | 'sample' | 'creator';
export type AssetKind = 'crypto' | 'stocks' | 'funds' | 'forex' | 'gold' | 'mine';
export type ProofKind = 'backtest' | 'rerun' | 'testdrive' | 'benchmark';
export type Bar = [number, number, number, number, number, number];

export type PurchaseStatus =
  | 'created' | 'authorized' | 'probation' | 'passed' | 'failed'
  | 'captured' | 'paid_out' | 'voided' | 'cancelled' | 'error';

export type Param = { value: number; min: number; max: number; step: number };
export type StrategySpec = {
  name: string; summary: string; symbol: string; interval: string; built_by: string;
  params: Record<string, Param>; entry: string; exit: string;
  size_pct: number; stop_loss_pct: number; take_profit_pct: number; trailing_stop_pct: number;
  fee_bps: number; slippage_bps: number;
};
export type RuleChip = { kind: 'entry' | 'exit' | 'risk' | 'size'; text: string };
export type SymbolInfo = { symbol: string; name: string; kind: AssetKind; quote: string; provider: string; intervals: string[]; live: boolean };
export type Quote = { symbol: string; price: number; t: number; quote: string; stale: boolean };
export type Candles = { symbol: string; interval: string; quote: string; source_kind: SourceKind; bars: Bar[]; data_hash: string };
export type DataInfo = { symbol: string; interval: string; start: number; end: number; bars: number; data_hash: string; source_kind: SourceKind; quote: string };
export type DataRequest = { symbol?: string; interval?: string; dataset_id?: string; start?: number; end?: number; limit?: number };
export type Dataset = { id: string; symbol: string; name: string; interval: string; quote: string; bars: number; start: number; end: number; data_hash: string; created_at: number };
export type UploadResult =
  | { status: 'ready'; dataset: Dataset }
  | { status: 'needs_mapping'; draft_id: string; columns: string[]; preview: string[][]; suggestion: Record<string, string> | null };

export type Metrics = {
  total_return_pct: number; benchmark_return_pct: number; excess_return_pct: number; cagr_pct: number | null;
  max_drawdown_pct: number; volatility_pct: number; sharpe: number; sortino: number; trades: number;
  win_rate_pct: number; profit_factor: number | null; avg_win_pct: number; avg_loss_pct: number;
  best_trade_pct: number; worst_trade_pct: number; exposure_pct: number; avg_hold_bars: number;
  avg_hold_s: number; fees_paid: number; start_cash: number; final_equity: number;
};
export type CurvePoint = [number, number, number];
export type Trade = { entry_t: number; exit_t: number; entry_price: number; exit_price: number; qty: number; pnl: number; return_pct: number; bars_held: number; fees: number; reason: 'signal' | 'stop' | 'take_profit' | 'trailing' | 'end' };
export type Marker = { t: number; side: 'buy' | 'sell'; price: number; text: string };
export type BacktestResult = { metrics: Metrics; curve: CurvePoint[]; trades: Trade[]; markers: Marker[]; data: DataInfo; quote: string; start_cash: number; spec_hash: string; engine_version: string; result_hash: string };
export type ProofView = {
  id: string; kind: ProofKind; spec_hash: string; symbol: string; interval: string; data: DataInfo; metrics: Metrics;
  curve: CurvePoint[]; trades_count: number; engine_version: string; result_hash: string; ledger_seq: number | null;
  matched: boolean | null; by: 'seller' | 'buyer' | 'visitor'; created_at: number;
  trades?: Trade[]; markers?: Marker[]; version_id?: string;
};
export type StoredBacktest = ProofView & { trades: Trade[]; markers: Marker[] };
export type OptimizeRow = { params: Record<string, number>; train: Metrics; test: Metrics; overfit: boolean };
export type OptimizeResult = { rows: OptimizeRow[]; grid_size: number; evaluated: number; train_bars: number; test_bars: number; base: { train: Metrics; test: Metrics } };
export type Job<T = unknown> = { id: string; kind: string; status: 'queued' | 'running' | 'done' | 'error'; progress: number; message: string; result: T | null; error: string | null; created_at: number };
export type FreeTries = { limit: number; used: number; remaining: number };
export type ModelInfo = { id: string; provider: string; model: string; label: string; available: boolean; free: boolean };
export type Models = { platform: ModelInfo[]; own: ModelInfo[]; free_tries: FreeTries; key_ok?: boolean | null };
export type Question = { id: string; text: string; options: { id: string; label: string }[] };
export type CompileRequest = { steps?: string; symbol: string; interval: string; model?: string; answers?: Record<string, string>; base?: StrategySpec };
export type CompileResponse = { spec: StrategySpec; summary: string; rules: RuleChip[]; built_by: string; attempts: number; free_tries: FreeTries };
export type Template = { id: string; label: string; blurb: string; family: string };
export type Validation = { ok: boolean; errors: string[]; spec_hash: string; rules: RuleChip[] };
export type AgentSummary = { id: string; name: string; symbol: string; interval: string; status: 'draft' | 'listed'; latest_version_id: string | null; listing_id: string | null; updated_at: number; headline: Partial<Metrics> | null };
export type VersionSummary = { id: string; n: number; name: string; spec_hash: string; built_by: string; created_at: number };
export type Version = VersionSummary & { agent_id: string; summary: string; steps_text: string; spec: StrategySpec };
export type Agent = AgentSummary & { versions: VersionSummary[] };
export type BenchmarkRow = { model: string; ok: boolean; error: string | null; summary: string; metrics: Metrics | null; curve: CurvePoint[]; spec_hash: string | null; built_by: string | null; rules: RuleChip[]; spec?: StrategySpec };
export type Benchmark = { id: string; agent_id: string; data: DataInfo; buy_and_hold: { metrics: { total_return_pct: number; max_drawdown_pct: number }; curve: [number, number][] }; rows: BenchmarkRow[] };
export type BenchmarkPublic = Omit<Benchmark, 'rows'> & { rows: Pick<BenchmarkRow, 'model' | 'ok' | 'metrics' | 'curve' | 'spec_hash'>[] };
export type Headline = Pick<Metrics, 'total_return_pct' | 'benchmark_return_pct' | 'max_drawdown_pct' | 'sharpe' | 'win_rate_pct' | 'trades'>;
export type Track = { run_id: number; status: 'alive' | 'dead'; since: number; seconds: number; equity_pct: number; start_equity: number; equity: number; price: number | null; points: number; runs_total: number; runs_ended_early: number; quote: string };

export type SellerRecord = {
  runs: number; alive: number; ended: number; survived: number; loss_limit: number; stopped: number;
  survival_rate: number; avg_return_bps: number; worst_return_bps: number; best_return_bps: number;
  total_trades: number; total_refusals: number; practice_runs: number; probation_runs: number;
  probation_passed: number; probation_failed: number; track_runs?: number; track_ended_early?: number;
};
export type ListingStats = { purchases: number; passed: number; failed: number; held_cents: number; paid_out_cents: number };
export type PublicListing = {
  id: string; title: string; pitch: string; price_cents: number; mode: SaleMode; trial_s: number;
  min_return_bps: number; max_loss_bps: number; allow_test_drive: boolean; symbol: string; interval: string;
  quote: string; kind: AssetKind; active: boolean; created_at: number; built_by: string; spec_hash: string;
  headline: Headline; sparkline: CurvePoint[]; data: DataInfo; proof_id: string; track: Track | null;
  reruns: { count: number; matched: number }; seller: { id: string; name: string; verified: boolean };
  seller_record: SellerRecord; stats: ListingStats;
};
export type ListingDetail = PublicListing & { proof: ProofView; benchmark: BenchmarkPublic | null; proofs: ProofView[]; recent_runs: Run[] };
export type NewListingPayload = { version_id: string; title: string; pitch: string; price_cents: number; mode: SaleMode; trial_s: number; min_return_bps: number; max_loss_bps: number; proof_id: string; allow_test_drive: boolean };
export type RerunResult = { match: boolean; claim: ProofView; rerun: ProofView; diff: Record<string, { claim: number | null; rerun: number | null }>; data_hash_match: boolean | null; refetched: boolean };
export type TestDriveResult = { proof: ProofView; claim: ProofView };
export type RunPoints = { run_id: number; quote: string; start_cash: number; points: [number, number, number][] };

export type Run = {
  id: number; seller_id: string; listing_id: string | null; purchase_id: string | null; purpose: RunPurpose; name: string;
  status: 'alive' | 'dead'; cause: RunCause | null; spec_hash?: string | null; symbol?: string | null;
  interval?: string | null; quote?: string | null; units?: number;
  start_cash_usd: number; peak_equity_usd: number; final_equity_usd: number | null; equity_usd: number;
  pnl_bps: number; drawdown_bps: number; started_at: number; expires_at: number; ended_at: number | null;
  trades: number; refusals: number; seconds_left: number; lifetime_s?: number;
};

export type LedgerEntry = { seq: number; at: number; kind: string; subject: string; data: Record<string, unknown>; prev_hash: string; hash: string };
export type Verdict = { passed: boolean; cause: RunCause | string; return_bps: number; min_return_bps: number; lifetime_s: number; trades: number; refusals: number; explanation: string };

export type License = {
  key: string; format: 'parable-agent'; engine_version: string; spec_hash: string; spec: StrategySpec;
  steps_text: string; proof_id: string; run_hint: string;
};
export type PurchaseView = {
  id: string; status: PurchaseStatus; mode: SaleMode; listing: PublicListing; amount_cents: number; fee_cents: number;
  payout_cents: number; paypal_order_id: string; paypal_authorization_id: string; paypal_capture_id: string;
  paypal_payout_batch_id: string; payout_status: string; threshold: { min_return_bps: number; max_loss_bps: number };
  run: Run | null; verdict: Verdict | null; timeline: LedgerEntry[]; error: string; created_at: number; updated_at: number;
  license: License | null;
};
export type PurchaseSummary = { id: string; status: PurchaseStatus; mode: SaleMode; listing_id: string; title: string; amount_cents: number; created_at: number };
export type BoughtAgent = { purchase_id: string; listing_id: string; title: string; mode: SaleMode; status: PurchaseStatus; spec_hash: string; symbol: string; interval: string; entitled: boolean };
export type SaleSummary = { listing_id: string; title: string; mode: SaleMode; purchases: number; captured_cents: number; paid_out_cents: number };
export type Me = { seller: { id: string; name: string; verified: boolean; email_masked: string } | null; paypal_mode: PaypalMode; free_tries?: FreeTries };

export type Limits = Record<string, number>;
export type InfoV2 = { kinds?: AssetKind[]; intervals?: string[]; templates?: Template[]; limits?: Limits; ai?: { free_tries_per_day: number } };
export type Info = InfoV2 & {
  paypal_mode: PaypalMode; paypal_client_id: string; currency: string; platform_fee_bps: number; price_source: string;
  analyst: string; ledger_head: { seq: number; hash: string };
};
export type Stats = {
  listings: number; sellers: number; runs_alive: number; probations_running: number; passed: number; failed: number;
  held_cents: number; captured_cents: number; voided_cents: number; paid_out_cents: number;
  ledger_head: { seq: number; hash: string } | string; agents?: number; proofs?: number; reruns?: number;
};

export type Diligence = { risk: RiskLevel; headline: string; findings: string[]; red_flags: string[]; facts: Record<string, unknown>; by: string };
export type Recommendation = { listing_id: string | null; reason: string; alternatives: string[]; by: string };
export type NewPurchase = { purchase_id: string; paypal_order_id: string; approve_url: string };
export type VerifyResult = { ok: boolean; checked: number; first_bad_seq: number | null; head: string };
export type TamperResult = { edited_seq: number; before: unknown; after: unknown; verify: VerifyResult };
export type Webhook = { event_type: string; verified: boolean | number; resource_id: string; received_at: number };
export type SellerProfile = { seller?: { id: string; name: string; verified: boolean }; id?: string; name?: string; verified?: boolean; record: SellerRecord; runs: Run[]; listings?: PublicListing[] };
