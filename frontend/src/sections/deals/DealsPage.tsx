import { useEffect, useState } from 'react';
import type { Info, Me } from '../../api';
import { Button } from '../../components/ui/Button';
import {
  buildChecklist, createDeal, fetchDeals,
  type ChecklistItem, type ChecklistKind, type Deal, type DealStatus,
} from '../../dealsApi';
import { cents } from '../../format';
import { goSignIn, rememberReturn } from '../../signIn';

type Props = { me: Me | null; info: Info | null; navigate?: (url: string) => void };
type Preset = { label: string; brief: string; price: string; email: string };

const PRESETS: Preset[] = [
  {
    label: 'Blog post',
    brief: 'Write a launch post for our PayPal escrow checkout. Explain how buyer protection works, write at least 30 words, and include the exact phrase instant payout.',
    price: '25',
    email: 'writer@example.com',
  },
  {
    label: 'Logo brief',
    brief: 'Deliver a brand identity specification for a fintech app called Parable. Describe the primary colour palette, typography rules, icon grid usage, and include the exact phrase monochrome mark.',
    price: '50',
    email: 'designer@example.com',
  },
  {
    label: 'Bug fix',
    brief: 'Write a root-cause postmortem and patch notes for the duplicate webhook retry issue. Explain the idempotency lock, write at least 25 words, and include the exact phrase capture_id.',
    price: '40',
    email: 'dev@example.com',
  },
];

const KIND_LABELS: Record<ChecklistKind, string> = {
  ai: 'AI check',
  min_words: 'Min words',
  must_include: 'Must include',
};
const NEXT_KIND: Record<ChecklistKind, ChecklistKind> = {
  ai: 'min_words',
  min_words: 'must_include',
  must_include: 'ai',
};
const STATUS_NAMES: Record<DealStatus, string> = {
  draft: 'Draft',
  funded: 'Held in PayPal',
  submitted: 'Under review',
  released: 'Paid',
  returned: 'Returned',
  error: 'Needs retry',
};

export function DealStatusBadge({ status }: { status: DealStatus }) {
  const tone = status === 'released' ? 'good' : status === 'returned' || status === 'error' ? 'bad' : 'neutral';
  return <span className={`badge status-${tone} deal-badge-${status}`}>{STATUS_NAMES[status]}</span>;
}

