import { expect, test } from 'vitest';
import { buildPayload, emptyForm } from './listingForm';

const valid = { ...emptyForm('momentum', 'rule'), title: 'Steady Eddie', pitch: 'A careful bot that trades small.' };

test('converts the form into the API payload units', () => {
  const built = buildPayload(valid);
  expect(built).toEqual({
    ok: true,
    payload: {
      title: 'Steady Eddie', pitch: 'A careful bot that trades small.', strategy: 'momentum', brain: 'rule',
      max_trade_usd: 250_000_000, max_loss_bps: 300, price_cents: 2500, probation_s: 600, min_return_bps: -100,
    },
  });
});

test('rejects out of range and non numeric values', () => {
  expect(buildPayload({ ...valid, price: '0' })).toMatchObject({ ok: false });
  expect(buildPayload({ ...valid, price: '501' })).toMatchObject({ ok: false });
  expect(buildPayload({ ...valid, probationMinutes: '4321' })).toMatchObject({ ok: false });
  expect(buildPayload({ ...valid, minReturnPercent: '6' })).toMatchObject({ ok: false });
  expect(buildPayload({ ...valid, lossLimitPercent: 'abc' })).toMatchObject({ ok: false, error: 'Loss limit (%) must be a number.' });
  expect(buildPayload({ ...valid, title: 'ab' })).toMatchObject({ ok: false });
  expect(buildPayload({ ...valid, pitch: 'short' })).toMatchObject({ ok: false });
});
