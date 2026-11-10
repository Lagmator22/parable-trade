type Props = { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void };

export function Slider({ label, value, min, max, step, unit = '', onChange }: Props) {
  return <label className="slider">
    <span className="slider-head"><span>{label}</span><b>{value}{unit}</b></span>
    <input type="range" min={min} max={max} step={step} value={value} aria-label={label} onChange={e => onChange(Number(e.target.value))}/>
  </label>;
}
