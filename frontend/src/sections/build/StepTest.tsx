import { useState } from 'react';
import { BacktestPanel } from './BacktestPanel';
import { BenchmarkPanel } from './BenchmarkPanel';
import { LivePanel } from './LivePanel';
import { OptimizePanel } from './OptimizePanel';
import { ReplayPanel } from './ReplayPanel';
import type { Build } from './useBuild';

const TABS = [['backtest', 'Backtest'], ['benchmark', 'Benchmark models'], ['optimize', 'Find best'], ['replay', 'Replay'], ['live', 'Go live']] as const;
type Tab = (typeof TABS)[number][0];

export function StepTest({ build }: { build: Build }) {
  const [tab, setTab] = useState<Tab>('backtest');
  if (!build.spec) return <div className="step-body"><p className="empty">Build a strategy to test it.</p></div>;
  return <div className="step-body">
    <div className="toggle tabs" role="tablist" aria-label="Tests">
      {TABS.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    {tab === 'backtest' && <BacktestPanel build={build}/>}
    {tab === 'benchmark' && <BenchmarkPanel build={build}/>}
    {tab === 'optimize' && <OptimizePanel build={build}/>}
    {tab === 'replay' && <ReplayPanel build={build}/>}
    {tab === 'live' && <LivePanel build={build}/>}
  </div>;
}
