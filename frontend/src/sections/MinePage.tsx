import { useState } from 'react';
import { fetchMyAgents, fetchMySales, type Me } from '../api';
import { Button } from '../components/ui/Button';
import { usePoll } from '../hooks/usePoll';
import { goSignIn } from '../signIn';
import { BoughtList } from './mine/BoughtList';
import { BuiltList } from './mine/BuiltList';

type Tab = 'built' | 'bought';

function Signed({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const agents = usePoll(fetchMyAgents, { every: 10000 });
  const sales = usePoll(() => fetchMySales().catch(() => []), { every: 20000 });
  const built = agents.data?.built ?? [];
  const bought = agents.data?.bought ?? [];
  return <>
    <div className="toggle" role="group" aria-label="My agents">
      <button type="button" aria-pressed={tab === 'built'} onClick={() => setTab('built')}>Built {agents.data ? built.length : ''}</button>
      <button type="button" aria-pressed={tab === 'bought'} onClick={() => setTab('bought')}>Bought {agents.data ? bought.length : ''}</button>
    </div>
    {agents.error && !agents.data && <p className="say bad" role="alert">{agents.error}</p>}
    {agents.data && tab === 'built' && <BuiltList agents={built} sales={sales.data ?? []} onChange={() => { agents.reload(); }}/>}
    {agents.data && tab === 'bought' && <BoughtList items={bought}/>}
  </>;
}

export function MinePage({ me }: { me: Me | null }) {
  const [tab, setTab] = useState<Tab>('built');
  return <section className="wrap page stack">
    <h1 className="page-title">My agents</h1>
    {!me && <p className="say">Loading</p>}
    {me && !me.seller && <div className="box empty">
      <p>Sign in to see what you built and bought.</p>
      <Button variant="solid" onClick={() => goSignIn()}>Sign in with PayPal</Button>
    </div>}
    {me?.seller && <Signed tab={tab} setTab={setTab}/>}
  </section>;
}
