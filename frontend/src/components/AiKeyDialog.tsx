import { useState } from 'react';
import { fetchModels, type ModelInfo } from '../api';
import { clearAiKey, loadAiSettings, saveAiSettings, type AiProvider, type AiSettings } from '../aiSettings';
import { Button } from './ui/Button';

const PROVIDERS: [AiProvider, string][] = [['platform', 'Free'], ['openai', 'OpenAI'], ['anthropic', 'Anthropic'], ['gemini', 'Gemini']];

export function AiKeyDialog({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState<AiSettings>(loadAiSettings);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [status, setStatus] = useState('');
  const [bad, setBad] = useState(false);
  const [busy, setBusy] = useState(false);
  const own = form.provider !== 'platform';

  async function test() {
    setBusy(true);
    setStatus('');
    try {
      const result = await fetchModels(form);
      const list = result.own.filter(m => m.available);
      setModels(list);
      setBad(list.length === 0);
      setStatus(list.length ? `Key works. ${list.length} models.` : 'No models found for this key.');
      if (list.length && !list.some(m => m.model === form.model)) setForm(f => ({ ...f, model: list[0].model }));
    } catch (failure) {
      setBad(true);
      setStatus(failure instanceof Error ? failure.message : 'Test failed');
    }
    setBusy(false);
  }

  function save() {
    saveAiSettings(form);
    onClose();
  }

  function forget() {
    clearAiKey();
    setForm({ provider: 'platform', model: '', key: '', remember: false });
    setModels([]);
    setStatus('Key removed from this browser.');
    setBad(false);
  }

  return <div className="scrim" role="dialog" aria-modal="true" aria-label="AI settings" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog box">
      <div className="dialog-body">
        <h3>AI</h3>
        <div className="toggle" role="group" aria-label="Provider">
          {PROVIDERS.map(([id, label]) => <button key={id} type="button" aria-pressed={form.provider === id}
            onClick={() => { setForm({ ...form, provider: id, model: '' }); setModels([]); setStatus(''); }}>{label}</button>)}
        </div>
        {!own && <p className="say">Free models, a few tries a day. Add your own key for unlimited use.</p>}
        {own && <>
          <label className="field"><span className="field-label">API key</span>
            <input type="password" autoComplete="off" spellCheck={false} value={form.key} onChange={e => setForm({ ...form, key: e.target.value })} placeholder="Paste key"/></label>
          <label className="check"><input type="checkbox" checked={form.remember} onChange={e => setForm({ ...form, remember: e.target.checked })}/> Remember on this device</label>
          <p className="say">Stored only in this browser. Sent only with your AI requests.</p>
          <div className="actions"><Button onClick={test} disabled={busy || !form.key.trim()}>{busy ? 'Testing' : 'Test key'}</Button></div>
          {models.length > 0 && <label className="field"><span className="field-label">Model</span>
            <select value={form.model} onChange={e => setForm({ ...form, model: e.target.value })}>
              {models.map(m => <option key={m.id} value={m.model}>{m.label}</option>)}
            </select></label>}
          {status && <p className={`say ${bad ? 'bad' : ''}`} role="status">{status}</p>}
        </>}
        <div className="actions">
          <Button variant="solid" onClick={save}>Save</Button>
          {own && <Button variant="quiet" onClick={forget}>Remove key</Button>}
          <Button variant="quiet" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  </div>;
}
