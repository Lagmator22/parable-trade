import { afterEach, expect, test, vi } from 'vitest';
import { ListingCard } from './sections/ListingCard';
import { instantListing, listing } from './test/fixtures';
import { mount } from './test/mount';

afterEach(() => vi.unstubAllGlobals());

test('shows the headline numbers, badges, live dot and price', async () => {
  const view = await mount(<ListingCard listing={listing} onBuy={() => {}}/>);
  const text = view.host.textContent ?? '';
  expect(text).toContain('Momentum Mule');
  expect(text).toContain('$25.00');
  expect(text).toContain('+12.5%');
  expect(text).toContain('+4.0%');
  expect(text).toContain('-6.0%');
  expect(text).toContain('57%');
  expect(text).toContain('Pay if proven');
  expect(text).toContain('Real data');
  expect(text).toContain('Gemini 3.5 Flash Lite');
  expect(view.host.querySelector('.live-pill')).not.toBeNull();
  expect(view.host.querySelector('svg.spark path.spark-line')).not.toBeNull();
  expect(view.host.querySelector('svg.spark path.spark-hold')).not.toBeNull();
  await view.unmount();
});

test('an instant listing without a live track has no live dot', async () => {
  const view = await mount(<ListingCard listing={instantListing} onBuy={() => {}}/>);
  expect(view.host.textContent).toContain('Instant');
  expect(view.host.querySelector('.live-pill')).toBeNull();
  await view.unmount();
});

test('links to the agent page and hands the listing to the buy handler', async () => {
  const onBuy = vi.fn();
  const view = await mount(<ListingCard listing={listing} onBuy={onBuy}/>);
  expect(view.host.querySelector('h3 a')?.getAttribute('href')).toBe(`#agent/${listing.id}`);
  const buy = [...view.host.querySelectorAll('button')].find(button => button.textContent?.startsWith('Buy'));
  await view.click(buy!);
  expect(onBuy).toHaveBeenCalledWith(listing);
  await view.unmount();
});
