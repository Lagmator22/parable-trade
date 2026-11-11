import type { PurchaseStatus, SaleMode } from './api';

export type StepState = 'done' | 'now' | 'todo' | 'bad';
export type Step = { label: string; state: StepState };

const DONE_COUNT: Record<PurchaseStatus, number> = {
  created: 1,
  authorized: 2,
  probation: 2,
  passed: 4,
  failed: 4,
  captured: 4,
  paid_out: 5,
  voided: 5,
  cancelled: 1,
  error: 4,
};

export const STATUS_LABEL: Record<PurchaseStatus, string> = {
  created: 'Waiting for PayPal approval',
  authorized: 'Payment held',
  probation: 'Trial running',
  passed: 'Passed, capturing payment',
  failed: 'Failed, releasing hold',
  captured: 'Captured, paying seller',
  paid_out: 'Paid out',
  voided: 'Voided, never charged',
  cancelled: 'Cancelled',
  error: 'Needs a retry',
};

export const passedOf = (status: PurchaseStatus): boolean | null => {
  if (status === 'passed' || status === 'captured' || status === 'paid_out') return true;
  if (status === 'failed' || status === 'voided') return false;
  return null;
};

function finalLabel(passed: boolean | null): string {
  if (passed === true) return 'Captured and paid out';
  if (passed === false) return 'Voided, never charged';
  return 'Settlement';
}

function stateAt(index: number, status: PurchaseStatus): StepState {
  const done = DONE_COUNT[status];
  const failedVerdict = passedOf(status) === false;
  if (index < done) return failedVerdict && index >= 3 ? 'bad' : 'done';
  if (index > done) return 'todo';
  return status === 'error' || status === 'cancelled' ? 'bad' : 'now';
}

const INSTANT_LABELS = ['Order created', 'Payment captured', 'Seller paid out'];

function instantSteps(status: PurchaseStatus, captured: boolean): Step[] {
  const done = status === 'paid_out' ? 3 : status === 'captured' ? 2 : status === 'error' ? (captured ? 2 : 1) : 1;
  return INSTANT_LABELS.map((label, index) => ({
    label,
    state: index < done ? 'done' : index > done ? 'todo' : status === 'error' || status === 'cancelled' ? 'bad' : 'now',
  }));
}

export function buildSteps(status: PurchaseStatus, mode: SaleMode = 'hold', captured = false): Step[] {
  if (mode === 'instant') return instantSteps(status, captured);
  const passed = passedOf(status);
  const verdict = passed === null ? 'Verdict' : passed ? 'Verdict: passed' : 'Verdict: failed';
  const labels = ['Order created', 'Payment authorized (held)', 'Trial running', verdict, finalLabel(passed)];
  return labels.map((label, index) => ({ label, state: stateAt(index, status) }));
}

export type StampInfo = { text: string; tone: 'good' | 'bad' };

export function stampOf(status: PurchaseStatus): StampInfo | null {
  if (status === 'paid_out' || status === 'captured') return { text: 'PAID', tone: 'good' };
  if (status === 'passed') return { text: 'PASSED', tone: 'good' };
  if (status === 'voided') return { text: 'VOIDED', tone: 'bad' };
  if (status === 'failed') return { text: 'FAILED', tone: 'bad' };
  return null;
}

export const isSettled = (status: PurchaseStatus) => status === 'paid_out' || status === 'voided' || status === 'cancelled';

export const KIND_LABEL: Record<string, string> = {
  'purchase.created': 'Order created',
  'purchase.authorized': 'Payment authorized and held',
  'purchase.probation_started': 'Probation started',
  'purchase.passed': 'Verdict: passed',
  'purchase.failed': 'Verdict: failed',
  'payment.captured': 'Payment captured',
  'payment.voided': 'Authorization voided',
  'payout.sent': 'Seller payout sent',
  'payout.updated': 'Payout updated',
  'run.started': 'Bot run started',
  'run.ended': 'Bot run ended',
  'run.trade': 'Trade',
  'run.refused': 'Trade refused',
  'webhook.received': 'PayPal webhook received',
  'seller.joined': 'Seller joined',
  'listing.created': 'Listing created',
  'listing.paused': 'Listing paused',
  'proof.stored': 'Proof stored',
  'purchase.cancelled': 'Purchase cancelled',
};

export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind;
