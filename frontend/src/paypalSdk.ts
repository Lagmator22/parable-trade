export type ApproveData = { orderID: string };

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

const loading = new Map<string, Promise<PayPalNamespace>>();

export const sdkUrl = (clientId: string) =>
  `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=USD&intent=authorize`;

export function loadPayPalSdk(clientId: string): Promise<PayPalNamespace> {
  const cached = loading.get(clientId);
  if (cached) return cached;
  const pending = new Promise<PayPalNamespace>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = sdkUrl(clientId);
    script.async = true;
    script.onload = () => (window.paypal ? resolve(window.paypal) : reject(new Error('PayPal SDK did not load')));
    script.onerror = () => reject(new Error('Could not reach PayPal'));
    document.head.append(script);
  });
  loading.set(clientId, pending);
  pending.catch(() => loading.delete(clientId));
  return pending;
}
