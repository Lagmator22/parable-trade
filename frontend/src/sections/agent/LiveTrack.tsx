import { useState } from 'react';
import type { Track } from '../../api';
import { duration, pct } from '../../format';
import { LivePill } from '../../components/Pills';
import { RunChart } from './RunChart';

export function LiveTrack({ track }: { track: Track }) {
  const [points, setPoints] = useState(0);
  const alive = track.status === 'alive';
  const early = track.runs_ended_early;
  return <section className="box agent-block" aria-label="Live track">
    <div className="box-head"><strong>Live track vs market</strong><LivePill track={track}/></div>
    <dl className="nums wide">
      <div><dt>Since start</dt><dd className={track.equity_pct >= 0 ? 'up' : 'down'}>{pct(track.equity_pct, 2)}</dd></div>
      <div><dt>Running</dt><dd>{duration(track.seconds)}</dd></div>
      <div><dt>Points</dt><dd>{Math.max(points, track.points)}</dd></div>
      <div><dt>Ended early</dt><dd className={early ? 'down' : ''}>{early} of {track.runs_total}</dd></div>
    </dl>
    <div className="block-body">
      <RunChart runId={track.run_id} alive={alive} label="Live track equity against buy and hold" onCount={setPoints}/>
      <p className="chart-note">Paper money on live prices. Solid: the agent. Dashed: just holding. Every restart is counted, deaths included.</p>
    </div>
  </section>;
}
