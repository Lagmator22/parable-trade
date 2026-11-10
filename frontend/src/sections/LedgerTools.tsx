import { useState } from 'react';
import { tamperDemo, verifyLedger, type TamperResult, type VerifyResult } from '../api';
import { shortHash } from '../format';
import { Button } from '../components/ui/Button';
import { Check, Shield } from '../components/ui/Glyphs';

export const show = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value));

export function VerifyLine({ result }: { result: VerifyResult }) {
  return result.ok
    ? <p className="say verified-line" role="status"><Check size={16}/> Chain intact. {result.checked} entries checked, head {shortHash(result.head, 12)}…</p>
    : <p className="say bad" role="alert"><Shield size={16}/> Chain broken at entry #{result.first_bad_seq}. {result.checked} entries checked.</p>;
}

export function VerifyPanel({ headSeq }: { headSeq: number | undefined }) {
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [tamper, setTamper] = useState<TamperResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run<T>(action: () => Promise<T>, apply: (value: T) => void) {
    setBusy(true);
    setError('');
    try { apply(await action()); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Request failed'); }
    setBusy(false);
  }

  return <div className="box">
    <div className="box-head"><span>Every entry hashes the one before it</span><span>{headSeq ? `${headSeq} entries` : ''}</span></div>
    <div className="verify-body">
      <div className="actions">
        <Button variant="solid" disabled={busy} onClick={() => run(verifyLedger, value => { setResult(value); setTamper(null); })}>Verify chain</Button>
        <Button disabled={busy} onClick={() => run(tamperDemo, value => { setTamper(value); setResult(null); })}>Try to rewrite history</Button>
      </div>
      {result && <VerifyLine result={result}/>}
      {tamper && <div className="tamper" aria-live="polite">
        <p className="say">A copy of the ledger, with entry #{tamper.edited_seq} edited. The real ledger was not touched.</p>
        <div className="diff"><div><span className="field-label">Before</span><code>{show(tamper.before)}</code></div><div><span className="field-label">After</span><code>{show(tamper.after)}</code></div></div>
        <VerifyLine result={tamper.verify}/>
      </div>}
      {error && <p className="say bad" role="alert">{error}</p>}
    </div>
  </div>;
}
