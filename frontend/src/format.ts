const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

const FAMILIES: Record<string, string> = { rule: 'Simple rule', claude: 'Claude', gemini: 'Gemini', gemma: 'Gemma', jev: 'Jev' };
const SMALL_WORDS = new Set(['it', 'of']);

export const cents = (value: number) => dollars.format(value / 100);

export const usdMicro = (value: number) => dollars.format(value / 1_000_000);

export const usdFloat = (value: number) => dollars.format(value);

export const bps = (value: number) => `${(value / 100).toFixed(2)}%`;

export const bpsShort = (value: number) => `${(value / 100).toFixed(1)}%`;

export const signedBps = (value: number) => `${value > 0 ? '+' : ''}${bps(value)}`;

function titleWord(word: string) {
  return SMALL_WORDS.has(word) ? word : word.charAt(0).toUpperCase() + word.slice(1);
}

export function brainName(brain: string): string {
  const [family, model] = brain.includes(':') ? [brain.slice(0, brain.indexOf(':')), brain.slice(brain.indexOf(':') + 1)] : [brain, ''];
  const label = FAMILIES[family] ?? titleWord(family);
  if (!model) return label;
  const trimmed = model.startsWith(`${family}-`) ? model.slice(family.length + 1) : model;
  return `${label} ${mergeVersion(trimmed.split('-')).map(titleWord).join(' ')}`;
}

function mergeVersion(tokens: string[]): string[] {
  return tokens.reduce<string[]>((merged, token) => {
    const previous = merged[merged.length - 1];
    if (previous !== undefined && /^\d+(\.\d+)*$/.test(previous) && /^\d+$/.test(token)) merged[merged.length - 1] = `${previous}.${token}`;
    else merged.push(token);
    return merged;
  }, []);
}

export function strategyName(strategy: string): string {
  const spaced = strategy.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  if (total < 3600) return join(Math.floor(total / 60), 'min', total % 60, 's');
  if (total < 86400) return join(Math.floor(total / 3600), 'h', Math.floor((total % 3600) / 60), 'min');
  const days = Math.floor(total / 86400);
  return join(days, days === 1 ? 'day' : 'days', Math.floor((total % 86400) / 3600), 'h');
}

function join(major: number, majorUnit: string, minor: number, minorUnit: string) {
  return minor ? `${major} ${majorUnit} ${minor} ${minorUnit}` : `${major} ${majorUnit}`;
}

export function countdown(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86400);
  const clock = [Math.floor((total % 86400) / 3600), Math.floor((total % 3600) / 60), total % 60].map(n => String(n).padStart(2, '0'));
  if (days > 0) return `${days}d ${clock.join(':')}`;
  return total >= 3600 ? clock.join(':') : clock.slice(1).join(':');
}

export function promise(probationSeconds: number, minReturnBps: number): string {
  const stay = `survives ${duration(probationSeconds)}`;
  if (minReturnBps < 0) return `Pays only if it ${stay} and loses no more than ${bpsShort(-minReturnBps)}`;
  if (minReturnBps === 0) return `Pays only if it ${stay} and finishes at break-even or better`;
  return `Pays only if it ${stay} and gains at least ${bpsShort(minReturnBps)}`;
}

export const toMillis = (timestamp: number) => (timestamp > 1e12 ? timestamp : timestamp * 1000);

export const clockTime = (timestamp: number) => new Date(toMillis(timestamp)).toLocaleTimeString([], { hour12: false });

export const dateTime = (timestamp: number) => new Date(toMillis(timestamp)).toLocaleString([], { hour12: false });

export function ago(timestamp: number, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - toMillis(timestamp)) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

export const shortHash = (hash: string, length = 10) => hash.slice(0, length);

export const mask = (id: string | null | undefined) => (!id ? '' : id.length <= 8 ? id : `…${id.slice(-6)}`);

export const survivalPercent = (survived: number, ended: number) => (ended > 0 ? Math.round((survived / ended) * 100) : null);

export const priceFromRaw = (raw: number) => raw / 1e8;
