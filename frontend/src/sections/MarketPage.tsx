import { useState } from 'react';
import { fetchListings, fetchStats, type AssetKind, type PublicListing, type SaleMode } from '../api';
import { LinkButton } from '../components/ui/Button';
import { usePoll } from '../hooks/usePoll';
import { Hero } from './Hero';
import { ListingCard } from './ListingCard';
import { Shopper } from './market/Shopper';

type KindFilter = AssetKind | 'all';
type ModeFilter = SaleMode | 'all';
type Sort = 'new' | 'return' | 'price';

const KINDS: [KindFilter, string][] = [['all', 'All'], ['crypto', 'Crypto'], ['stocks', 'Stocks'], ['funds', 'Funds'], ['forex', 'Forex'], ['gold', 'Gold']];
const MODES: [ModeFilter, string][] = [['all', 'Any'], ['hold', 'Pay if proven'], ['instant', 'Instant']];
const SORTS: [Sort, string][] = [['return', 'Best return'], ['new', 'Newest'], ['price', 'Cheapest']];

function Group<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return <div className="toggle" role="group" aria-label={label}>
    {options.map(([id, text]) => <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)}>{text}</button>)}
  </div>;
}

export function MarketPage({ onBuy }: { onBuy: (l: PublicListing) => void }) {
  const [kind, setKind] = useState<KindFilter>('all');
  const [mode, setMode] = useState<ModeFilter>('all');
  const [sort, setSort] = useState<Sort>('return');
  const stats = usePoll(fetchStats, { every: 15000 });
  const list = usePoll(() => fetchListings({ kind: kind === 'all' ? undefined : kind, mode: mode === 'all' ? undefined : mode, sort }), { every: 15000, deps: [kind, mode, sort] });
  const items = list.data ?? [];

  return <>
    <Hero stats={stats.data}/>
    <section className="mk-body">
      <div className="wrap stack">
        <div className="filters">
          <Group label="Asset" value={kind} options={KINDS} onChange={setKind}/>
          <Group label="Sale mode" value={mode} options={MODES} onChange={setMode}/>
          <Group label="Sort" value={sort} options={SORTS} onChange={setSort}/>
        </div>
        {list.error && !list.data && <p className="say bad" role="alert">{list.error}</p>}
        {list.data && items.length === 0 && <div className="box empty">
          <p>No agents match. Build the first one.</p>
          <LinkButton variant="solid" href="#build">Build an agent</LinkButton>
        </div>}
        <div className="listing-grid" id="market-grid">
          {items.map(item => <ListingCard key={item.id} listing={item} onBuy={onBuy}/>)}
        </div>
        <ol className="how-strip" aria-label="How it works">
          <li><b>1</b>Check the proof</li>
          <li><b>2</b>Re-run it yourself</li>
          <li><b>3</b>Buy. Hold or instant.</li>
        </ol>
        <Shopper listings={items} onBuy={onBuy}/>
      </div>
    </section>
  </>;
}