export function DealsPage({ me, navigate }: Props) {
  const signedIn = Boolean(me?.seller);
  const [brief, setBrief] = useState(PRESETS[0].brief);
  const [price, setPrice] = useState(PRESETS[0].price);
  const [email, setEmail] = useState(PRESETS[0].email);
  const [title, setTitle] = useState('');
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [builtBy, setBuiltBy] = useState('');
  const [building, setBuilding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [deals, setDeals] = useState<Deal[]>([]);

  useEffect(() => {
    if (!signedIn) { setDeals([]); return; }
    let cancelled = false;
    fetchDeals()
      .then(list => { if (!cancelled) setDeals(list); })
      .catch(() => { if (!cancelled) setDeals([]); });
    return () => { cancelled = true; };
  }, [signedIn]);

  function applyPreset(preset: Preset) {
    setBrief(preset.brief);
    setPrice(preset.price);
    setEmail(preset.email);
    setError('');
  }

  async function onBuild() {
    setError('');
    setBuilding(true);
    try {
      const built = await buildChecklist(brief);
      setTitle(built.title);
      setItems(built.items);
      setBuiltBy(built.built_by);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not build the checklist.');
    } finally {
      setBuilding(false);
    }
  }

  function updateItem(index: number, patch: Partial<ChecklistItem>) {
    setItems(current =>
      current.map((item, idx) => (idx === index ? { ...item, ...patch } : item)).map((item, idx) => ({ ...item, id: `c${idx + 1}` }))
    );
  }

  function cycleKind(index: number) {
    const item = items[index];
    if (!item) return;
    const next = NEXT_KIND[item.kind];
    updateItem(index, { kind: next, value: next === 'min_words' ? 20 : next === 'must_include' ? 'keyword' : null });
  }

  function removeItem(index: number) {
    setItems(current => current.filter((_, idx) => idx !== index).map((item, idx) => ({ ...item, id: `c${idx + 1}` })));
  }

  function addItem() {
    if (items.length >= 8) return;
    setItems(current => [...current, { id: `c${current.length + 1}`, text: 'Meets all brief criteria', kind: 'ai', value: null }]);
  }

  async function onCreate() {
    const amountCents = Math.round(Number(price) * 100);
    if (!Number.isFinite(amountCents) || amountCents < 100 || amountCents > 50000) {
      setError('Price must be between $1.00 and $500.00.');
      return;
    }
    setError('');
    setCreating(true);
    try {
      const created = await createDeal({
        title: title.trim() || 'Freelance deal',
        brief,
        checklist: items,
        amount_cents: amountCents,
        freelancer_email: email.trim(),
        built_by: builtBy || 'rules',
      });
      window.location.hash = `#deal/${created.id}`;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not create the deal.');
    } finally {
      setCreating(false);
    }
  }

  return <section className="wrap page stack deals-page">
    <div className="deals-hero">
      <h1>Pay when the work passes.</h1>
      <p className="lead">PayPal holds the money. An AI agent checks the work. Then it pays or returns.</p>
    </div>

    <div className="box deals-builder">
      <div className="box-head">
        <strong>1 · Describe the job</strong>
        <div className="deal-presets" role="group" aria-label="Example briefs">
          {PRESETS.map(preset => (
            <button key={preset.label} type="button" className="chip-btn" onClick={() => applyPreset(preset)}>{preset.label}</button>
          ))}
        </div>
      </div>

      <div className="deals-form">
        <label className="field">
          <span className="field-label">Job brief</span>
          <textarea rows={4} value={brief} onChange={event => setBrief(event.target.value)}
            placeholder="Describe what the freelancer must deliver and how to verify it..."/>
        </label>

        <div className="deals-form-row">
          <label className="field narrow">
            <span className="field-label">Price (USD)</span>
            <input type="number" min="1" max="500" step="1" value={price} onChange={event => setPrice(event.target.value)}/>
          </label>
          <label className="field">
            <span className="field-label">Freelancer&apos;s PayPal email</span>
            <input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="freelancer@example.com"/>
          </label>
        </div>

        <div className="actions">
          {signedIn
            ? <Button variant="solid" disabled={building || brief.trim().length < 20} onClick={onBuild}>
                {building ? 'Building agent…' : 'Build the agent'}
              </Button>
            : <Button variant="solid" onClick={() => { rememberReturn('#deals'); goSignIn(navigate); }}>
                Sign in with PayPal
              </Button>}
        </div>
      </div>

      {items.length > 0 && <div className="deals-checklist-panel">
        <div className="box-head">
          <strong>2 · Acceptance checklist</strong>
          <span className="mono muted">built by {builtBy || 'rules'}</span>
        </div>
        <div className="deals-checklist-body">
          <label className="field">
            <span className="field-label">Deal title</span>
            <input type="text" aria-label="Deal title" value={title} onChange={event => setTitle(event.target.value)}/>
          </label>

          <ul className="checklist-edit-list" aria-label="Acceptance checks">
            {items.map((item, index) => (
              <li key={item.id} className="checklist-edit-item" style={{ animationDelay: `${index * 120}ms` }}>
                <button type="button" className={`kind-badge kind-${item.kind}`} onClick={() => cycleKind(index)} title="Click to switch check type">
                  {KIND_LABELS[item.kind]}
                </button>
                <input type="text" className="checklist-text-input" aria-label={`Check ${index + 1}`}
                  value={item.text} onChange={event => updateItem(index, { text: event.target.value })}/>
                {item.kind !== 'ai' && (
                  <input type={item.kind === 'min_words' ? 'number' : 'text'} className="checklist-value-input"
                    aria-label={`Value ${index + 1}`} value={item.value ?? ''}
                    onChange={event => updateItem(index, { value: item.kind === 'min_words' ? Number(event.target.value) || 1 : event.target.value })}/>
                )}
                <button type="button" className="link-btn remove-check-btn" disabled={items.length <= 2}
                  onClick={() => removeItem(index)} aria-label={`Remove check ${index + 1}`}>Remove</button>
              </li>
            ))}
          </ul>

          <div className="actions">
            <Button variant="quiet" disabled={items.length >= 8} onClick={addItem}>Add a check</Button>
            <Button variant="solid" disabled={creating || items.length < 2} onClick={onCreate}>
              {creating ? 'Creating…' : 'Create deal'}
            </Button>
          </div>
        </div>
      </div>}

      {error && <p className="say bad deals-error" role="alert">{error}</p>}
    </div>

    {signedIn && <div className="box">
      <div className="box-head"><strong>My deals</strong><span className="mono muted">{deals.length} total</span></div>
      {deals.length === 0
        ? <p className="empty">No deals yet. Build an agent above to start your first deal.</p>
        : <div className="purchase-list">
            {deals.map(deal => (
              <a key={deal.id} className="row purchase-row" href={`#deal/${deal.id}`}>
                <div><strong>{deal.title}</strong><span className="mono muted">#{deal.id}</span></div>
                <span className="mono">{cents(deal.amount_cents)}</span>
                <DealStatusBadge status={deal.status}/>
              </a>
            ))}
          </div>}
    </div>}

    <a className="box slim-market-card" href="#market">
      <span>Trading agents — pay only when the proof passes</span>
      <span className="mono">Explore →</span>
    </a>
  </section>;
}
