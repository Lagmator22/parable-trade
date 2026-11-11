import type { PublicListing } from '../api';
import { builtBy, cents, pct } from '../format';
import { Button, LinkButton } from '../components/ui/Button';
import { Check } from '../components/ui/Glyphs';
import { DataPill, LivePill, ModePill } from '../components/Pills';
import { Sparkline } from '../components/Sparkline';

type Props = { listing: PublicListing; onBuy: (listing: PublicListing) => void; note?: string };

const tone = (value: number) => (value > 0 ? 'up' : value < 0 ? 'down' : '');

export function Numbers({ listing }: { listing: PublicListing }) {
  const h = listing.headline;
  return <dl className="nums">
    <div><dt>Return</dt><dd className={tone(h.total_return_pct)}>{pct(h.total_return_pct)}</dd></div>
    <div><dt>Hold</dt><dd className={tone(h.benchmark_return_pct)}>{pct(h.benchmark_return_pct)}</dd></div>
    <div><dt>Worst drop</dt><dd>{`-${h.max_drawdown_pct.toFixed(1)}%`}</dd></div>
    <div><dt>Win rate</dt><dd>{`${h.win_rate_pct.toFixed(0)}%`}</dd></div>
  </dl>;
}

export function ListingCard({ listing, onBuy, note }: Props) {
  return <article className="listing box">
    <div className="listing-top">
      <div>
        <h3><a href={`#agent/${listing.id}`}>{listing.title}</a></h3>
        <p className="by mono">
          {listing.symbol.split(':').pop()} · {listing.interval}
          <span>{listing.seller.name}</span>
          {listing.seller.verified && <span className="verified"><Check size={14}/>Verified</span>}
        </p>
      </div>
      <p className="price">{cents(listing.price_cents)}</p>
    </div>
    {note && <p className="note">{note}</p>}
    <Sparkline points={listing.sparkline} label={`${listing.title} equity against buy and hold`}/>
    <Numbers listing={listing}/>
    <div className="pill-row">
      <ModePill mode={listing.mode}/>
      <DataPill kind={listing.data.source_kind}/>
      <span className="pill">{builtBy(listing.built_by)}</span>
      <LivePill track={listing.track}/>
    </div>
    <div className="listing-actions">
      <LinkButton href={`#agent/${listing.id}`}>Proof</LinkButton>
      <Button variant="solid" onClick={() => onBuy(listing)}>Buy {cents(listing.price_cents)}</Button>
    </div>
  </article>;
}
