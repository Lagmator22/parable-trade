import { useState } from 'react';
import type { Info, Me } from '../../api';
import { Button } from '../../components/ui/Button';
import { SellDialog } from './SellDialog';
import { StepMarket } from './StepMarket';
import { StepStrategy } from './StepStrategy';
import { StepTest } from './StepTest';
import { useBuild } from './useBuild';

type Props = { agentId: string; me: Me | null; info: Info | null | undefined; onMe?: () => void };

function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children: React.ReactNode }) {
  return <section className="build-step box" aria-label={title}>
    <header className="box-head"><strong><span className="step-n">{n}</span> {title}</strong>{done && <span className="up mono">done</span>}</header>
    {children}
  </section>;
}

export function BuildPage({ agentId, me, info }: Props) {
  const build = useBuild(agentId);
  const [selling, setSelling] = useState(false);
  const signedIn = Boolean(me?.seller);

  return <div className="wrap build">
    <h1 className="build-title">Build an agent</h1>
    <Step n={1} title="Market" done={Boolean(build.market)}><StepMarket build={build}/></Step>
    <Step n={2} title="Strategy" done={Boolean(build.spec && build.validation?.ok)}><StepStrategy build={build} info={info ?? null}/></Step>
    <Step n={3} title="Test" done={Boolean(build.result)}><StepTest build={build}/></Step>
    <div className="build-bar box">
      <div className="actions">
        <Button variant="solid" disabled={!build.spec || build.validation?.ok !== true || build.saving || !signedIn} onClick={() => { build.save(); }}>
          {build.saving ? 'Saving' : build.isSaved ? 'Saved' : 'Save version'}
        </Button>
        <Button disabled={!build.isSaved} onClick={() => setSelling(true)}>Sell</Button>
        {!signedIn && <a className="link-btn" href="/paypal/login">Sign in to save</a>}
      </div>
      {build.error && <p className="say bad" role="alert">{build.error}</p>}
    </div>
    {selling && <SellDialog build={build} onClose={() => setSelling(false)}/>}
  </div>;
}
