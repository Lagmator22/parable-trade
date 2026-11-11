import { useState } from 'react';
import { fetchListing, type ListingDetail, type Me, type PublicListing } from '../api';
import { builtBy, cents, duration, instantOnly, promise } from '../format';
import { Button } from '../components/ui/Button';
import { Check } from '../components/ui/Glyphs';
import { DataPill, LivePill, ModePill } from '../components/Pills';
import { usePoll } from '../hooks/usePoll';
import { Diligence } from './Diligence';
import { Numbers } from './ListingCard';
import { BenchmarkTable } from './agent/BenchmarkTable';
import { LiveTrack } from './agent/LiveTrack';
import { ProofSection } from './agent/ProofSection';
import { RecentProofs } from './agent/RecentProofs';
import { RerunPanel } from './agent/RerunPanel';
import { TestDrivePanel } from './agent/TestDrivePanel';

type Props = { id: string; me: Me | null; onBuy: (l: PublicListing) => void };

function Terms({ listing }: { listing: ListingDetail }) {
  if (listing.mode === 'instant') return <p className="promise">Pay once. Download the agent at once.</p>;
  return <p className="promise">{promise(listing.trial_s, listing.min_return_bps)}. Trial {duration(listing.trial_s)}, stops at {(listing.max_loss_bps / 100).toFixed(1)}% loss.</p>;
}

function Head({ listing, mine, onBuy }: { listing: ListingDetail; mine: boolean; onBuy: () => void }) {
  return <header className="agent-head box">
    <div className="agent-title">
      <a className="out-link" href="#market">← Market</a>
      <h1>{listing.title}</h1>
      <p className="by mono">
        {listing.symbol.split(':').pop()} · {listing.interval} · built by {builtBy(listing.built_by)}
        <span>{listing.seller.name}</span>
        {listing.seller.verified && <span className="verified"><Check size={14}/>Verified</span>}
      </p>
      <div className="pill-row"><ModePill mode={listing.mode}/><DataPill kind={listing.data.source_kind}/><LivePill track={listing.track}/></div>
    </div>
    <div className="agent-buy">
      <p className="price">{cents(listing.price_cents)}</p>
      {mine
        ? <a className="btn btn-line" href="#mine"><span>Your listing</span></a>
        : <Button variant="solid" className="big" disabled={!listing.active} onClick={onBuy}>{listing.active ? 'Buy' : 'Not for sale'}</Button>}
    </div>
    <div className="agent-nums"><Numbers listing={listing}/><Terms listing={listing}/>{listing.pitch && <p className="pitch full">{listing.pitch}</p>}</div>
  </header>;
}

export function AgentPage({ id, me, onBuy }: Props) {
  const { data, error, reload } = usePoll(() => fetchListing(id), { every: 15000, deps: [id] });
  const [report, setReport] = useState(false);
  if (!data) return <section className="wrap page"><a className="out-link" href="#market">← Market</a>{error ? <p className="say bad" role="alert">{error}</p> : <p className="say">Loading the agent</p>}</section>;
  const mine = Boolean(me?.seller && me.seller.id === data.seller.id);
  const upload = data.symbol.startsWith('upload:');
  const live = data.track && !instantOnly(data.symbol);
  return <section className="wrap page stack">
    <Head listing={data} mine={mine} onBuy={() => onBuy(data)}/>
    <ProofSection proof={data.proof} note={data.data_note}/>
    {data.benchmark && <BenchmarkTable benchmark={data.benchmark}/>}
    {live && data.track && <LiveTrack key={data.track.run_id} track={data.track}/>}
    <RerunPanel listing={data} onDone={reload}/>
    {data.allow_test_drive && !upload && <TestDrivePanel listing={data}/>}
    <RecentProofs proofs={data.proofs}/>
    <section className="box agent-block">
      <div className="box-head"><strong>AI due diligence</strong><Button variant="quiet" aria-expanded={report} onClick={() => setReport(open => !open)}>{report ? 'Hide' : 'Read the report'}</Button></div>
      {report && <div className="block-body"><Diligence listingId={data.id}/></div>}
    </section>
    {!mine && data.active && <div className="buy-foot"><Button variant="solid" className="big" onClick={() => onBuy(data)}>Buy {cents(data.price_cents)}</Button></div>}
  </section>;
}
