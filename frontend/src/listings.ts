import type { Listing } from './api';
import { survivalPercent } from './format';

export type SortMode = 'record' | 'cheapest' | 'newest';

export const SORT_LABELS: Record<SortMode, string> = { record: 'Best record', cheapest: 'Cheapest', newest: 'Newest' };

const survival = (listing: Listing) => survivalPercent(listing.seller_record.survived, listing.seller_record.ended) ?? -1;

export function sortListings(listings: Listing[], mode: SortMode): Listing[] {
  const copy = [...listings];
  if (mode === 'cheapest') return copy.sort((a, b) => a.price_cents - b.price_cents);
  if (mode === 'newest') return copy.sort((a, b) => b.created_at - a.created_at);
  return copy.sort((a, b) => survival(b) - survival(a) || b.seller_record.runs - a.seller_record.runs);
}
