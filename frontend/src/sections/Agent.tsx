import { useState, type FormEvent } from 'react';
import { askShopper, type Listing, type Recommendation } from '../api';
import { brainName } from '../format';
import { Button } from '../components/ui/Button';
import { Section } from '../components/ui/Section';
import { ListingCard } from './ListingCard';

type Props = { listings: Listing[]; onBuy: (listing: Listing) => void };

const EXAMPLE = 'a low-risk bot under $30 that has survived most of its runs';

function parseBudget(text: string): number | undefined {
  const dollars = Number(text);
  return text.trim() && Number.isFinite(dollars) && dollars > 0 ? Math.round(dollars * 100) : undefined;
}

export function Agent({ listings, onBuy }: Props) {
  const [query, setQuery] = useState('');
  const [budget, setBudget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Recommendation | null>(null);

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError('');
    try {
      setResult(await askShopper(query.trim(), parseBudget(budget)));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The shopping agent is unavailable.');
    } finally {
      setBusy(false);
    }
  }

  const picked = result && (listings.find(item => item.id === result.listing_id) ?? result.listing);
  const others = result ? result.alternatives.map(id => listings.find(item => item.id === id)).filter((item): item is Listing => Boolean(item)) : [];

  return <Section id="agent" label="01 Shopping agent">
    <h2>Tell the agent what you need.</h2>
    <p className="lead">It reads every seller’s public record and recommends one bot. It can only pick from listed bots, and it never touches your money.</p>
    <form className="agent-form box" onSubmit={ask}>
      <label className="field">
        <span className="field-label">What are you looking for?</span>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder={`e.g. ${EXAMPLE}`} maxLength={300}/>
      </label>
      <label className="field narrow">
        <span className="field-label">Max price, USD (optional)</span>
        <input value={budget} onChange={event => setBudget(event.target.value)} inputMode="decimal" placeholder="30"/>
      </label>
      <Button type="submit" variant="solid" disabled={busy || !query.trim()}>{busy ? 'Thinking…' : 'Ask the agent'}</Button>
    </form>
    {error && <p className="say bad" role="alert">{error}</p>}
    {result && <div className="agent-result" aria-live="polite">
      <p className="say">Recommendation by {result.by === 'rules' ? 'fixed rules' : brainName(result.by)}</p>
      {picked ? <ListingCard listing={picked} onBuy={onBuy} note={result.reason}/> : <p className="empty box">{result.reason || 'Nothing in the market fits that yet.'}</p>}
      {others.length > 0 && <p className="say">Also worth a look: {others.map(item => item.title).join(', ')}</p>}
    </div>}
  </Section>;
}
