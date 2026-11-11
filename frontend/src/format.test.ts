import { expect, test } from 'vitest';
import { builtBy, instantOnly, pct, ago, bps, bpsShort, brainName, cents, countdown, duration, mask, promise, signedBps, usdMicro } from './format';

test('formats cents as dollars', () => {
  expect(cents(2500)).toBe('$25.00');
  expect(cents(123456)).toBe('$1,234.56');
  expect(cents(0)).toBe('$0.00');
  expect(cents(-150)).toBe('-$1.50');
});

test('formats micro dollars', () => {
  expect(usdMicro(1_000_000_000)).toBe('$1,000.00');
  expect(usdMicro(1_500_000)).toBe('$1.50');
  expect(usdMicro(0)).toBe('$0.00');
});

test('formats basis points as percentages', () => {
  expect(bps(100)).toBe('1.00%');
  expect(bps(-300)).toBe('-3.00%');
  expect(bpsShort(100)).toBe('1.0%');
  expect(signedBps(150)).toBe('+1.50%');
  expect(signedBps(-50)).toBe('-0.50%');
  expect(signedBps(0)).toBe('0.00%');
});

test('prettifies brain and strategy names', () => {
  expect(brainName('rule')).toBe('Simple rule');
  expect(brainName('claude:claude-haiku-5-5')).toBe('Claude Haiku 5.5');
  expect(brainName('gemini:gemini-3.5-flash-lite')).toBe('Gemini 3.5 Flash Lite');
  expect(brainName('jev:gemma-4-31b-it')).toBe('Jev Gemma 4 31b it');
  expect(brainName('mystery')).toBe('Mystery');
});

test('formats durations and countdowns', () => {
  expect(duration(45)).toBe('45 s');
  expect(duration(600)).toBe('10 min');
  expect(duration(90)).toBe('1 min 30 s');
  expect(duration(5400)).toBe('1 h 30 min');
  expect(duration(259200)).toBe('3 days');
  expect(duration(-5)).toBe('0 s');
  expect(countdown(61)).toBe('01:01');
  expect(countdown(3725)).toBe('01:02:05');
  expect(countdown(90061)).toBe('1d 01:01:01');
  expect(countdown(-3)).toBe('00:00');
});

test('writes the promise for each kind of threshold', () => {
  expect(promise(600, -100)).toBe('Pays only if it survives 10 min and loses no more than 1.0%');
  expect(promise(600, 0)).toBe('Pays only if it survives 10 min and finishes at break-even or better');
  expect(promise(3600, 250)).toBe('Pays only if it survives 1 h and gains at least 2.5%');
});

test('small helpers', () => {
  expect(mask('PAYID-ABCDEFGHIJ')).toBe('…EFGHIJ');
  expect(mask('short')).toBe('short');
  expect(mask(null)).toBe('');
  expect(ago(1_000, 1_030_000)).toBe('30 s ago');
  expect(ago(1_000, 1_000_000 + 7_200_000)).toBe('2 h ago');
});

test('pct and builtBy', () => {
  expect(pct(3.14159)).toBe('+3.1%');
  expect(pct(-2, 2)).toBe('-2.00%');
  expect(pct(null)).toBe('-');
  expect(builtBy('template:dip')).toBe('Template');
  expect(builtBy('')).toBe('Hand-made');
  expect(builtBy('gemini:gemini-3.5-flash-lite')).toBe('Gemini 3.5 Flash Lite');
  expect(instantOnly('upload:d_1')).toBe(true);
  expect(instantOnly('sample:BTCUSDT')).toBe(true);
  expect(instantOnly('binance:BTCUSDT')).toBe(false);
});
