import { useState, type FormEvent } from 'react';
import { createListing, type Info } from '../api';
import { brainName, strategyName } from '../format';
import { buildPayload, emptyForm, type FormState } from '../listingForm';
import { Button } from '../components/ui/Button';
import { SelectMenu } from '../components/ui/SelectMenu';

type Props = { info: Info; onCreated: () => void };

type FieldProps = { label: string; value: string; onChange: (value: string) => void; hint?: string; wide?: boolean; multiline?: boolean };

function Field({ label, value, onChange, hint, wide, multiline }: FieldProps) {
  return <label className={`field ${wide ? 'wide' : ''}`}>
    <span className="field-label">{label}</span>
    {multiline
      ? <textarea value={value} rows={3} onChange={event => onChange(event.target.value)}/>
      : <input value={value} onChange={event => onChange(event.target.value)} inputMode={wide ? 'text' : 'decimal'}/>}
    {hint && <span className="hint mono">{hint}</span>}
  </label>;
}

export function ListingForm({ info, onCreated }: Props) {
  const brains = info.brains.filter(item => item.available);
  const [form, setForm] = useState<FormState>(() => emptyForm(info.strategies[0]?.id, brains[0]?.brain));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (key: keyof FormState) => (value: string) => setForm(current => ({ ...current, [key]: value }));
  const strategyText = info.strategies.find(item => item.id === form.strategy)?.text;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildPayload(form);
    if (!built.ok) { setError(built.error); return; }
    setBusy(true);
    setError('');
    try {
      await createListing(built.payload);
      setForm(emptyForm(form.strategy, form.brain));
      onCreated();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not create the listing.');
    } finally {
      setBusy(false);
    }
  }

  return <form className="box listing-form" onSubmit={submit}>
    <div className="box-head"><strong>New listing</strong><span>the promise below is enforced by the referee</span></div>
    <div className="form-grid">
      <Field wide label="Title" value={form.title} onChange={set('title')}/>
      <Field wide multiline label="Pitch" value={form.pitch} onChange={set('pitch')} hint="Claims that the record does not support get flagged by the AI due diligence."/>
      <SelectMenu label="Strategy" value={form.strategy} onChange={set('strategy')} options={info.strategies.map(item => ({ value: item.id, label: strategyName(item.id) }))}/>
      <SelectMenu label="Brain" value={form.brain} onChange={set('brain')} options={brains.map(item => ({ value: item.brain, label: brainName(item.brain) }))}/>
      {strategyText && <p className="hint mono wide">{strategyText}</p>}
      <Field label="Price (USD)" value={form.price} onChange={set('price')} hint="$1 to $500"/>
      <Field label="Probation (minutes)" value={form.probationMinutes} onChange={set('probationMinutes')} hint="up to 4320, the PayPal hold window"/>
      <Field label="Loss limit (%)" value={form.lossLimitPercent} onChange={set('lossLimitPercent')} hint="bot is ended if it falls this far from its peak"/>
      <Field label="Minimum return (%)" value={form.minReturnPercent} onChange={set('minReturnPercent')} hint="negative allows a small loss"/>
      <Field label="Max trade (USD)" value={form.maxTrade} onChange={set('maxTrade')} hint="paper cash is fixed at $1,000"/>
    </div>
    <div className="form-foot">
      <Button type="submit" variant="solid" disabled={busy}>{busy ? 'Publishing…' : 'Publish listing'}</Button>
      {error && <p className="say bad" role="alert">{error}</p>}
    </div>
  </form>;
}
