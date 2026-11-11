import { afterEach, expect, test, vi } from 'vitest';
import { listing, proof } from '../../test/fixtures';
import { mount } from '../../test/mount';
import { failure, flush, stubFetch } from '../../test/net';
import { RerunPanel } from './RerunPanel';

afterEach(() => vi.unstubAllGlobals());

const rerun = (hash: string, ret: number) => ({ ...proof, id: 'pf_2', kind: 'rerun' as const, result_hash: hash, metrics: { ...proof.metrics, total_return_pct: ret } });
const run = async (view: Awaited<ReturnType<typeof mount>>) => {
  await view.click([...view.host.querySelectorAll('button')].find(b => b.textContent === 'Re-run the proof')!);
  await flush();
};

test('a matching re-run shows the big match stamp and both hashes', async () => {
  const calls = stubFetch(() => ({ match: true, claim: proof, rerun: rerun(proof.result_hash, 12.5), diff: {}, data_hash_match: null, refetched: false }));
  const view = await mount(<RerunPanel listing={listing}/>);
  await run(view);
  expect(calls[0]).toMatchObject({ path: `/api/listings/${listing.id}/rerun`, body: { refetch: false } });
  expect(view.host.querySelector('.stamp-good')?.textContent).toBe('✓ MATCH');
  expect(view.host.textContent).toContain("Seller's claim");
  expect(view.host.textContent).toContain('Your re-run');
  expect(view.host.textContent).toContain('aaaaaaaaaaaa');
  expect(view.host.textContent).not.toContain('a'.repeat(30));
  await view.unmount();
});

test('a mismatch shows the red stamp and which numbers differ', async () => {
  stubFetch(() => ({ match: false, claim: proof, rerun: rerun('b'.repeat(64), 9.1), diff: { total_return_pct: { claim: 12.5, rerun: 9.1 }, trades: { claim: 7, rerun: 7 } }, data_hash_match: false, refetched: true }));
  const view = await mount(<RerunPanel listing={listing}/>);
  await run(view);
  expect(view.host.querySelector('.stamp-bad')?.textContent).toBe('✗ MISMATCH');
  expect(view.host.textContent).toContain('+9.10%');
  expect(view.host.textContent).toContain('Differs: total return pct');
  expect(view.host.textContent).toContain('Fresh data differs');
  await view.unmount();
});

test('the fetch-again option is sent as refetch and rate limits are explained', async () => {
  const calls = stubFetch(() => { throw failure(429, 'slow down', 'rate_limited'); });
  const view = await mount(<RerunPanel listing={listing}/>);
  await view.click(view.host.querySelector('input[type=checkbox]')!);
  await run(view);
  expect(calls[0].body).toEqual({ refetch: true });
  expect(view.host.querySelector('[role=alert]')?.textContent).toContain('Too many re-runs');
  await view.unmount();
});
