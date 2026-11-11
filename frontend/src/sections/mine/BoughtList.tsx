import { useState } from 'react';
import { downloadLicense, runPurchase, stopRun, type BoughtAgent, type Run } from '../../api';
import { Button, LinkButton } from '../../components/ui/Button';
import { ModePill } from '../../components/Pills';
import { StatusBadge } from '../Purchase';
import { saveBlob } from '../PurchaseLicense';
import { RunChart } from '../agent/RunChart';

function Row({ item }: { item: BoughtAgent }) {
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  async function act(name: string, job: () => Promise<void>) {
    setBusy(name);
    setError('');
    try { await job(); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Failed'); }
    setBusy('');
  }

  const live = run?.status === 'alive';
  return <div className="box mine-row">
    <div className="mine-main">
      <strong>{item.title}</strong>
      <span className="mono muted">{item.symbol.split(':').pop()} · {item.interval}</span>
    </div>
    <ModePill mode={item.mode}/>
    <StatusBadge status={item.status}/>
    <div className="actions">
      {item.entitled && !live && <Button variant="solid" disabled={busy === 'run'} onClick={() => act('run', async () => setRun(await runPurchase(item.purchase_id)))}>Go live</Button>}
      {live && run && <Button disabled={busy === 'stop'} onClick={() => act('stop', async () => setRun(await stopRun(run.id)))}>Stop</Button>}
      {item.entitled && <Button disabled={busy === 'download'} onClick={() => act('download', async () => saveBlob(await downloadLicense(item.purchase_id), `${item.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${item.spec_hash.slice(0, 8)}.json`))}>Download</Button>}
      <LinkButton variant="quiet" href={`#purchase/${item.purchase_id}`}>Purchase</LinkButton>
    </div>
    {error && <p className="say bad" role="alert">{error}</p>}
    {run && <div className="block-body"><RunChart runId={run.id} alive={live} label={`${item.title} running`}/></div>}
  </div>;
}

export function BoughtList({ items }: { items: BoughtAgent[] }) {
  if (items.length === 0) return <div className="box empty"><p>Nothing bought yet.</p><LinkButton variant="solid" href="#market">Browse agents</LinkButton></div>;
  return <div className="mine-list">{items.map(item => <Row key={item.purchase_id} item={item}/>)}</div>;
}
