import { act } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mount } from '../test/mount';
import { failure, flush, stubFetch, type Call } from '../test/net';
import { UploadBox } from './UploadBox';

const dataset = { id: 'd_ab12cd34ef', symbol: 'upload:d_ab12cd34ef', name: 'prices', interval: '1d', quote: 'USD', bars: 50, start: 1, end: 2, data_hash: 'h', created_at: 3 };
let calls: Call[] = [];
let reply: (path: string) => unknown = () => ({ status: 'ready', dataset });

beforeEach(() => { calls = stubFetch((_m, path) => reply(path)); });
afterEach(() => vi.unstubAllGlobals());

async function pick(host: HTMLElement, name = 'prices.csv') {
  const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
  const file = new File(['t,close\n1,2'], name, { type: 'text/csv' });
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
  await flush();
}

const press = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text) as HTMLButtonElement;

test('a clean file becomes a dataset at once', async () => {
  reply = () => ({ status: 'ready', dataset });
  const onReady = vi.fn();
  const view = await mount(<UploadBox onReady={onReady}/>);
  await pick(view.host);
  expect(calls[0].path).toBe('/api/datasets');
  expect(onReady).toHaveBeenCalledWith(dataset);
  await view.unmount();
});

test('an unclear file shows the column mapping, AI match and confirm', async () => {
  reply = path => {
    if (path === '/api/datasets') return { status: 'needs_mapping', draft_id: 'dr_1', columns: ['when', 'px'], preview: [['2024-01-01', '10']], suggestion: { t: 'when' } };
    if (path === '/api/datasets/ai-map') return { mapping: { t: 'when', close: 'px' }, by: 'gemini' };
    return { status: 'ready', dataset };
  };
  const onReady = vi.fn();
  const view = await mount(<UploadBox onReady={onReady}/>);
  await pick(view.host);
  expect(view.host.querySelector('.mapping')).not.toBeNull();
  expect(press(view.host, 'Use this data').disabled).toBe(true);
  await view.click(press(view.host, 'Match with AI'));
  await flush();
  expect(press(view.host, 'Use this data').disabled).toBe(false);
  await view.click(press(view.host, 'Use this data'));
  await flush();
  expect(calls.find(c => c.path === '/api/datasets/map')?.body).toMatchObject({ draft_id: 'dr_1', mapping: { t: 'when', close: 'px' } });
  expect(onReady).toHaveBeenCalledWith(dataset);
  expect(view.host.querySelector('.mapping')).toBeNull();
  await view.unmount();
});

test('signed out uploads ask to sign in and other errors are shown', async () => {
  reply = () => { throw failure(401, 'unauthorized', 'unauthorized'); };
  const view = await mount(<UploadBox onReady={() => {}}/>);
  await pick(view.host);
  expect(view.host.querySelector('[role=alert]')?.textContent).toBe('Sign in to upload data.');
  reply = () => { throw failure(413, 'File too large', 'too_large'); };
  await pick(view.host);
  expect(view.host.querySelector('[role=alert]')?.textContent).toBe('File too large');
  await view.unmount();
});
