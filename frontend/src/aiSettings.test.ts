import { beforeEach, describe, expect, it } from 'vitest';
import { clearAiKey, hasOwnKey, headersFor, loadAiSettings, loadDraft, saveAiSettings, saveDraft } from './aiSettings';

describe('aiSettings', () => {
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });

  it('defaults to the platform with no headers', () => {
    const s = loadAiSettings();
    expect(s.provider).toBe('platform');
    expect(headersFor(s)).toEqual({});
  });

  it('keeps the key in sessionStorage unless remembered', () => {
    saveAiSettings({ provider: 'openai', model: 'gpt-x', key: 'sk-secret', remember: false });
    expect(localStorage.getItem('parable.ai.key')).toBeNull();
    expect(sessionStorage.getItem('parable.ai.key')).toBe('sk-secret');
    expect(loadAiSettings().key).toBe('sk-secret');
    saveAiSettings({ provider: 'openai', model: 'gpt-x', key: 'sk-secret', remember: true });
    expect(localStorage.getItem('parable.ai.key')).toBe('sk-secret');
    expect(sessionStorage.getItem('parable.ai.key')).toBeNull();
  });

  it('builds headers only with a key', () => {
    expect(headersFor({ provider: 'gemini', model: 'm', key: '', remember: false })).toEqual({});
    expect(headersFor({ provider: 'gemini', model: 'm', key: ' k ', remember: false })).toEqual({ 'x-ai-provider': 'gemini', 'x-ai-model': 'm', 'x-ai-key': 'k' });
    expect(hasOwnKey({ provider: 'platform', model: '', key: 'k', remember: false })).toBe(false);
  });

  it('clears the key everywhere', () => {
    saveAiSettings({ provider: 'anthropic', model: 'c', key: 'k', remember: true });
    clearAiKey();
    const s = loadAiSettings();
    expect(s.key).toBe('');
    expect(s.provider).toBe('platform');
  });

  it('round trips the build draft', () => {
    saveDraft({ spec: { a: 1 }, steps: 'x' });
    expect(loadDraft()).toEqual({ spec: { a: 1 }, steps: 'x' });
  });
});
