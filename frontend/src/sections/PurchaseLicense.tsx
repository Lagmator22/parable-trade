import { useState } from 'react';
import { downloadLicense, runPurchase, type PurchaseView, type Run } from '../api';
import { Button } from '../components/ui/Button';
import { Copy } from '../components/ui/Glyphs';
import { RunChart } from './agent/RunChart';

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'agent';

export function LicensePanel({ purchase }: { purchase: PurchaseView }) {
  const license = purchase.license;
  const [copied, setCopied] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  if (!license) return null;

  async function copy() {
    try { await navigator.clipboard.writeText(license!.key); setCopied(true); } catch { setCopied(false); }
  }

  async function download() {
    setBusy('download');
    setError('');
    try { saveBlob(await downloadLicense(purchase.id), `${slug(purchase.listing.title)}-${license!.spec_hash.slice(0, 8)}.json`); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Download failed'); }
    setBusy('');
  }

  async function start() {
    setBusy('run');
    setError('');
    try { setRun(await runPurchase(purchase.id)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not start'); }
    setBusy('');
  }

  return <div className="box license">
    <div className="box-head"><strong>Your license</strong><span>{purchase.mode === 'hold' ? 'unlocked, it passed' : 'unlocked, paid'}</span></div>
    <div className="license-key mono">
      <code>{license.key}</code>
      <button type="button" className="link-btn" onClick={copy}><Copy size={16}/>{copied ? 'Copied' : 'Copy'}</button>
    </div>
    <div className="actions license-actions">
      <Button variant="solid" disabled={busy === 'download'} onClick={download}>Download JSON</Button>
      <Button disabled={busy === 'run' || run !== null} onClick={start}>{run ? 'Running' : 'Run on Parable'}</Button>
    </div>
    <p className="say">{license.run_hint}</p>
    {error && <p className="say bad" role="alert">{error}</p>}
    {run && <div className="block-body">
      <RunChart runId={run.id} alive label="Your agent running on paper money"/>
      <a className="out-link" href="#mine">See it in My agents</a>
    </div>}
  </div>;
}
