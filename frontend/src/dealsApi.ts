import { aiHeaders, get, post, type FreeTries } from './api';

export type ChecklistKind = 'ai' | 'min_words' | 'must_include';

export type ChecklistItem = {
  id: string;
  text: string;
  kind: ChecklistKind;
  value: string | number | null;
};

export type VerdictItem = {
  id: string;
  text: string;
  pass: boolean;
  reason: string;
};

export type Verdict = {
  passed: boolean;
  items: VerdictItem[];
  summary: string;
};

export type DealEvent = {
  seq: number;
  at: number;
  kind: string;
  data: Record<string, unknown>;
  hash: string;
};

export type DealStatus = 'draft' | 'funded' | 'submitted' | 'released' | 'returned' | 'error';
export type DealRole = 'client' | 'freelancer' | 'visitor';

export type Deal = {
  id: string;
  title: string;
  status: DealStatus;
  amount_cents: number;
  fee_cents: number;
  payout_cents: number;
  checklist: ChecklistItem[];
  verdict: Verdict | null;
  attempts: number;
  attempts_left: number;
  built_by: string | null;
  created_at: number;
  updated_at: number;
  error: string | null;
  brief?: string;
  work_text?: string | null;
  work_url?: string | null;
  freelancer_email_masked?: string;
  payout_status?: string | null;
  share_token?: string;
  freelancer_email?: string;
  paypal_order_id?: string | null;
  timeline?: DealEvent[];
  role?: DealRole;
};

export type BuiltChecklist = {
  title: string;
  items: ChecklistItem[];
  built_by: string;
  free_tries?: FreeTries;
};

export type CreateDealInput = {
  title: string;
  brief: string;
  checklist: ChecklistItem[];
  amount_cents: number;
  freelancer_email: str_or_string;
  built_by?: string | null;
};

type str_or_string = string;

export type DealOrder = {
  paypal_order_id: string;
  approve_url: string;
  mock: boolean;
};

export const buildChecklist = (brief: string) =>
  post<BuiltChecklist>('/api/deals/checklist', { brief }, aiHeaders());

export const createDeal = (body: CreateDealInput) =>
  post<Deal>('/api/deals', body);

export const fetchDeals = () =>
  get<Deal[]>('/api/deals');

export const fetchDeal = (id: string, token?: string) =>
  get<Deal>(`/api/deals/${encodeURIComponent(id)}${token ? `?k=${encodeURIComponent(token)}` : ''}`);

export const orderDeal = (id: string) =>
  post<DealOrder>(`/api/deals/${encodeURIComponent(id)}/order`);

export const fundDeal = (id: string, orderId: string) =>
  post<Deal>(`/api/deals/${encodeURIComponent(id)}/fund`, { order_id: orderId });

export const submitWork = (id: string, token: string, text: string, url?: string) =>
  post<Deal>(`/api/deals/${encodeURIComponent(id)}/submit?k=${encodeURIComponent(token)}`, {
    work_text: text,
    work_url: url ? url : undefined,
  });

export const releaseDeal = (id: string) =>
  post<Deal>(`/api/deals/${encodeURIComponent(id)}/release`);

export const refundDeal = (id: string) =>
  post<Deal>(`/api/deals/${encodeURIComponent(id)}/refund`);
