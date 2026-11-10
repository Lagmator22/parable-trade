import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, aiHeaders, compileSteps, fetchCandles, fetchModels, get, pollJob, uploadDataset } from './api';
import { saveAiSettings } from './aiSettings';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('api', () => {
  const fetchMock = vi.fn();
  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); localStorage.clear(); sessionStorage.clear(); });
  afterEach(() => vi.unstubAllGlobals());

  it('adds AI headers only when a key is set', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ spec: {} })));
    await compileSteps({ steps: 'x', symbol: 'sample:BTCUSDT', interval: '1h' });
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ 'content-type': 'application/json' });
    saveAiSettings({ provider: 'openai', model: 'gpt', key: 'sk-1', remember: false });
    await compileSteps({ steps: 'x', symbol: 'sample:BTCUSDT', interval: '1h' });
    expect(fetchMock.mock.calls[1][1].headers).toMatchObject({ 'x-ai-provider': 'openai', 'x-ai-model': 'gpt', 'x-ai-key': 'sk-1' });
    expect(aiHeaders()['x-ai-key']).toBe('sk-1');
    fetchMock.mockImplementation(() => Promise.resolve(json({ platform: [], own: [], free_tries: {} })));
    await fetchModels();
    expect(fetchMock.mock.calls[2][1].headers).toMatchObject({ 'x-ai-key': 'sk-1' });
  });

  it('maps error bodies to ApiError', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'bad spec', code: 'invalid_spec', errors: ['a', 'b'] }, 422)));
    const err = await get('/x').catch(e => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message, err.errors]).toEqual([422, 'invalid_spec', 'bad spec', ['a', 'b']]);
  });

  it('maps validation arrays, empty bodies and network failures', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: [{ msg: 'field required' }] }, 422));
    expect(((await get('/x').catch(e => e)) as ApiError).message).toBe('field required');
    fetchMock.mockResolvedValueOnce(new Response('<html>', { status: 502 }));
    expect(((await get('/x').catch(e => e)) as ApiError).message).toBe('Request failed (502)');
    fetchMock.mockRejectedValueOnce(new TypeError('boom'));
    const err = await get('/x').catch(e => e) as ApiError;
    expect([err.status, err.code]).toEqual([0, 'network']);
  });

  it('builds query strings', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({})));
    await fetchCandles('binance:BTCUSDT', '1h', 100, undefined, 5);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/markets/candles?symbol=binance%3ABTCUSDT&interval=1h&limit=100&end=5');
  });

  it('uploads multipart without a content type', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ status: 'needs_mapping', draft_id: 'dr_1', columns: [], preview: [], suggestion: null })));
    const result = await uploadDataset(new File(['a'], 'a.csv'), 'a');
    expect(result.status).toBe('needs_mapping');
    const init = fetchMock.mock.calls[0][1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined();
  });

  it('polls a job to completion and rejects on error', async () => {
    const job = (status: string, progress: number, result: unknown = null, error: string | null = null) => json({ id: 'j', kind: 'k', status, progress, message: '', result, error, created_at: 0 });
    fetchMock.mockResolvedValueOnce(job('running', 0.5)).mockResolvedValueOnce(job('done', 1, { ok: 1 }));
    const seen: number[] = [];
    expect(await pollJob('j', j => seen.push(j.progress), 1)).toEqual({ ok: 1 });
    expect(seen).toEqual([0.5, 1]);
    fetchMock.mockResolvedValueOnce(job('error', 0, null, 'nope'));
    await expect(pollJob('j', undefined, 1)).rejects.toBeInstanceOf(ApiError);
  });
});
