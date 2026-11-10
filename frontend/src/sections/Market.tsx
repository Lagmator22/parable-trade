import { useState } from 'react';
import { fetchPrices, type Listing } from '../api';
import { usdFloat, clockTime, toMillis } from '../format';
import { Chart } from '../components/ui/Chart';
import { Section } from '../components/ui/Section';
import { LinkButton } from '../components/ui/Button';
import { usePoll } from '../hooks/usePoll';
import { SORT_LABELS, sortListings, type SortMode } from '../listings';
import { ListingCard } from './ListingCard';

type Props = { listings: Listing[] | null; error: string | null; onBuy: (listing: Listing) => void };

function PriceFeed() {
  const prices = usePoll(fetchPrices, { every: 10000 });
  const points = (prices.data?.points ?? []).map(([at, price]) => [toMillis(at) / 1000, price] as [number, number]);
  if (points.length < 2) return null;
  return <div className="box price-feed">
    <div className="box-head"><span>The referee’s live ETH/USD feed</span><span>bots trade it with paper money</span></div>
    <div className="chart-scroll">
      <Chart label="ETH price" lines={[{ name: 'ETH/USD', color: 'var(--ink)', points }]} yFormat={usdFloat} xFormat={x => clockTime(x)}/>
    </div>
  </div>;
}

export function Market({ listings, error, onBuy }: Props) {
  const [mode, setMode] = useState<SortMode>('record');
  const sorted = sortListings(listings ?? [], mode);
  return <Section id="market" label="02 Market">
    <div className="market-head">
      <h2>Bots for sale.</h2>
      <div className="toggle" role="group" aria-label="Sort bots">
        {(Object.keys(SORT_LABELS) as SortMode[]).map(key => <button key={key} type="button" aria-pressed={mode === key} onClick={() => setMode(key)}>{SORT_LABELS[key]}</button>)}
      </div>
    </div>
    <PriceFeed/>
    {error && !listings && <p className="say bad" role="alert">{error}</p>}
    {listings && listings.length === 0 && <div className="box empty">
      <p>No bots are listed yet. Be the first seller.</p>
      <LinkButton variant="solid" href="#sell">Sell a bot</LinkButton>
    </div>}
    <div className="listing-grid" id="market-grid">
      {sorted.map(listing => <ListingCard key={listing.id} listing={listing} onBuy={onBuy}/>)}
    </div>
  </Section>;
}
