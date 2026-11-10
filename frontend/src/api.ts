export type PaypalMode = 'sandbox' | 'live' | 'mock';
export type RunCause = 'expired' | 'loss_limit' | 'stopped';
export type RunPurpose = 'practice' | 'probation';
export type RiskLevel = 'low' | 'medium' | 'high';

export type PurchaseStatus =
  | 'created' | 'authorized' | 'probation' | 'passed' | 'failed'
  | 'captured' | 'paid_out' | 'voided' | 'cancelled' | 'error';

export type Rules = {
  strategy: string;
  brain: string;
  start_cash_usd: number;
  max_trade_usd: number;
  max_loss_bps: number;
  lease_seconds: number;
};

export type Info = {
  paypal_mode: PaypalMode;
  paypal_client_id: string;
  currency: string;
  platform_fee_bps: number;
  price_source: string;
  eth_price_usd: number;
  strategies: { id: string; text: string }[];
  brains: { brain: string; available: boolean }[];
  analyst: string;
  ledger_head: { seq: number; hash: string };
};

export type Stats = {
  listings: number;
  sellers: number;
  runs_alive: number;
  probations_running: number;
  passed: number;
  failed: number;
  held_cents: number;
  captured_cents: number;
  voided_cents: number;
  paid_out_cents: number;
  ledger_head: { seq: number; hash: string } | string;
};

export type Me = {
  seller: { id: string; name: string; verified: boolean; email_masked: string } | null;
  paypal_mode: PaypalMode;
};

export type SellerRecord = {
  runs: number;
  alive: number;
  ended: number;
  survived: number;
  loss_limit: number;
  stopped: number;
  survival_rate: number;
  avg_return_bps: number;
  worst_return_bps: number;
  best_return_bps: number;
  total_trades: number;
  total_refusals: number;
  practice_runs: number;
  probation_runs: number;
  probation_passed: number;
  probation_failed: number;
};

export type Listing = {
  id: string;
  title: string;
  pitch: string;
  seller: { id?: string; name: string; verified: boolean };
  seller_id?: string;
  rules: Rules;
  fingerprint: string;
  price_cents: number;
  probation_s: number;
  min_return_bps: number;
  active: boolean | number;
  created_at: number;
  seller_record: SellerRecord;
  stats: { purchases: number; passed: number; failed: number; held_cents: number; paid_out_cents: number };
};

export type Run = {
  id: number;
  seller_id: string;
  listing_id: string | null;
  purchase_id: string | null;
  purpose: RunPurpose;
  name: string;
  fingerprint: string;
  status: 'alive' | 'dead';
  cause: RunCause | null;
  start_cash_usd: number;
  peak_equity_usd: number;
  final_equity_usd: number | null;
  started_at: number;
  expires_at: number;
  ended_at: number | null;
  trades: number;
  refusals: number;
  equity_usd: number;
  pnl_bps: number;
  drawdown_bps: number;
  seconds_left: number;
  rules: Rules;
};

export type LedgerEntry = {
  seq: number;
  at: number;
  kind: string;
  subject: string;
  data: Record<string, unknown>;
  prev_hash: string;
  hash: string;
};

export type Verdict = {
  passed: boolean;
  cause: RunCause | string;
  return_bps: number;
  min_return_bps: number;
  lifetime_s: number;
  trades: number;
  refusals: number;
  explanation: string;
};

export type License = { key: string; bot: Rules; fingerprint: string; instructions: string };

export type Diligence = {
  risk: RiskLevel;
  headline: string;
  findings: string[];
  red_flags: string[];
  facts: Record<string, unknown>;
  by: string;
};

export type Recommendation = {
  listing_id: string | null;
  reason: string;
  alternatives: string[];
  by: string;
  listing?: Listing;
};

export type NewPurchase = { purchase_id: string; buyer_token: string; paypal_order_id: string; approve_url: string };

export type VerifyResult = { ok: boolean; checked: number; first_bad_seq: number | null; head: string };

export type TamperResult = { edited_seq: number; before: unknown; after: unknown; verify: VerifyResult };

export type Webhook = { event_type: string; verified: boolean | number; resource_id: string; received_at: number };

export type SellerProfile = {
  seller?: { id: string; name: string; verified: boolean };
  id?: string;
  name?: string;
  verified?: boolean;
  record: SellerRecord;
  runs: Run[];
  listings?: Listing[];
};

export type ListingPayload = {
  title: string;
  pitch: string;
  strategy: string;
  brain: string;
  max_trade_usd: number;
  max_loss_bps: number;
  price_cents: number;
  probation_s: number;
  min_return_bps: number;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? headers : { 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, errorMessage(payload, response.status));
  return payload as T;
}

function errorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) return String((detail[0] as { msg?: string }).msg ?? `Request failed (${status})`);
  return `Request failed (${status})`;
}

export const get = <T,>(path: string, headers?: Record<string, string>) => request<T>('GET', path, undefined, headers);
export const post = <T,>(path: string, body: unknown = {}) => request<T>('POST', path, body);

export const fetchInfo = () => get<Info>('/api/info');
export const fetchMe = () => get<Me>('/api/me');
export const fetchStats = () => get<Stats>('/api/stats');
export const fetchListings = () => get<Listing[]>('/api/listings');
export const fetchDiligence = (id: string) => get<Diligence>(`/api/listings/${id}/diligence`);
export const fetchPrices = () => get<{ points: [number, number][] }>('/api/prices');
export const askShopper = (query: string, budget_cents?: number) => post<Recommendation>('/api/shopper', { query, budget_cents });
export const startPurchase = (listing_id: string) => post<NewPurchase>('/api/purchases', { listing_id });
export const approvePurchase = (id: string, order_id: string) => post<unknown>(`/api/purchases/${id}/approve`, { order_id });
export const retryPurchase = (id: string) => post<unknown>(`/api/purchases/${id}/retry`);
export const fetchPurchase = (id: string, token?: string) => get<unknown>(`/api/purchases/${id}`, token ? { 'x-buyer-token': token } : undefined);
export const createListing = (payload: ListingPayload) => post<Listing>('/api/listings', payload);
export const pauseListing = (id: string) => post<unknown>(`/api/listings/${id}/pause`);
export const startPractice = (id: string) => post<Run>(`/api/listings/${id}/practice`);
export const stopRun = (id: number) => post<unknown>(`/api/runs/${id}/stop`);
export const fetchSeller = (id: string) => get<SellerProfile>(`/api/sellers/${id}`);
export const fetchRuns = (query: string) => get<Run[]>(`/api/runs?${query}`);
export const fetchLedger = (limit: number, kind?: string) => get<LedgerEntry[]>(`/api/ledger?limit=${limit}${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`);
export const verifyLedger = () => get<VerifyResult>('/api/ledger/verify');
export const tamperDemo = () => post<TamperResult>('/api/ledger/tamper-demo');
export const fetchWebhooks = () => get<Webhook[]>('/api/webhooks/recent');
export const logout = () => post<unknown>('/api/logout');
