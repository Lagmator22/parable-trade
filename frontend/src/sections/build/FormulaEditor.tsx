import type { StrategySpec } from '../../api';
import { RuleChips } from '../../components/RuleChips';
import { Slider } from './Slider';
import type { Build } from './useBuild';

type Num = 'size_pct' | 'stop_loss_pct' | 'take_profit_pct' | 'trailing_stop_pct' | 'fee_bps' | 'slippage_bps';
const RISK: { key: Num; label: string; min: number; max: number; step: number; unit: string }[] = [
  { key: 'size_pct', label: 'Cash per trade', min: 1, max: 100, step: 1, unit: '%' },
  { key: 'stop_loss_pct', label: 'Stop loss', min: 0, max: 50, step: 0.5, unit: '%' },
  { key: 'take_profit_pct', label: 'Take profit', min: 0, max: 100, step: 1, unit: '%' },
  { key: 'trailing_stop_pct', label: 'Trailing stop', min: 0, max: 50, step: 0.5, unit: '%' },
  { key: 'fee_bps', label: 'Fee', min: 0, max: 200, step: 1, unit: ' bps' },
  { key: 'slippage_bps', label: 'Slippage', min: 0, max: 200, step: 1, unit: ' bps' },
];

export function FormulaEditor({ build, spec }: { build: Build; spec: StrategySpec }) {
  const set = (patch: Partial<StrategySpec>) => build.setSpec({ ...spec, ...patch, built_by: spec.built_by.startsWith('manual') ? spec.built_by : 'manual' });
  const errors = build.validation && !build.validation.ok ? build.validation.errors : [];
  const names = Object.keys(spec.params);
  return <div className="editor">
    <RuleChips rules={build.rules}/>
    {spec.summary && <p className="say">{spec.summary}</p>}
    <label className="field"><span className="field-label">Buy when</span>
      <textarea rows={2} value={spec.entry} spellCheck={false} onChange={e => set({ entry: e.target.value })}/></label>
    <label className="field"><span className="field-label">Sell when (empty = stops only)</span>
      <textarea rows={2} value={spec.exit} spellCheck={false} onChange={e => set({ exit: e.target.value })}/></label>
    <div role="status" className={`say ${errors.length ? 'bad' : ''}`}>
      {errors.length ? errors.map((m, i) => <div key={i}>{m}</div>) : build.validation?.ok ? 'Formulas are valid.' : 'Checking'}
    </div>
    {names.length > 0 && <div className="slider-grid" aria-label="Settings">
      {names.map(n => {
        const p = spec.params[n];
        return <Slider key={n} label={n} value={p.value} min={p.min} max={p.max} step={p.step} onChange={v => set({ params: { ...spec.params, [n]: { ...p, value: v } } })}/>;
      })}
    </div>}
    <div className="slider-grid" aria-label="Risk">
      {RISK.map(r => <Slider key={r.key} label={r.label} value={spec[r.key]} min={r.min} max={r.max} step={r.step} unit={r.unit} onChange={v => set({ [r.key]: v } as Partial<StrategySpec>)}/>)}
    </div>
  </div>;
}
