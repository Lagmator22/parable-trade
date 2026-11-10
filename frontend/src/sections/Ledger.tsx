import { useState } from 'react';
import { fetchLedger, fetchWebhooks, type LedgerEntry, type Webhook } from '../api';
import { ago, dateTime, shortHash } from '../format';
import { KIND_LABEL, kindLabel } from '../steps';
import { Button } from '../components/ui/Button';
import { Section } from '../components/ui/Section';
import { SelectMenu } from '../components/ui/SelectMenu';
import { usePoll } from '../hooks/usePoll';
import { show, VerifyPanel } from './LedgerTools';

const PAGE = 40;
const KIND_OPTIONS = [{ value: '', label: 'All entries' }, ...Object.keys(KIND_LABEL).map(kind => ({ value: kind, label: kindLabel(kind) }))];

const summary = (entry: LedgerEntry) =>
  Object.entries(entry.data).slice(0, 3).map(([key, value]) => `${key}=${show(value)}`).join('  ').slice(0, 110);

function EntryRow({ entry }: { entry: LedgerEntry }) {
  const bad = entry.kind === 'purchase.failed' || entry.kind === 'payment.voided' || entry.kind === 'run.refused';
  return <div className={`row entry ${bad ? 'refused' : ''}`}>
    <span className="muted">#{entry.seq}</span>
    <span><strong>{kindLabel(entry.kind)}</strong><br/><span className="muted">{entry.subject}</span></span>
    <span className="data">{summary(entry)}</span>
    <span className="muted hash" title={entry.hash}>{shortHash(entry.hash, 10)}</span>
  </div>;
}

function WebhookRow({ event }: { event: Webhook }) {
  return <div className="row webhook">
    <span>{event.event_type}</span>
    <span className={event.verified ? 'up' : 'down'}>{event.verified ? 'signature verified' : 'unverified'}</span>
    <span className="muted">{event.resource_id}</span>
    <time className="muted" title={dateTime(event.received_at)}>{ago(event.received_at)}</time>
  </div>;
}

export function Ledger() {
  const [kind, setKind] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const entries = usePoll(() => fetchLedger(limit, kind), { every: 4000, deps: [limit, kind] });
  const webhooks = usePoll(fetchWebhooks, { every: 6000 });
  const rows = entries.data ?? [];
  return <Section id="ledger" label="Ledger">
    <h2>The record nobody can edit.</h2>
    <p className="lead">Every listing, trade, refusal, verdict, capture and payout is chained to the one before it with SHA-256. Rewrite one entry and every hash after it breaks.</p>
    <VerifyPanel headSeq={rows[0]?.seq}/>
    <div className="box">
      <div className="box-head">
        <span>Latest entries</span>
        <SelectMenu label="Show" value={kind} options={KIND_OPTIONS} onChange={value => { setKind(value); setLimit(PAGE); }}/>
      </div>
      {entries.data && rows.length === 0 && <p className="empty">Nothing recorded yet.</p>}
      <div className="entries">{rows.map(entry => <EntryRow key={entry.seq} entry={entry}/>)}</div>
      {rows.length >= limit && <div className="more"><Button variant="quiet" onClick={() => setLimit(current => current + PAGE)}>Show older entries</Button></div>}
    </div>
    <div className="box">
      <div className="box-head"><span>Recent PayPal webhooks</span><span>signature-checked before they change anything</span></div>
      {webhooks.data && webhooks.data.length === 0 && <p className="empty">No webhooks received yet.</p>}
      <div className="webhooks">{(webhooks.data ?? []).map(event => <WebhookRow key={`${event.event_type}-${event.resource_id}-${event.received_at}`} event={event}/>)}</div>
    </div>
  </Section>;
}
