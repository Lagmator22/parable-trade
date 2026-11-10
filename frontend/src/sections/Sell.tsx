import { fetchSeller, type Info, type Listing, type Me } from '../api';
import { bpsShort, signedBps, survivalPercent } from '../format';
import { LinkButton } from '../components/ui/Button';
import { Section } from '../components/ui/Section';
import { usePoll } from '../hooks/usePoll';
import { ListingForm } from './ListingForm';
import { MyListings } from './MyListings';

type Props = { me: Me | null; info: Info | null; listings: Listing[]; onChanged: () => void };

function SignIn({ mocked }: { mocked: boolean }) {
  return <div className="box signin-box">
    <div className="box-head"><strong>Sellers sign in with PayPal</strong>{mocked && <span>demo sign-in, PayPal is simulated</span>}</div>
    <p className="verdict-text">Signing in proves who gets paid. Parable pays you through PayPal Payouts when a bot you sold survives its probation. Your email stays private.</p>
    <div className="actions"><LinkButton variant="solid" href="/paypal/login">Sign in with PayPal</LinkButton></div>
  </div>;
}

function Profile({ sellerId }: { sellerId: string }) {
  const { data } = usePoll(() => fetchSeller(sellerId), { every: 6000, deps: [sellerId] });
  const record = data?.record;
  if (!record) return null;
  const survived = survivalPercent(record.survived, record.ended);
  return <dl className="stats five">
    <div><dt>Runs</dt><dd>{record.runs}</dd></div>
    <div><dt>Survived</dt><dd>{survived === null ? '–' : `${survived}%`}</dd></div>
    <div><dt>Avg return</dt><dd>{record.runs ? signedBps(record.avg_return_bps) : '–'}</dd></div>
    <div><dt>Worst return</dt><dd className={record.worst_return_bps < 0 ? 'down' : ''}>{record.runs ? signedBps(record.worst_return_bps) : '–'}</dd></div>
    <div><dt>Loss-limit deaths</dt><dd className={record.loss_limit ? 'down' : ''}>{record.loss_limit}</dd></div>
  </dl>;
}

export function Sell({ me, info, listings, onChanged }: Props) {
  const seller = me?.seller ?? null;
  const mine = listings.filter(item => item.seller.id === seller?.id || item.seller_id === seller?.id);
  return <Section id="sell" label="Sell">
    <h2>Sell a bot that has to prove itself.</h2>
    <p className="lead">List a bot with a promise. Buyers pay only when it survives. Platform fee: {info ? bpsShort(info.platform_fee_bps) : '10.0%'} of each paid sale. Failures stay on your record.</p>
    {!me && <p className="say">Checking your session…</p>}
    {me && !seller && <SignIn mocked={me.paypal_mode === 'mock'}/>}
    {seller && <>
      <p className="mono">Signed in as <strong>{seller.name}</strong>{seller.verified ? ' · PayPal verified' : ''} · {seller.email_masked}</p>
      <Profile sellerId={seller.id}/>
      {info && <ListingForm info={info} onCreated={onChanged}/>}
      <MyListings listings={mine} sellerId={seller.id} onChanged={onChanged}/>
    </>}
  </Section>;
}
