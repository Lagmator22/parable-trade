export type AiProvider = 'openai' | 'anthropic' | 'gemini' | 'platform';
export type AiSettings = { provider: AiProvider; model: string; key: string; remember: boolean };

const PROVIDER = 'parable.ai.provider';
const MODEL = 'parable.ai.model';
const KEY = 'parable.ai.key';
const REMEMBER = 'parable.ai.remember';
const DRAFT = 'parable.build.draft';
const PROVIDERS: AiProvider[] = ['openai', 'anthropic', 'gemini', 'platform'];

function read(store: () => Storage, name: string): string {
  try { return store().getItem(name) ?? ''; } catch { return ''; }
}

function write(store: () => Storage, name: string, value: string | null) {
  try {
    if (value === null) store().removeItem(name);
    else store().setItem(name, value);
  } catch { return; }
}

const local = () => window.localStorage;
const session = () => window.sessionStorage;

export function loadAiSettings(): AiSettings {
  const saved = read(local, PROVIDER);
  const provider = (PROVIDERS as string[]).includes(saved) ? (saved as AiProvider) : 'platform';
  const remember = read(local, REMEMBER) === '1';
  const key = read(local, KEY) || read(session, KEY);
  return { provider, model: read(local, MODEL), key, remember };
}

export function saveAiSettings(settings: AiSettings) {
  write(local, PROVIDER, settings.provider);
  write(local, MODEL, settings.model);
  write(local, REMEMBER, settings.remember ? '1' : '0');
  write(local, KEY, settings.remember && settings.key ? settings.key : null);
  write(session, KEY, !settings.remember && settings.key ? settings.key : null);
}

export function clearAiKey() {
  write(local, KEY, null);
  write(session, KEY, null);
  write(local, PROVIDER, 'platform');
  write(local, MODEL, null);
}

export const hasOwnKey = (settings: AiSettings = loadAiSettings()) => settings.provider !== 'platform' && settings.key.trim().length > 0;

export function headersFor(settings: AiSettings): Record<string, string> {
  if (!hasOwnKey(settings)) return {};
  const headers: Record<string, string> = { 'x-ai-provider': settings.provider, 'x-ai-key': settings.key.trim() };
  if (settings.model) headers['x-ai-model'] = settings.model;
  return headers;
}

export const maskKey = (key: string) => (key.length <= 8 ? '****' : `${key.slice(0, 3)}...${key.slice(-4)}`);

export type BuildDraft = { spec: unknown; steps: string };

export function loadDraft(): BuildDraft | null {
  try {
    const raw = read(local, DRAFT);
    return raw ? (JSON.parse(raw) as BuildDraft) : null;
  } catch { return null; }
}

export const saveDraft = (draft: BuildDraft) => write(local, DRAFT, JSON.stringify(draft));
export const clearDraft = () => write(local, DRAFT, null);
