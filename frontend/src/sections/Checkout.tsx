import { useEffect, useRef, useState } from 'react';
import { approvePurchase, startPurchase, type Info, type Me, type NewPurchase, type PublicListing } from '../api';
import { cents, duration, promise } from '../format';
import { Button } from '../components/ui/Button';
import { Lock } from '../components/ui/Glyphs';
import { ModePill } from '../components/Pills';
import { loadPayPalSdk } from '../paypalSdk';
import { goSignIn } from '../signIn';

type Props = {
  listing: PublicListing;
  info: Info;
  me: Me | null;
  onClose: () => void;
  onDone?: (purchaseId: string) => void;
  navigate?: (url: string) => void;
};

const goTo = (url: string) => window.location.assign(url);
const openTracker = (purchaseId: string) => { window.location.hash = `#purchase/${purchaseId}`; };

function Summary({ listing }: { listing: PublicListing }) {
  const hold = listing.mode === 'hold';
  return <dl className="summary">
    <div><dt>Price</dt><dd>{cents(listing.price_cents)}</dd></div>
    <div><dt>Charged now</dt><dd>{hold ? '$0.00' : cents(listing.price_cents)}</dd></div>
    {hold && <div><dt>Held in PayPal</dt><dd>{cents(listing.price_cents)}</dd></div>}
    {hold && <div><dt>Live trial</dt><dd>{duration(listing.trial_s)}</dd></div>}
    {hold && <div><dt>Loss limit</dt><dd>{(listing.max_loss_bps / 100).toFixed(1)}%</dd></div>}
    {!hold && <div><dt>You get</dt><dd>Agent file at once</dd></div>}
  </dl>;
}

export function Checkout({ listing, info, me, onClose, onDone = openTracker, navigate = goTo }: Props) {
  const mocked = info.paypal_mode === 'mock';
  const hold = listing.mode === 'hold';
  const signedIn = Boolean(me?.seller);
  const own = Boolean(me?.seller && me.seller.id === listing.seller.id);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const created = useRef<NewPurchase | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const canPay = signedIn && !own;

  async function createPurchase(): Promise<NewPurchase> {
    const purchase = await startPurchase(listing.id);
    created.current = purchase;
    return purchase;
  }

  async function paySimulated() {
    setBusy(true);
    setError('');
    try {
      navigate((await createPurchase()).approve_url);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not start the purchase.');
      setBusy(false);
    }
  }

  useEffect(() => {
    if (mocked || !canPay || !info.paypal_client_id || !container.current) return;
    let cancelled = false;
    const host = container.current;
    loadPayPalSdk(info.paypal_client_id, hold ? 'authorize' : 'capture')
      .then(paypal => {
        if (cancelled) return;
        host.replaceChildren();
        return paypal.Buttons({
          style: { layout: 'vertical', shape: 'rect', label: 'pay' },
          createOrder: async () => (await createPurchase()).paypal_order_id,
          onApprove: async data => {
            const purchase = created.current;
            if (!purchase) return;
            await approvePurchase(purchase.purchase_id, data.orderID);
            onClose();
            onDone(purchase.purchase_id);
          },
          onCancel: () => setError('Checkout cancelled. Nothing was charged.'),
          onError: () => setError('PayPal could not finish. Nothing was charged.'),
        }).render(host).then(() => { if (!cancelled) setReady(true); });
      })
      .catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : 'PayPal is unavailable.'); });
    return () => { cancelled = true; };
  }, [mocked, canPay, hold, info.paypal_client_id, listing.id]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [onClose]);

  return <div className="scrim" onClick={onClose}>
    <div className="dialog box" role="dialog" aria-modal="true" aria-labelledby="checkout-title" onClick={event => event.stopPropagation()}>
      <div className="box-head"><strong id="checkout-title">Checkout</strong><button type="button" className="link-btn" onClick={onClose}>Close</button></div>
      <div className="dialog-body">
        <h3>{listing.title}</h3>
        <div className="pill-row"><ModePill mode={listing.mode}/><span className="pill">by {listing.seller.name}</span></div>
        <Summary listing={listing}/>
        <p className="promise"><Lock size={16}/> {hold ? `${promise(listing.trial_s, listing.min_return_bps)}. Otherwise the hold is voided.` : 'One payment. The seller is paid at once.'}</p>
        {!signedIn && <>
          <p className="say">Sign in with PayPal to buy.</p>
          <Button variant="solid" className="big" onClick={() => goSignIn(navigate)}>Sign in with PayPal</Button>
        </>}
        {own && <p className="say bad" role="alert">This is your own listing.</p>}
        {canPay && (mocked
          ? <Button variant="solid" className="big" disabled={busy} onClick={paySimulated}>Pay with PayPal (simulated)</Button>
          : <>
            {!ready && !error && <p className="say">Loading PayPal</p>}
            <div ref={container} className="paypal-buttons" aria-label="PayPal checkout"/>
          </>)}
        {canPay && mocked && <p className="say">No PayPal keys set, so approval is simulated.</p>}
        {error && <p className="say bad" role="alert">{error}</p>}
      </div>
    </div>
  </div>;
}
