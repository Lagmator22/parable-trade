import { headersFor, loadAiSettings, type AiSettings } from './aiSettings';
import type {
  Agent, AgentSummary, BacktestResult, Benchmark, BoughtAgent, Candles, CompileRequest, CompileResponse, DataRequest,
  Dataset, Diligence, Info, Job, LedgerEntry, ListingDetail, Me, Models, NewListingPayload, NewPurchase,
  PublicListing, PurchaseSummary, PurchaseView, Quote, Question, Recommendation, RerunResult, Run, RunPoints, SaleSummary,
  SellerProfile, Stats, StoredBacktest, StrategySpec, SymbolInfo, TamperResult, TestDriveResult, UploadResult, Validation,
  VerifyResult, Version, Webhook,
} from './apiTypes';

export * from './apiTypes';

type Headers = Record<string, string>;

export class ApiError extends Error {
  status: number;
  code: string;
  payload: Record<string, unknown>;
  constructor(status: number, message: string, code = '', payload: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
  get errors(): string[] {
    const list = this.payload.errors;
    return Array.isArray(list) ? list.map(String) : [];
  }
}

export function aiHeaders(settings: AiSettings = loadAiSettings()): Headers {
  return headersFor(settings);
}

function errorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) return String((detail[0] as { msg?: string }).msg ?? `Request failed (${status})`);
  return `Request failed (${status})`;
}

async function read<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: unknown = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = null; }
  if (!response.ok) {
    const body = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
    throw new ApiError(response.status, errorMessage(payload, response.status), typeof body.code === 'string' ? body.code : '', body);
  }
  return payload as T;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, { credentials: 'same-origin', ...init });
  } catch {
    throw new ApiError(0, 'Network error. Check your connection and try again.', 'network');
  }
}

