import { useEffect, useState } from 'react';
import { ApiError, compileSteps, fetchModels, fetchQuestions, fetchTemplate, type CompileRequest, type FreeTries, type Info, type ModelInfo, type Question, type Template } from '../../api';
import { hasOwnKey, loadAiSettings } from '../../aiSettings';
import { Button } from '../../components/ui/Button';
import { FormulaEditor } from './FormulaEditor';
import type { Build } from './useBuild';

export function StepStrategy({ build, info }: { build: Build; info: Info | null }) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState('');
  const [tries, setTries] = useState<FreeTries | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const own = hasOwnKey(loadAiSettings());
  const templates: Template[] = info?.templates ?? [];
  const { market, spec } = build;

  useEffect(() => {
    fetchQuestions().then(setQuestions).catch(() => setQuestions([]));
    fetchModels().then(m => {
      const ok = m.platform.filter(x => x.available);
      setModels(ok);
      setModel(cur => cur || ok[0]?.id || '');
      setTries(m.free_tries);
    }).catch(() => setModels([]));
  }, []);

  async function run(label: string, req: Omit<CompileRequest, 'symbol' | 'interval'>) {
    if (!market) { setError('Pick a market first.'); return; }
    setBusy(label);
    setError('');
    try {
      const response = await compileSteps({ ...req, symbol: market.symbol, interval: build.interval });
      build.applyCompile(response);
      setTries(response.free_tries);
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'free_tries_used' ? 'Free tries used up. Add your own key in AI settings.' : e instanceof Error ? e.message : 'Build failed');
    }
    setBusy('');
  }

  async function template(t: Template) {
    if (!market) { setError('Pick a market first.'); return; }
    setBusy(`t:${t.id}`);
    setError('');
    try {
      build.applyCompile(await fetchTemplate(t.id, market.symbol, build.interval));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the template');
    }
    setBusy('');
  }

  const ready = questions.length > 0 && questions.every(q => answers[q.id]);

  return <div className="step-body">
    {templates.length > 0 && <div className="cards" aria-label="Templates">
      {templates.map(t => <button key={t.id} type="button" className="card-pick" disabled={!market || Boolean(busy)} aria-pressed={spec?.built_by === `template:${t.id}`} onClick={() => template(t)}>
        <b>{t.label}</b><span>{t.blurb}</span>
      </button>)}
    </div>}
    <label className="field"><span className="field-label">Describe your steps</span>
      <textarea rows={3} value={build.steps} onChange={e => build.setSteps(e.target.value)} placeholder="Buy when the price dips 3 percent, sell after a 5 percent gain"/></label>
    <div className="actions">
      <Button variant="solid" disabled={!market || !build.steps.trim() || Boolean(busy)} onClick={() => run('ai', { steps: build.steps, model: own ? undefined : model || undefined, base: spec ?? undefined })}>
        {busy === 'ai' ? 'Building' : 'Build with AI'}
      </Button>
      {!own && models.length > 0 && <label className="inline-select"><span className="field-label">Model</span>
        <select value={model} onChange={e => setModel(e.target.value)} aria-label="Model">{models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>}
      {own ? <span className="badge">your key</span> : tries && <span className="badge">{tries.remaining}/{tries.limit} free today</span>}
    </div>
    {questions.length > 0 && <details className="quiz">
      <summary>Or answer 4 questions</summary>
      {questions.map(q => <fieldset key={q.id}><legend>{q.text}</legend>
        <div className="chip-row">{q.options.map(o => <button key={o.id} type="button" className="chip" aria-pressed={answers[q.id] === o.id} onClick={() => setAnswers({ ...answers, [q.id]: o.id })}><b>{o.label}</b></button>)}</div>
      </fieldset>)}
      <Button disabled={!ready || !market || Boolean(busy)} onClick={() => run('quiz', { answers })}>Build from answers</Button>
    </details>}
    {error && <p className="say bad" role="alert">{error}</p>}
    {spec && <FormulaEditor build={build} spec={spec}/>}
  </div>;
}
