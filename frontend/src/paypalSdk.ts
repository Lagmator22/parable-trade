export type ApproveData = { orderID: string };
export type SdkIntent = 'authorize' | 'capture';

export type ButtonsConfig = {
  style?: Record<string, string | number | boolean>;
  createOrder: () => Promise<string>;
  onApprove: (data: ApproveData) => Promise<void>;
  onCancel?: () => void;
  onError?: (error: unknown) => void;
};

export type PayPalNamespace = {
  Buttons: (config: ButtonsConfig) => { render: (container: HTMLElement) => Promise<void>; close?: () => void };
};

declare global {
  interface Window { paypal?: PayPalNamespace }
}

let loaded: { key: string; promise: Promise<PayPalNamespace> } | null = null;

export const sdkUrl = (clientId: string, intent: SdkIntent) =>
  `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=USD&intent=${intent}`;

export function loadPayPalSdk(clientId: string, intent: SdkIntent = 'authorize'): Promise<PayPalNamespace> {
  const key = `${clientId}:${intent}`;
  if (loaded?.key === key) return loaded.promise;
  document.querySelectorAll('script[data-parable-paypal]').forEach(node => node.remove());
  delete window.paypal;
  const promise = new Promise<PayPalNamespace>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = sdkUrl(clientId, intent);
    script.async = true;
    script.dataset.parablePaypal = intent;
    script.onload = () => (window.paypal ? resolve(window.paypal) : reject(new Error('PayPal SDK did not load')));
    script.onerror = () => reject(new Error('Could not reach PayPal'));
    document.head.append(script);
  });
  loaded = { key, promise };
  promise.catch(() => { if (loaded?.promise === promise) loaded = null; });
  return promise;
}
