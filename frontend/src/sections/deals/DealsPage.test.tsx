import { act } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Me } from '../../api';
import { mockInfo } from '../../test/fixtures';
import { mount } from '../../test/mount';
import { flush, stubFetch, type Call } from '../../test/net';
import { DealsPage } from './DealsPage';

const me: Me = { seller: { id: 's_1', name: 'Ada', verified: true, email_masked: 'a***@example.com' }, paypal_mode: 'mock' };

let calls: Call[] = [];

beforeEach(() => {
  window.location.hash = '#deals';
  calls = stubFetch((method, path, body) => {
    if (method === 'GET' && path === '/api/deals') return [];
    if (method === 'POST' && path === '/api/deals/checklist') {
      return {
        title: 'Launch Blog Post',
        built_by: 'gemini:gemini-3.5-flash-lite',
        items: [
          { id: 'c1', text: 'Explains buyer protection', kind: 'ai', value: null },
          { id: 'c2', text: 'At least 30 words', kind: 'min_words', value: 30 },
        ],
      };
    }
    if (method === 'POST' && path === '/api/deals') {
      const payload = body as Record<string, unknown>;
      return {
        id: 'dl_test123',
        title: payload.title,
        status: 'draft',
        amount_cents: payload.amount_cents,
        fee_cents: 250,
        payout_cents: 2250,
        checklist: payload.checklist,
        verdict: null,
        attempts: 0,
        attempts_left: 3,
        built_by: payload.built_by,
        created_at: 1700000000,
        updated_at: 1700000000,
        error: null,
      };
    }
    throw new Error(`unrouted ${method} ${path}`);
  });
});

afterEach(() => vi.unstubAllGlobals());

test('builds a checklist, edits an item, and creates the deal', async () => {
  const view = await mount(<DealsPage me={me} info={mockInfo}/>);
  await flush(4);
  expect(view.host.textContent).toContain('Pay when the work passes.');

  const buildBtn = [...view.host.querySelectorAll('button')].find(b => b.textContent === 'Build the agent')!;
  await view.click(buildBtn);
  await flush(4);

  expect(view.host.textContent).toContain('built by gemini:gemini-3.5-flash-lite');
  const firstCheck = view.host.querySelector('input[aria-label="Check 1"]') as HTMLInputElement;
  expect(firstCheck.value).toBe('Explains buyer protection');

  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(firstCheck, 'Explains PayPal hold clearly');
    firstCheck.dispatchEvent(new Event('input', { bubbles: true }));
    firstCheck.dispatchEvent(new Event('change', { bubbles: true }));
  });

  const createBtn = [...view.host.querySelectorAll('button')].find(b => b.textContent === 'Create deal')!;
  await view.click(createBtn);
  await flush(4);

  const postDeal = calls.find(c => c.method === 'POST' && c.path === '/api/deals')!;
  expect(postDeal).toBeDefined();
  expect((postDeal.body as { checklist: { text: string }[] }).checklist[0].text).toBe('Explains PayPal hold clearly');
  expect(window.location.hash).toBe('#deal/dl_test123');
  await view.unmount();
});
