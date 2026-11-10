import { useState } from 'react';
import { createListing, type SaleMode } from '../../api';
import { promise } from '../../format';
import { Button } from '../../components/ui/Button';
import type { Build } from './useBuild';

const TRIALS: [number, string][] = [[3600, '1 hour'], [21600, '6 hours'], [86400, '1 day'], [259200, '3 days']];

export function SellDialog({ build, onClose }: { build: Build; onClose: () => void }) {
  const [title, setTitle] = useState(build.spec?.name ?? '');
  const [pitch, setPitch] = useState(build.spec?.summary ?? '');
  const [price, setPrice] = useState('19');
  const [mode, setMode] = useState<SaleMode>('hold');
  const [trial, setTrial] = useState(86400);
  const [minReturn, setMinReturn] = useState('0');
  const [maxLoss, setMaxLoss] = useState('10');
  const [drive, setDrive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const saved = build.saved;
  const cents = Math.round(Number(price) * 100);
  const minBps = Math.round(Number(minReturn) * 100);
  const lossBps = Math.round(Number(maxLoss) * 100);
  const okForm = title.trim().length >= 3 && cents >= 100 && cents <= 50000 && Number.isFinite(minBps) && lossBps >= 10 && lossBps <= 5000;

  async function submit() {
    if (!saved?.versionId || !saved.proofId) return;
    setBusy(true);
    setError('');
    try {
      const listing = await createListing({
        version_id: saved.versionId, title: title.trim(), pitch: pitch.trim().slice(0, 600), price_cents: cents, mode,
        trial_s: trial, min_return_bps: minBps, max_loss_bps: lossBps, proof_id: saved.proofId, allow_test_drive: drive,
      });
      window.location.hash = `#agent/${listing.id}`;
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not list');
      setBusy(false);
    }
  }

  return <div className="scrim" role="dialog" aria-modal="true" aria-label="Sell this agent" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog box">
      <div className="dialog-body">
        <h3>Sell</h3>
        <label className="field"><span className="field-label">Title</span><input value={title} maxLength={80} onChange={e => setTitle(e.target.value)}/></label>
        <label className="field"><span className="field-label">Pitch</span><textarea rows={2} value={pitch} maxLength={600} onChange={e => setPitch(e.target.value)}/></label>
        <label className="field narrow"><span className="field-label">Price (USD)</span><input inputMode="decimal" value={price} onChange={e => setPrice(e.target.value)}/></label>
        <div className="toggle" role="group" aria-label="Sale mode">
          <button type="button" aria-pressed={mode === 'hold'} onClick={() => setMode('hold')}>Hold</button>
          <button type="button" aria-pressed={mode === 'instant'} onClick={() => setMode('instant')}>Instant</button>
        </div>
        <p className="say">{mode === 'hold' ? 'Buyer pays after a live trial. You are paid only if it passes.' : 'Buyer pays now. You are paid at once.'}</p>
        {mode === 'hold' && <>
          <div className="toggle" role="group" aria-label="Trial length">
            {TRIALS.map(([s, l]) => <button key={s} type="button" aria-pressed={trial === s} onClick={() => setTrial(s)}>{l}</button>)}
          </div>
          <div className="two">
            <label className="field"><span className="field-label">Min return %</span><input inputMode="decimal" value={minReturn} onChange={e => setMinReturn(e.target.value)}/></label>
            <label className="field"><span className="field-label">Max loss %</span><input inputMode="decimal" value={maxLoss} onChange={e => setMaxLoss(e.target.value)}/></label>
          </div>
          {okForm && <p className="say">{promise(trial, minBps)}</p>}
        </>}
        <label className="check"><input type="checkbox" checked={drive} onChange={e => setDrive(e.target.checked)}/> Allow free test-drive before buying</label>
        {error && <p className="say bad" role="alert">{error}</p>}
        <div className="actions">
          <Button variant="solid" disabled={!okForm || busy || !saved?.proofId} onClick={submit}>{busy ? 'Listing' : 'List for sale'}</Button>
          <Button variant="quiet" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  </div>;
}
