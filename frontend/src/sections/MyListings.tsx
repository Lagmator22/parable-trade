import { fetchRuns, pauseListing, startPractice, stopRun, type Listing, type Run } from '../api';
import { bpsShort, cents, countdown, duration, signedBps, usdMicro } from '../format';
import { Button } from '../components/ui/Button';
import { usePoll } from '../hooks/usePoll';
import { useState } from 'react';

type Props = { listings: Listing[]; sellerId: string; onChanged: () => void };

function RunRow({ run, onStop }: { run: Run; onStop: (id: number) => void }) {
  const alive = run.status === 'alive';
  const outcome = alive ? `${countdown(run.seconds_left)} left` : (run.cause ?? 'ended').replace('_', ' ');
  return <div className={`row practice ${!alive && run.cause === 'loss_limit' ? 'refused' : ''}`}>
    <span>{alive && <span className="live"/>} {run.name}</span>
    <span>{usdMicro(run.final_equity_usd ?? run.equity_usd)}</span>
    <span className={run.pnl_bps < 0 ? 'down' : 'up'}>{signedBps(run.pnl_bps)}</span>
    <span>{outcome}</span>
    {alive ? <button type="button" className="link-btn" onClick={() => onStop(run.id)}>Stop</button> : <span/>}
  </div>;
}

export function PracticeRuns({ sellerId }: { sellerId: string }) {
  const runs = usePoll(() => fetchRuns(`seller=${sellerId}&purpose=practice`), { every: 4000, deps: [sellerId] });
  const rows = (runs.data ?? []).slice(0, 12);
  async function stop(id: number) {
    await stopRun(id);
    await runs.reload();
  }
  return <div className="box">
    <div className="box-head"><span>Practice runs, public and permanent</span><span>{rows.length} latest</span></div>
    {rows.length === 0 && <p className="empty">No practice runs yet. Run one on a listing to build a record buyers can check.</p>}
    {rows.map(run => <RunRow key={run.id} run={run} onStop={stop}/>)}
  </div>;
}

export function MyListings({ listings, sellerId, onChanged }: Props) {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  async function act(id: string, action: () => Promise<unknown>) {
    setBusy(id);
    setError('');
    try {
      await action();
      onChanged();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'That did not work.');
    } finally {
      setBusy('');
    }
  }

  return <div className="stack">
    <div className="box">
      <div className="box-head"><span>Your listings</span><span>pausing hides a listing, it is never deleted</span></div>
      {listings.length === 0 && <p className="empty">You have no active listings.</p>}
      {listings.map(listing => <div className="row my-listing" key={listing.id}>
        <span><strong>{listing.title}</strong><br/><span className="muted">{duration(listing.probation_s)} · stops at {bpsShort(listing.rules.max_loss_bps)} loss</span></span>
        <span>{cents(listing.price_cents)}</span>
        <span className="row-actions">
          <Button variant="quiet" disabled={busy === listing.id} onClick={() => act(listing.id, () => startPractice(listing.id))}>Run practice</Button>
          <Button variant="quiet" disabled={busy === listing.id} onClick={() => act(listing.id, () => pauseListing(listing.id))}>Pause</Button>
        </span>
      </div>)}
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
    <PracticeRuns sellerId={sellerId}/>
  </div>;
}
