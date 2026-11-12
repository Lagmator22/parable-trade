import { act } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Me } from '../../api';
import type { Deal } from '../../dealsApi';
import { mockInfo } from '../../test/fixtures';
import { mount } from '../../test/mount';
import { flush, stubFetch, type Call } from '../../test/net';
import { DealPage } from './DealPage';

const me: Me = { seller: { id: 's_1', name: 'Ada', verified: true, email_masked: 'a***@example.com' }, paypal_mode: 'mock' };

function makeDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'dl_1',
    title: 'Launch Blog Post',
    status: 'draft',
    amount_cents: 2500,
    fee_cents: 250,
    payout_cents: 2250,
    checklist: [
      { id: 'c1', text: 'Explains buyer protection', kind: 'ai', value: null },
      { id: 'c2', text: 'At least 10 words', kind: 'min_words', value: 10 },
    ],
    verdict: null,
    attempts: 0,
    attempts_left: 3,
    built_by: 'gemini:gemini-3.5-flash-lite',
    created_at: 1700000000,
    updated_at: 1700000000,
    error: null,
    brief: 'Write a post about buyer protection.',
    share_token: 'tok_secret',
    freelancer_email: 'freelancer@example.com',
    role: 'client',
    timeline: [{ seq: 1, at: 1700000000, kind: 'deal.created', data: { amount_cents: 2500 }, hash: '1234567890abcdef' }],
    ...overrides,
  };
}

let currentDeal: Deal = makeDeal();
let submitResponse: Deal = makeDeal();
let calls: Call[] = [];

beforeEach(() => {
  currentDeal = makeDeal();
  submitResponse = makeDeal();
  calls = stubFetch((method, path) => {
    if (method === 'GET' && path.startsWith('/api/deals/dl_1')) return currentDeal;
    if (method === 'POST' && path === '/api/deals/dl_1/order') {
      return { paypal_order_id: 'MOCK-ORDER-1', approve_url: '/paypal/mock-approve?order=MOCK-ORDER-1', mock: true };
    }
    if (method === 'POST' && path === '/api/deals/dl_1/fund') {
      currentDeal = makeDeal({ status: 'funded', updated_at: 1700000010 });
      return currentDeal;
    }
    if (method === 'POST' && path.startsWith('/api/deals/dl_1/submit')) {
      currentDeal = submitResponse;
      return currentDeal;
    }
    throw new Error(`unrouted ${method} ${path}`);
  });
});

afterEach(() => vi.unstubAllGlobals());

test('client mock funding moves deal from draft to funded and reveals share link', async () => {
  const view = await mount(<DealPage id="dl_1" me={me} info={mockInfo}/>);
  await flush(4);
  const holdBtn = [...view.host.querySelectorAll('button')].find(b => b.textContent?.includes('Hold $25.00 with PayPal'))!;
  expect(holdBtn).toBeDefined();

  await view.click(holdBtn);
  await flush(4);

  expect(calls.some(c => c.path === '/api/deals/dl_1/order')).toBe(true);
  expect(calls.some(c => c.path === '/api/deals/dl_1/fund')).toBe(true);
  expect(view.host.textContent).toContain('HELD $25.00');
  expect(view.host.textContent).toContain('#deal/dl_1.tok_secret');
  await view.unmount();
});

test('freelancer submit shows ticks and the PAID stamp when checks pass', async () => {
  currentDeal = makeDeal({ status: 'funded', role: 'freelancer' });
  submitResponse = makeDeal({
    status: 'released',
    role: 'freelancer',
    attempts: 1,
    attempts_left: 2,
    updated_at: 1700000020,
    verdict: {
      passed: true,
      summary: '2 of 2 checks passed',
      items: [
        { id: 'c1', text: 'Explains buyer protection', pass: true, reason: 'Covers PayPal hold' },
        { id: 'c2', text: 'At least 10 words', pass: true, reason: '14 words (minimum 10)' },
      ],
    },
  });

  const view = await mount(<DealPage id="dl_1.tok_secret" me={null} info={mockInfo}/>);
  await flush(4);
  expect(view.host.textContent).toContain('$25.00 is held by PayPal for this job');

  const textarea = view.host.querySelector('textarea[aria-label="Delivered work"]') as HTMLTextAreaElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    setter.call(textarea, 'Our PayPal checkout holds the money safely until the delivered work passes all checks.');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.dispatchEvent(new Event('change', { bubbles: true }));
  });

  const submitBtn = [...view.host.querySelectorAll('button')].find(b => b.textContent === 'Submit work')!;
  await view.click(submitBtn);
  await flush(4);

  expect(view.host.querySelectorAll('.check-mark.tick')).toHaveLength(2);
  expect(view.host.querySelector('.deal-stamp.stamp-good')?.textContent).toContain('PAID $22.50');
  await view.unmount();
});

test('failed check shows NOT YET and attempts left', async () => {
  currentDeal = makeDeal({ status: 'funded', role: 'freelancer' });
  submitResponse = makeDeal({
    status: 'submitted',
    role: 'freelancer',
    attempts: 1,
    attempts_left: 2,
    updated_at: 1700000020,
    verdict: {
      passed: false,
      summary: '1 of 2 checks passed',
      items: [
        { id: 'c1', text: 'Explains buyer protection', pass: true, reason: 'Covers hold' },
        { id: 'c2', text: 'At least 10 words', pass: false, reason: '4 words (minimum 10)' },
      ],
    },
  });

  const view = await mount(<DealPage id="dl_1.tok_secret" me={null} info={mockInfo}/>);
  await flush(4);

  const textarea = view.host.querySelector('textarea[aria-label="Delivered work"]') as HTMLTextAreaElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    setter.call(textarea, 'Too short work here.');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.dispatchEvent(new Event('change', { bubbles: true }));
  });

  const submitBtn = [...view.host.querySelectorAll('button')].find(b => b.textContent === 'Submit work')!;
  await view.click(submitBtn);
  await flush(4);

  expect(view.host.querySelectorAll('.check-mark.cross')).toHaveLength(1);
  expect(view.host.querySelector('.deal-stamp.stamp-bad')?.textContent).toBe('NOT YET — 1 of 2 checks passed');
  expect(view.host.textContent).toContain('2 attempts left');
  await view.unmount();
});
