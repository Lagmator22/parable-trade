import { useState } from 'react';
import { deleteAgent, type AgentSummary, type SaleSummary } from '../../api';
import { cents, pct } from '../../format';
import { Button, LinkButton } from '../../components/ui/Button';

type Props = { agents: AgentSummary[]; sales: SaleSummary[]; onChange: () => void };

function Row({ agent, sale, onChange }: { agent: AgentSummary; sale?: SaleSummary; onChange: () => void }) {
  const [error, setError] = useState('');
  const listed = agent.status === 'listed' && agent.listing_id;
  const ret = agent.headline?.total_return_pct;

  async function remove() {
    try { await deleteAgent(agent.id); onChange(); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not delete'); }
  }

  return <div className="box mine-row">
    <div className="mine-main">
      <strong>{agent.name}</strong>
      <span className="mono muted">{agent.symbol.split(':').pop()} · {agent.interval}</span>
    </div>
    <span className={`badge ${listed ? 'status-good' : ''}`}>{listed ? 'Listed' : 'Draft'}</span>
    <span className={`mono ${ret === undefined ? 'muted' : ret >= 0 ? 'up' : 'down'}`}>{ret === undefined ? '-' : pct(ret)}</span>
    {sale && <span className="mono sales" aria-label="Sales">{sale.purchases} sold · {cents(sale.captured_cents)} captured · {cents(sale.paid_out_cents)} paid</span>}
    <div className="actions">
      <LinkButton variant="solid" href={`#build/${agent.id}`}>Open in Build</LinkButton>
      {listed && <LinkButton href={`#agent/${agent.listing_id}`}>Listing</LinkButton>}
      {!listed && <Button variant="quiet" onClick={remove}>Delete</Button>}
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
  </div>;
}

export function BuiltList({ agents, sales, onChange }: Props) {
  if (agents.length === 0) return <div className="box empty"><p>Nothing built yet.</p><LinkButton variant="solid" href="#build">Build an agent</LinkButton></div>;
  return <div className="mine-list">
    {agents.map(agent => <Row key={agent.id} agent={agent} sale={sales.find(s => s.listing_id === agent.listing_id)} onChange={onChange}/>)}
  </div>;
}
