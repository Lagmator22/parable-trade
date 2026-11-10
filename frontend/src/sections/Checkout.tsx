import { useEffect, useRef, useState } from 'react';
import { approvePurchase, startPurchase, type Info, type Listing, type NewPurchase } from '../api';
import { bpsShort, cents, duration, promise } from '../format';
import { Button } from '../components/ui/Button';
import { Lock } from '../components/ui/Glyphs';
import { loadPayPalSdk } from '../paypalSdk';
import { savePurchase } from '../storage';

type Props = {
  listing: Listing;
  info: Info;
  onClose: () => void;
  onDone?: (purchaseId: string) => void;
  navigate?: (url: string) => void;
};

const goTo = (url: string) => window.location.assign(url);
const openTracker = (purchaseId: string) => { window.location.hash = `#purchase/${purchaseId}`; };

export function Checkout({ listing, info, onClose, onDone = openTracker, navigate = goTo }: Props) {
  const mocked = info.paypal_mode === 'mock';
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const created = useRef<NewPurchase | null>(null);
  const container = useRef<HTMLDivElement>(null);

  async function createPurchase(): Promise<NewPurchase> {
    const purchase = await startPurchase(listing.id);
    created.current = purchase;
    savePurchase({ purchase_id: purchase.purchase_id, buyer_token: purchase.buyer_token, approve_url: purchase.approve_url, listing_title: listing.title, saved_at: Date.now() });
    return purchase;
  }

  async function paySimulated() {
    setBusy(true);
    setError('');
    try {
      const purchase = await createPurchase();
      navigate(purchase.approve_url);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not start the purchase.');
      setBusy(false);
    }
  }

  useEffect(() => {
    if (mocked || !info.paypal_client_id || !container.current) return;
    let cancelled = false;
    const host = container.current;
    loadPayPalSdk(info.paypal_client_id)
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
          onError: () => setError('PayPal could not complete the approval. Nothing was charged.'),
        }).render(host).then(() => { if (!cancelled) setReady(true); });
      })
      .catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : 'PayPal is unavailable.'); });
    return () => { cancelled = true; };
  }, [mocked, info.paypal_client_id, listing.id]);

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
        <p className="by mono">by {listing.seller.name}</p>
        <dl className="summary">
          <div><dt>Price</dt><dd>{cents(listing.price_cents)}</dd></div>
          <div><dt>Charged now</dt><dd>$0.00</dd></div>
          <div><dt>Held in PayPal</dt><dd>{cents(listing.price_cents)}</dd></div>
          <div><dt>Probation</dt><dd>{duration(listing.probation_s)}</dd></div>
          <div><dt>Loss limit</dt><dd>{bpsShort(listing.rules.max_loss_bps)}</dd></div>
        </dl>
        <p className="promise"><Lock size={16}/> {promise(listing.probation_s, listing.min_return_bps)}. Otherwise PayPal voids the hold and you are never charged.</p>
        {mocked
          ? <Button variant="solid" disabled={busy} onClick={paySimulated}>Pay with PayPal (simulated)</Button>
          : <>
            {!ready && !error && <p className="say">Loading PayPal…</p>}
            <div ref={container} className="paypal-buttons" aria-label="PayPal checkout"/>
          </>}
        {mocked && <p className="say">PayPal sandbox keys are not set, so this opens a simulated PayPal approval page.</p>}
        {error && <p className="say bad" role="alert">{error}</p>}
      </div>
    </div>
  </div>;
}
