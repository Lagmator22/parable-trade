import { useState } from 'react';
import type { Listing } from '../api';
import { brainName, bpsShort, cents, duration, promise, signedBps, strategyName, survivalPercent } from '../format';
import { Button } from '../components/ui/Button';
import { Check } from '../components/ui/Glyphs';
import { Diligence } from './Diligence';

type Props = { listing: Listing; onBuy: (listing: Listing) => void; note?: string };

function RecordMini({ listing }: { listing: Listing }) {
  const record = listing.seller_record;
  const survived = survivalPercent(record.survived, record.ended);
  return <dl className="record">
    <div><dt>Runs</dt><dd>{record.runs}</dd></div>
    <div><dt>Survived</dt><dd>{survived === null ? '–' : `${survived}%`}</dd></div>
    <div><dt>Worst</dt><dd className={record.worst_return_bps < 0 ? 'down' : ''}>{record.runs ? signedBps(record.worst_return_bps) : '–'}</dd></div>
    <div><dt>Probation</dt><dd><span className="up">{record.probation_passed}</span> / <span className="down">{record.probation_failed}</span></dd></div>
  </dl>;
}

export function ListingCard({ listing, onBuy, note }: Props) {
  const [showReport, setShowReport] = useState(false);
  const thin = listing.seller_record.runs < 3;
  return <article className="listing box">
    <div className="listing-top">
      <div>
        <h3>{listing.title}</h3>
        <p className="by mono">
          {listing.seller.name}
          {listing.seller.verified && <span className="verified"><Check size={14}/>PayPal verified</span>}
        </p>
      </div>
      <p className="price">{cents(listing.price_cents)}</p>
    </div>
    {note && <p className="note">{note}</p>}
    <p className="pitch">{listing.pitch}</p>
    <ul className="tags mono">
      <li>{brainName(listing.rules.brain)}</li>
      <li>{strategyName(listing.rules.strategy)}</li>
      <li>{duration(listing.probation_s)} probation</li>
      <li>stops at {bpsShort(listing.rules.max_loss_bps)} loss</li>
      {thin && <li className="thin">thin record</li>}
    </ul>
    <p className="promise">{promise(listing.probation_s, listing.min_return_bps)}.</p>
    <RecordMini listing={listing}/>
    <div className="listing-actions">
      <Button variant="quiet" aria-expanded={showReport} onClick={() => setShowReport(open => !open)}>AI due diligence</Button>
      <Button variant="solid" onClick={() => onBuy(listing)}>Buy with PayPal</Button>
    </div>
    {showReport && <Diligence listingId={listing.id}/>}
  </article>;
}