export async function request<T>(method: string, path: string, body?: unknown, headers: Headers = {}): Promise<T> {
  const response = await send(path, {
    method,
    headers: body === undefined ? headers : { 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return read<T>(response);
}

export const get = <T,>(path: string, headers?: Headers) => request<T>('GET', path, undefined, headers);
export const post = <T,>(path: string, body: unknown = {}, headers?: Headers) => request<T>('POST', path, body, headers);
export const del = <T,>(path: string) => request<T>('DELETE', path);

const qs = (params: Record<string, string | number | undefined | null>) => {
  const parts = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
};

export const fetchInfo = () => get<Info>('/api/info');
export const fetchMe = () => get<Me>('/api/me');
export const fetchStats = () => get<Stats>('/api/stats');
export const fetchPopular = (kind: string) => get<SymbolInfo[]>(`/api/markets/popular${qs({ kind })}`);
export const searchSymbols = (q: string, kind = 'all') => get<SymbolInfo[]>(`/api/markets/search${qs({ q, kind })}`);
export const fetchCandles = (symbol: string, interval: string, limit = 500, start?: number, end?: number) =>
  get<Candles>(`/api/markets/candles${qs({ symbol, interval, limit, start, end })}`);
export const fetchTemplate = (id: string, symbol: string, interval: string) =>
  get<CompileResponse>(`/api/lab/templates/${encodeURIComponent(id)}${qs({ symbol, interval })}`);
export const fetchQuote = (symbol: string) => get<Quote>(`/api/markets/latest${qs({ symbol })}`);

export async function uploadDataset(file: File, name?: string, quote?: string): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  if (name) form.append('name', name);
  if (quote) form.append('quote', quote);
  return read<UploadResult>(await send('/api/datasets', { method: 'POST', body: form }));
}
export const aiMapDataset = (draft_id: string) =>
  post<{ mapping: Record<string, string>; by: string }>('/api/datasets/ai-map', { draft_id }, aiHeaders());
export const mapDataset = (draft_id: string, mapping: Record<string, string>, name?: string, quote?: string) =>
  post<{ status: 'ready'; dataset: Dataset }>('/api/datasets/map', { draft_id, mapping, name, quote });
export const fetchDatasets = () => get<Dataset[]>('/api/datasets');
export const deleteDataset = (id: string) => del<{ ok: boolean }>(`/api/datasets/${id}`);

export const fetchModels = (settings?: AiSettings) => get<Models>('/api/ai/models', aiHeaders(settings));
export const fetchQuestions = () => get<{ questions: Question[] }>('/api/ai/questionnaire').then(r => r.questions);
export const compileSteps = (req: CompileRequest) => post<CompileResponse>('/api/ai/compile', req, aiHeaders());
export const aiIdeas = (spec: StrategySpec, steps: string, model?: string) =>
  post<{ ideas: CompileResponse[]; free_tries: Models['free_tries'] }>('/api/ai/ideas', { spec, steps, model }, aiHeaders());
export const validateSpec = (spec: StrategySpec) => post<Validation>('/api/lab/validate', { spec });
export const labBacktest = (spec: StrategySpec, data: DataRequest) => post<BacktestResult>('/api/lab/backtest', { ...data, spec });
export const labOptimize = (spec: StrategySpec, data: DataRequest, top_k?: number) =>
  post<{ job_id: string }>('/api/lab/optimize', { ...data, spec, top_k });
export const fetchJob = <T,>(id: string) => get<Job<T>>(`/api/jobs/${id}`);

export async function pollJob<T>(id: string, onProgress: (job: Job<T>) => void = () => undefined, every = 1000): Promise<T> {
  for (;;) {
    const job = await fetchJob<T>(id);
    onProgress(job);
    if (job.status === 'done') return job.result as T;
    if (job.status === 'error') throw new ApiError(500, job.error || 'Job failed', 'job_failed');
    await new Promise(resolve => setTimeout(resolve, every));
  }
}

export const fetchAgents = () => get<AgentSummary[]>('/api/agents');
export const createAgent = (name: string, symbol: string, interval: string) => post<Agent>('/api/agents', { name, symbol, interval });
export const fetchAgent = (id: string) => get<Agent>(`/api/agents/${id}`);
export const deleteAgent = (id: string) => del<{ ok: boolean }>(`/api/agents/${id}`);
export const saveVersion = (agent_id: string, spec: StrategySpec, steps_text = '', built_by?: string) =>
  post<Version>(`/api/agents/${agent_id}/versions`, { spec, steps_text, built_by });
export const fetchVersion = (agent_id: string, version_id: string) => get<Version>(`/api/agents/${agent_id}/versions/${version_id}`);
export const backtestVersion = (agent_id: string, version_id: string, data: DataRequest) =>
  post<StoredBacktest>(`/api/agents/${agent_id}/versions/${version_id}/backtest`, data);
export const runVersion = (agent_id: string, version_id: string, opts: { start_cash?: number; max_loss_bps?: number; lease_seconds?: number } = {}) =>
  post<Run>(`/api/agents/${agent_id}/versions/${version_id}/run`, opts);
export const startBenchmark = (agent_id: string, body: { steps?: string; models: string[]; symbol?: string; interval?: string; dataset_id?: string; start?: number; end?: number }) =>
  post<{ job_id: string }>(`/api/agents/${agent_id}/benchmark`, body, aiHeaders());
export const fetchBenchmark = (id: string) => get<Benchmark>(`/api/benchmarks/${id}`);
export const adoptBenchmark = (id: string, model: string) => post<Version>(`/api/benchmarks/${id}/adopt`, { model });
export const fetchProof = (id: string) => get<StoredBacktest>(`/api/proofs/${id}`);

export const fetchListings = (query?: { kind?: string; mode?: string; sort?: string }) =>
  get<PublicListing[]>(`/api/listings${qs({ kind: query?.kind, mode: query?.mode, sort: query?.sort })}`);
export const fetchListing = (id: string) => get<ListingDetail>(`/api/listings/${id}`);
export const createListing = (payload: NewListingPayload) => post<ListingDetail>('/api/listings', payload);
export const pauseListing = (id: string) => post<ListingDetail>(`/api/listings/${id}/pause`);
export const resumeListing = (id: string) => post<ListingDetail>(`/api/listings/${id}/resume`);
export const attachBenchmark = (listing_id: string, benchmark_id: string) => post<ListingDetail>(`/api/listings/${listing_id}/benchmark`, { benchmark_id });
export const rerunProof = (listing_id: string, refetch = false) => post<RerunResult>(`/api/listings/${listing_id}/rerun`, { refetch });
export const testDrive = (listing_id: string, body: { symbol?: string; interval?: string; start?: number; end?: number } = {}) =>
  post<TestDriveResult>(`/api/listings/${listing_id}/test-drive`, body);
export const fetchDiligence = (id: string) => get<Diligence>(`/api/listings/${id}/diligence`);
export const askShopper = (query: string, budget_cents?: number) => post<Recommendation>('/api/shopper', { query, budget_cents });

export const startPurchase = (listing_id: string) => post<NewPurchase>('/api/purchases', { listing_id });
export const approvePurchase = (id: string, order_id: string) => post<PurchaseView>(`/api/purchases/${id}/approve`, { order_id });
export const retryPurchase = (id: string) => post<PurchaseView>(`/api/purchases/${id}/retry`);
export const fetchPurchase = (id: string) => get<PurchaseView>(`/api/purchases/${id}`);
export async function downloadLicense(id: string): Promise<Blob> {
  const response = await send(`/api/purchases/${id}/license`, { method: 'GET' });
  if (!response.ok) return read<Blob>(response);
  return response.blob();
}
export const runPurchase = (id: string, opts: { start_cash?: number; max_loss_bps?: number; lease_seconds?: number } = {}) =>
  post<Run>(`/api/purchases/${id}/run`, opts);

export const fetchMyAgents = () => get<{ built: AgentSummary[]; bought: BoughtAgent[] }>('/api/me/agents');
export const fetchMyPurchases = () => get<PurchaseSummary[]>('/api/me/purchases');
export const fetchMySales = () => get<SaleSummary[]>('/api/me/sales');
export const fetchRunPoints = (run_id: number, since = 0) => get<RunPoints>(`/api/runs/${run_id}/points${qs({ since })}`);

export const stopRun = (id: number) => post<Run>(`/api/runs/${id}/stop`);
export const fetchSeller = (id: string) => get<SellerProfile>(`/api/sellers/${id}`);
export const fetchRuns = (query: string) => get<Run[]>(`/api/runs?${query}`);
export const fetchLedger = (limit: number, kind?: string) => get<LedgerEntry[]>(`/api/ledger?limit=${limit}${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`);
export const verifyLedger = () => get<VerifyResult>('/api/ledger/verify');
export const tamperDemo = () => post<TamperResult>('/api/ledger/tamper-demo');
export const fetchWebhooks = () => get<Webhook[]>('/api/webhooks/recent');
export const logout = () => post<unknown>('/api/logout');
