import { act } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mount } from '../test/mount';
import { flush, stubFetch } from '../test/net';
import { AiKeyDialog } from './AiKeyDialog';

const model = { id: 'openai:gpt', provider: 'openai', model: 'gpt', label: 'GPT', available: true, free: false };
let reply: unknown;

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); stubFetch(() => reply); });
afterEach(() => vi.unstubAllGlobals());

async function test$(keyOk: boolean | null | undefined) {
  reply = { platform: [], own: [model], free_tries: { limit: 5, used: 0, remaining: 5 }, ...(keyOk === undefined ? {} : { key_ok: keyOk }) };
  const view = await mount(<AiKeyDialog onClose={() => {}}/>);
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'OpenAI')!);
  const input = view.host.querySelector<HTMLInputElement>('input[type=password]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'sk-test');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Test key')!);
  await flush();
  const status = view.host.querySelector('[role=status]')!;
  const out = { text: status.textContent, bad: status.className.includes('bad') };
  await view.unmount();
  return out;
}

test('key_ok true says the key works', async () => {
  expect(await test$(true)).toEqual({ text: 'Key works. 1 models.', bad: false });
});

test('key_ok false says the key was rejected', async () => {
  expect(await test$(false)).toEqual({ text: 'The provider rejected this key.', bad: true });
});

test('key_ok null says the check could not run', async () => {
  const result = await test$(null);
  expect(result.text).toContain('Could not check');
  expect(result.bad).toBe(false);
});

test('without key_ok the model list decides', async () => {
  expect((await test$(undefined)).text).toBe('Key works. 1 models.');
});
