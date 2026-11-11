import { ApiError, fetchMyPurchases } from '../api';
import { ago, cents } from '../format';
import { goSignIn } from '../signIn';
import { Button, LinkButton } from '../components/ui/Button';
import { usePoll } from '../hooks/usePoll';
import type { PurchaseSummary } from '../api';
import { StatusBadge } from './Purchase';

async function load(): Promise<PurchaseSummary[] | 'signin'> {
  try {
    return await fetchMyPurchases();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 401) return 'signin';
    throw failure;
  }
}

export function Purchases() {
  const poll = usePoll(load, { every: 6000 });
  const { error } = poll;
  const signedOut = poll.data === 'signin';
  const data = poll.data === 'signin' ? null : poll.data;
  return <section className="wrap page stack">
    <h1 className="page-title">Purchases</h1>
    {signedOut && <div className="box empty">
      <p>Sign in to see what you bought.</p>
      <Button variant="solid" onClick={() => goSignIn()}>Sign in with PayPal</Button>
    </div>}
    {error && !data && !signedOut && <p className="say bad" role="alert">{error}</p>}
    {data && data.length === 0 && <div className="box empty">
      <p>Nothing bought yet.</p>
      <LinkButton variant="solid" href="#market">Browse agents</LinkButton>
    </div>}
    <div className="purchase-list">
      {(data ?? []).map(item => <a key={item.id} className="box purchase-row" href={`#purchase/${item.id}`}>
        <div><strong>{item.title}</strong><span className="mono muted">{ago(item.created_at)} · {item.mode === 'hold' ? 'Pay if proven' : 'Instant'}</span></div>
        <span className="mono">{cents(item.amount_cents)}</span>
        <StatusBadge status={item.status}/>
      </a>)}
    </div>
  </section>;
}
