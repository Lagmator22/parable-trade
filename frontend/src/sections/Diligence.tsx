import { useEffect, useState } from 'react';
import { fetchDiligence, type Diligence as Report } from '../api';
import { brainName } from '../format';

export function RiskBadge({ risk }: { risk: Report['risk'] }) {
  return <span className={`badge risk-${risk}`}>{risk} risk</span>;
}

export function Diligence({ listingId }: { listingId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    fetchDiligence(listingId)
      .then(next => { if (!cancelled) setReport(next); })
      .catch(failure => { if (!cancelled) setError(failure.message); });
    return () => { cancelled = true; };
  }, [listingId]);

  if (error) return <div className="diligence"><p className="say bad">{error}</p></div>;
  if (!report) return <div className="diligence"><p className="say">Reading the seller’s full record…</p></div>;
  return <div className="diligence" aria-live="polite">
    <div className="diligence-head"><RiskBadge risk={report.risk}/><strong>{report.headline}</strong></div>
    <ul className="findings">{report.findings.map(finding => <li key={finding}>{finding}</li>)}</ul>
    {report.red_flags.length > 0 && <ul className="findings flags">{report.red_flags.map(flag => <li key={flag}>{flag}</li>)}</ul>}
    <p className="say">Written by {report.by === 'rules' ? 'fixed rules' : brainName(report.by)} from the public record only.</p>
  </div>;
}
