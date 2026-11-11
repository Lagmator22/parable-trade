import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError, backtestVersion, createAgent, fetchAgent, fetchVersion, saveVersion, validateSpec,
  type BacktestResult, type CompileResponse, type DataRequest, type RuleChip, type StrategySpec, type SymbolInfo, type Validation,
} from '../../api';
import { clearDraft, loadDraft, saveDraft } from '../../aiSettings';

export type Saved = { agentId: string; versionId: string; proofId: string; key: string };

export const pickInterval = (intervals: string[]) => (intervals.includes('1h') ? '1h' : intervals.includes('1d') ? '1d' : intervals[0] ?? '1d');
export function summaryOf(spec: StrategySpec, rules: RuleChip[]): string {
  const edited = (spec.built_by ?? '').startsWith('manual');
  const live = rules.filter(r => r.kind === 'entry' || r.kind === 'exit').map(r => r.text).join('. ');
  return edited && live ? live : spec.summary;
}
export const uploadId = (symbol: string) => (symbol.startsWith('upload:') ? symbol.slice(7) : undefined);
export const withMarket = (spec: StrategySpec, symbol: string, interval: string): StrategySpec => ({ ...spec, symbol, interval });

function placeholder(symbol: string, interval: string): SymbolInfo {
  const provider = symbol.split(':')[0] ?? '';
  return { symbol, name: symbol.split(':')[1] ?? symbol, kind: provider === 'upload' ? 'mine' : 'crypto', quote: '', provider, intervals: [interval], live: provider !== 'upload' && provider !== 'sample' };
}

export function useBuild(agentId: string) {
  const [market, setMarketState] = useState<SymbolInfo | null>(null);
  const [interval, setIntervalState] = useState('1h');
  const [spec, setSpecState] = useState<StrategySpec | null>(null);
  const [steps, setSteps] = useState('');
  const [rules, setRules] = useState<RuleChip[]>([]);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [result, setResultState] = useState<{ key: string; value: BacktestResult } | null>(null);
  const [saved, setSaved] = useState<Saved | null>(agentId ? { agentId, versionId: '', proofId: '', key: '' } : null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const latest = useRef({ spec, saved, market, interval, steps });
  latest.current = { spec, saved, market, interval, steps };

  const specKey = useMemo(() => (spec ? JSON.stringify(spec) : ''), [spec]);

  useEffect(() => {
    if (agentId) {
      fetchAgent(agentId).then(async agent => {
        setMarketState(placeholder(agent.symbol, agent.interval));
        setIntervalState(agent.interval);
        if (!agent.latest_version_id) return;
        const version = await fetchVersion(agentId, agent.latest_version_id);
        setSpecState(version.spec);
        setSteps(version.steps_text);
        setSaved({ agentId, versionId: version.id, proofId: '', key: JSON.stringify(version.spec) });
      }).catch(e => setError(e instanceof Error ? e.message : 'Could not load this agent'));
      return;
    }
    const draft = loadDraft();
    if (draft?.spec) {
      const d = draft.spec as StrategySpec;
      setSpecState(d);
      setSteps(draft.steps ?? '');
      setMarketState(placeholder(d.symbol, d.interval));
      setIntervalState(d.interval);
    }
  }, [agentId]);

  useEffect(() => {
    if (agentId || !spec) return;
    saveDraft({ spec, steps });
  }, [agentId, spec, steps]);

  useEffect(() => {
    if (!spec) { setValidation(null); return; }
    let live = true;
    const timer = window.setTimeout(() => {
      validateSpec(spec).then(v => { if (live) { setValidation(v); if (v.ok && v.rules.length) setRules(v.rules); } })
        .catch(e => { if (live) setValidation({ ok: false, errors: [e instanceof Error ? e.message : 'Check failed'], spec_hash: '', rules: [] }); });
    }, 350);
    return () => { live = false; window.clearTimeout(timer); };
  }, [specKey]);

  const setMarket = useCallback((info: SymbolInfo) => {
    const next = pickInterval(info.intervals);
    setMarketState(info);
    setIntervalState(next);
    setSpecState(s => (s ? withMarket(s, info.symbol, next) : s));
  }, []);

  const setInterval = useCallback((value: string) => {
    setIntervalState(value);
    setSpecState(s => (s ? withMarket(s, s.symbol, value) : s));
  }, []);

  const setSpec = useCallback((next: StrategySpec) => setSpecState(next), []);

  const applyCompile = useCallback((response: CompileResponse) => {
    const m = latest.current;
    setSpecState(m.market ? withMarket(response.spec, m.market.symbol, m.interval) : response.spec);
    setRules(response.rules);
  }, []);

  const data: DataRequest | null = market ? { symbol: market.symbol, interval, dataset_id: uploadId(market.symbol), limit: 2000 } : null;

  const save = useCallback(async (): Promise<Saved | null> => {
    const m = latest.current;
    if (!m.spec) return null;
    setSaving(true);
    setError('');
    try {
      let id = m.saved?.agentId ?? '';
      if (!id) {
        const agent = await createAgent(m.spec.name || 'My agent', m.spec.symbol, m.spec.interval);
        id = agent.id;
        window.history.replaceState(null, '', `#build/${id}`);
      }
      const version = await saveVersion(id, m.spec, m.steps, m.spec.built_by);
      const proof = await backtestVersion(id, version.id, { symbol: m.spec.symbol, interval: m.spec.interval, dataset_id: uploadId(m.spec.symbol), limit: 2000 });
      const next = { agentId: id, versionId: version.id, proofId: proof.id, key: JSON.stringify(m.spec) };
      setSaved(next);
      clearDraft();
      return next;
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? 'Sign in with PayPal to save.' : e instanceof Error ? e.message : 'Save failed');
      return null;
    } finally {
      setSaving(false);
    }
  }, []);

  const ensureAgent = useCallback(async (): Promise<string> => {
    const m = latest.current;
    if (m.saved?.agentId) return m.saved.agentId;
    if (!m.spec) throw new Error('Build a strategy first');
    const agent = await createAgent(m.spec.name || 'My agent', m.spec.symbol, m.spec.interval);
    setSaved({ agentId: agent.id, versionId: '', proofId: '', key: '' });
    window.history.replaceState(null, '', `#build/${agent.id}`);
    return agent.id;
  }, []);

  const adopt = useCallback((next: StrategySpec, versionId: string, agent: string) => {
    setSpecState(next);
    setSaved({ agentId: agent, versionId, proofId: '', key: JSON.stringify(next) });
  }, []);

  const isSaved = Boolean(saved?.versionId && saved.key === specKey && saved.proofId);
  const live = Boolean(saved?.versionId && saved.key === specKey);
  const current = result && result.key === specKey ? result.value : null;
  const setResult = useCallback((value: BacktestResult) => setResultState({ key: latest.current.spec ? JSON.stringify(latest.current.spec) : '', value }), []);

  return {
    market, interval, spec, steps, rules, validation, result: current, saved, saving, error, data, specKey,
    isSaved, live, setMarket, setInterval, setSpec, setSteps, setRules, applyCompile, save, ensureAgent, adopt, setResult, setError,
  };
}

export type Build = ReturnType<typeof useBuild>;
