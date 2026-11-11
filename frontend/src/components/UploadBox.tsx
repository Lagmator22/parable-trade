import { useRef, useState } from 'react';
import { aiMapDataset, ApiError, mapDataset, uploadDataset, type Dataset } from '../api';
import { Button } from './ui/Button';

type Draft = { draft_id: string; columns: string[]; preview: string[][]; mapping: Record<string, string> };
const FIELDS = ['t', 'open', 'high', 'low', 'close', 'volume'];
const LABEL: Record<string, string> = { t: 'Time', open: 'Open', high: 'High', low: 'Low', close: 'Close or price', volume: 'Volume' };

export function UploadBox({ onReady }: { onReady: (d: Dataset) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notes, setNotes] = useState<string[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);

  const fail = (e: unknown) => setError(e instanceof ApiError && e.status === 401 ? 'Sign in to upload data.' : e instanceof Error ? e.message : 'Upload failed');

  async function send(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const result = await uploadDataset(file, file.name.replace(/\.[^.]+$/, ''));
      if (result.status === 'ready') { setNotes(result.warnings ?? []); onReady(result.dataset); }
      else setDraft({ draft_id: result.draft_id, columns: result.columns, preview: result.preview, mapping: result.suggestion ?? {} });
    } catch (e) { fail(e); }
    setBusy(false);
  }

  async function ai() {
    if (!draft) return;
    setBusy(true);
    setError('');
    try {
      const { mapping } = await aiMapDataset(draft.draft_id);
      setDraft({ ...draft, mapping });
    } catch (e) { fail(e); }
    setBusy(false);
  }

  async function confirm() {
    if (!draft) return;
    setBusy(true);
    setError('');
    try {
      const { dataset } = await mapDataset(draft.draft_id, draft.mapping);
      setDraft(null);
      onReady(dataset);
    } catch (e) { fail(e); }
    setBusy(false);
  }

  const ready = Boolean(draft?.mapping.t && draft?.mapping.close);
  return <div className="upload">
    <div className={`dropzone ${over ? 'over' : ''}`} role="button" tabIndex={0} aria-label="Upload a data file"
      onClick={() => input.current?.click()} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') input.current?.click(); }}
      onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]); }}>
      <strong>{busy ? 'Working' : 'Drop a file here'}</strong>
      <span>CSV, Excel, JSON or Word table. Max 5 MB.</span>
      <input ref={input} type="file" hidden accept=".csv,.tsv,.txt,.json,.xlsx,.docx" onChange={e => { send(e.target.files?.[0]); e.target.value = ''; }}/>
    </div>
    {draft && <div className="box mapping">
      <div className="box-head"><strong>Match your columns</strong></div>
      <div className="mapping-grid">
        {FIELDS.map(f => <label key={f} className="field"><span className="field-label">{LABEL[f]}</span>
          <select value={draft.mapping[f] ?? ''} onChange={e => setDraft({ ...draft, mapping: { ...draft.mapping, [f]: e.target.value } })}>
            <option value="">-</option>
            {draft.columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select></label>)}
      </div>
      <div className="scroll-x"><table className="preview"><thead><tr>{draft.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{draft.preview.slice(0, 4).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table></div>
      <div className="actions form-foot">
        <Button variant="solid" disabled={busy || !ready} onClick={confirm}>Use this data</Button>
        <Button disabled={busy} onClick={ai}>Match with AI</Button>
      </div>
    </div>}
    {notes.length > 0 && <p className="say">{notes.slice(0, 2).join(' ')}</p>}
    {error && <p className="say bad" role="alert">{error}</p>}
  </div>;
}
