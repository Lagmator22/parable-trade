import { expect, test } from 'vitest';
import { receiptsOf, thresholdLines, tradesOf } from './purchase';
import { entry, purchase } from './test/fixtures';

test('splits the timeline into trades and receipts', () => {
  const timeline = [entry(1, 'purchase.created'), entry(2, 'run.trade'), entry(3, 'run.refused'), entry(4, 'purchase.authorized')];
  expect(tradesOf(timeline).map(item => item.seq)).toEqual([2, 3]);
  expect(receiptsOf(timeline).map(item => item.seq)).toEqual([1, 4]);
});

test('hold purchases draw the needed return and the loss limit', () => {
  const lines = thresholdLines(purchase());
  expect(lines.map(line => line.label)).toEqual(['Needs', 'Loss limit']);
  expect(lines[0].price).toBeCloseTo(990, 5);
  expect(lines[1].price).toBeCloseTo(979.7, 5);
});

test('instant purchases and missing runs draw no guide lines', () => {
  expect(thresholdLines(purchase({ mode: 'instant' }))).toEqual([]);
  expect(thresholdLines(purchase({ run: null }))).toEqual([]);
});
