import { useEffect, useRef, useState } from 'react';
import { deleteDataset, fetchDatasets, fetchPopular, searchSymbols, type AssetKind, type Dataset, type SymbolInfo } from '../api';
import { UploadBox } from './UploadBox';

export const KINDS: [AssetKind, string][] = [['crypto', 'Crypto'], ['stocks', 'Stocks'], ['funds', 'Funds'], ['forex', 'Forex'], ['gold', 'Gold'], ['mine', 'Mine']];

export const datasetInfo = (d: Dataset): SymbolInfo => ({ symbol: d.symbol, name: d.name, kind: 'mine', quote: d.quote, provider: 'upload', intervals: [d.interval], live: false });

type Props = { value: string; onSelect: (info: SymbolInfo) => void; initialKind?: AssetKind };

export function MarketPicker({ value, onSelect, initialKind = 'crypto' }: Props) {
  const [kind, setKind] = useState<AssetKind>(initialKind);
  const [chips, setChips] = useState<SymbolInfo[]>([]);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<SymbolInfo[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState('');
  const seq = useRef(0);

  useEffect(() => {
    if (kind === 'mine') {
      fetchDatasets().then(d => { setDatasets(d); setError(''); }).catch(() => setError('Sign in to see your data.'));
      return;
    }
    fetchPopular(kind).then(list => { setChips(list); setError(''); }).catch(() => setError('Could not load symbols.'));
  }, [kind]);

  useEffect(() => {
    const q = query.trim();
    const mine = ++seq.current;
    if (q.length < 2 || kind === 'mine') { setFound([]); return; }
    const timer = window.setTimeout(() => {
      searchSymbols(q, kind).then(list => { if (mine === seq.current) setFound(list); }).catch(() => { if (mine === seq.current) setFound([]); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, kind]);

  async function remove(d: Dataset) {
    await deleteDataset(d.id).catch(() => undefined);
    setDatasets(list => list.filter(x => x.id !== d.id));
  }

  const shown = found.length ? found : chips;
  return <div className="picker">
    <div className="toggle tabs" role="tablist" aria-label="Asset type">
      {KINDS.map(([id, label]) => <button key={id} type="button" role="tab" aria-pressed={kind === id} aria-selected={kind === id} onClick={() => { setKind(id); setQuery(''); }}>{label}</button>)}
    </div>
    {kind !== 'mine' && <>
      <label className="field"><span className="field-label">Search</span>
        <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Name or ticker"/></label>
      <div className="chip-row" aria-label="Symbols">
        {shown.map(s => <button key={s.symbol} type="button" className="chip" aria-pressed={s.symbol === value} onClick={() => onSelect(s)}>
          <b>{s.symbol.split(':')[1] ?? s.symbol}</b><span>{s.name}</span></button>)}
      </div>
    </>}
    {kind === 'mine' && <>
      <div className="chip-row">
        {datasets.map(d => <span key={d.id} className="chip-pair">
          <button type="button" className="chip" aria-pressed={d.symbol === value} onClick={() => onSelect(datasetInfo(d))}><b>{d.name}</b><span>{d.bar_count} bars, {d.interval}</span></button>
          <button type="button" className="chip-x" aria-label={`Delete ${d.name}`} onClick={() => remove(d)}>x</button>
        </span>)}
      </div>
      <UploadBox onReady={d => { setDatasets(list => [d, ...list.filter(x => x.id !== d.id)]); onSelect(datasetInfo(d)); }}/>
    </>}
    {error && <p className="say bad">{error}</p>}
  </div>;
}
