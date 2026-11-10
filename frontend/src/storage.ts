export type SavedPurchase = { purchase_id: string; buyer_token: string; approve_url: string; listing_title: string; saved_at: number };

const KEY = 'parable-purchases';

export function savedPurchases(): SavedPurchase[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function savePurchase(entry: SavedPurchase) {
  try {
    const others = savedPurchases().filter(item => item.purchase_id !== entry.purchase_id);
    localStorage.setItem(KEY, JSON.stringify([entry, ...others].slice(0, 50)));
  } catch {
    return;
  }
}

export const savedPurchase = (id: string) => savedPurchases().find(item => item.purchase_id === id);
