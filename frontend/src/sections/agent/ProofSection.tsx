import type { ProofView } from '../../api';
import { dateTime, shortHash } from '../../format';
import { MetricsGrid } from '../../components/MetricsGrid';
import { ProofChart } from '../../components/ProofChart';
import { DataPill } from '../../components/Pills';

export function ProofSection({ proof, title = 'Backtest proof', note = '' }: { proof: ProofView; title?: string; note?: string }) {
  const info = proof.data;
  return <section className="box agent-block" aria-label={title}>
    <div className="box-head"><strong>{title}</strong><DataPill kind={info.source_kind}/></div>
    <div className="block-body">
      {(note || proof.verifiable === false) && <p className="say bad" role="note">{note || 'Creator-supplied data, cannot be independently checked.'}</p>}
      <ProofChart curve={proof.curve} quote={info.quote} label={title} percent/>
      <MetricsGrid metrics={proof.metrics} quote={info.quote}/>
      <dl className="facts-line mono">
        <div><dt>Data</dt><dd>{info.bars} bars, {dateTime(info.start)} to {dateTime(info.end)}</dd></div>
        {proof.assumptions && <div><dt>Costs assumed</dt><dd>fee {proof.assumptions.fee_bps} bps, slippage {proof.assumptions.slippage_bps} bps per trade</dd></div>}
        <div><dt>Data hash</dt><dd title={info.data_hash}>{shortHash(info.data_hash, 12)}</dd></div>
        <div><dt>Result hash</dt><dd title={proof.result_hash}>{shortHash(proof.result_hash, 12)}</dd></div>
        <div><dt>Engine</dt><dd>{proof.engine_version}</dd></div>
        {proof.ledger_seq !== null && <div><dt>Ledger</dt><dd><a href="#ledger">#{proof.ledger_seq}</a></dd></div>}
      </dl>
    </div>
  </section>;
}
