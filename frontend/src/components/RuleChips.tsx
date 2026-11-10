import type { RuleChip } from '../api';

const TAG: Record<RuleChip['kind'], string> = { entry: 'BUY', exit: 'SELL', risk: 'RISK', size: 'SIZE' };

export function RuleChips({ rules }: { rules: RuleChip[] }) {
  if (rules.length === 0) return null;
  return <ul className="rule-chips" aria-label="Rules">
    {rules.map((rule, i) => <li key={`${rule.kind}-${i}`} className={`rule-chip rule-${rule.kind}`}>
      <b>{TAG[rule.kind]}</b><span>{rule.text}</span>
    </li>)}
  </ul>;
}
