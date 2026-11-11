import { useState, type FormEvent } from 'react';
import { askShopper, fetchListing, type PublicListing, type Recommendation } from '../../api';
import { brainName } from '../../format';
import { Button } from '../../components/ui/Button';
import { ListingCard } from '../ListingCard';

type Props = { listings: PublicListing[]; onBuy: (listing: PublicListing) => void };

const parseBudget = (text: string) => {
  const dollars = Number(text);
  return text.trim() && Number.isFinite(dollars) && dollars > 0 ? Math.round(dollars * 100) : undefined;
};

async function resolve(id: string | null, known: PublicListing[]): Promise<PublicListing | null> {
  if (!id) return null;
  const hit = known.find(item => item.id === id);
  if (hit) return hit;
  try { return await fetchListing(id); } catch { return null; }
}

export function Shopper({ listings, onBuy }: Props) {
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<{ rec: Recommendation; picked: PublicListing | null; others: PublicListing[] } | null>(null);

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError('');
    try {
      const rec = await askShopper(query.trim(), parseBudget(budget));
      const picked = await resolve(rec.listing_id, listings);
      const others = (await Promise.all(rec.alternatives.map(id => resolve(id, listings)))).filter((x): x is PublicListing => Boolean(x));
      setResult({ rec, picked, others });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The shopper is unavailable.');
    }
    setBusy(false);
  }

  return <section className="shopper box" aria-label="AI shopper">
    <div className="box-head"><strong>Ask the AI shopper</strong><span>it only reads public proof</span></div>
    <form className="shopper-form" onSubmit={ask}>
      <label className="field"><span className="field-label">What do you need?</span>
        <input value={query} onChange={e => setQuery(e.target.value)} maxLength={300} placeholder="a calm crypto agent under $30"/></label>
      <label className="field narrow"><span className="field-label">Max price, USD</span>
        <input value={budget} onChange={e => setBudget(e.target.value)} inputMode="decimal" placeholder="30"/></label>
      <Button type="submit" variant="solid" disabled={busy || !query.trim()}>{busy ? 'Thinking' : 'Ask'}</Button>
    </form>
    {error && <p className="say bad" role="alert">{error}</p>}
    {result && <div className="shopper-result" aria-live="polite">
      <p className="say">By {result.rec.by === 'rules' ? 'fixed rules' : brainName(result.rec.by)}</p>
      {result.picked
        ? <ListingCard listing={result.picked} onBuy={onBuy} note={result.rec.reason}/>
        : <p className="empty">{result.rec.reason || 'Nothing fits yet.'}</p>}
      {result.others.length > 0 && <div className="listing-grid">{result.others.map(item => <ListingCard key={item.id} listing={item} onBuy={onBuy}/>)}</div>}
    </div>}
  </section>;
}
