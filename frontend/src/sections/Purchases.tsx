import { fetchPurchase } from '../api';
import { ago, cents } from '../format';
import { normalizePurchase, type Purchase } from '../purchase';
import { savedPurchases } from '../storage';
import { LinkButton } from '../components/ui/Button';
import { Section } from '../components/ui/Section';
import { usePoll } from '../hooks/usePoll';
import { StatusBadge } from './Purchase';

async function loadAll(): Promise<{ saved: ReturnType<typeof savedPurchases>[number]; purchase: Purchase | null }[]> {
  return Promise.all(savedPurchases().map(async saved => {
    try {
      return { saved, purchase: normalizePurchase(await fetchPurchase(saved.purchase_id, saved.buyer_token)) };
    } catch {
      return { saved, purchase: null };
    }
  }));
}

export function Purchases() {
  const { data } = usePoll(loadAll, { every: 5000 });
  const items = data ?? [];
  return <Section id="purchases" label="My purchases">
    <h2>Your purchases.</h2>
    <p className="lead">Saved in this browser only. Each one shows where its money is right now.</p>
    {data && items.length === 0 && <div className="box empty">
      <p>You have not bought a bot yet.</p>
      <LinkButton variant="solid" href="#market">Browse the market</LinkButton>
    </div>}
    <div className="purchase-list">
      {items.map(({ saved, purchase }) => <a key={saved.purchase_id} className="box purchase-row" href={`#purchase/${saved.purchase_id}`}>
        <div><strong>{purchase?.listingTitle ?? saved.listing_title}</strong><span className="mono muted">{ago(saved.saved_at)}</span></div>
        <span className="mono">{purchase ? cents(purchase.amountCents) : ''}</span>
        {purchase ? <StatusBadge status={purchase.status}/> : <span className="badge status-neutral">Unavailable</span>}
      </a>)}
    </div>
  </Section>;
}
