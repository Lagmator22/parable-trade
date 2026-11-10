import { expect, test } from 'vitest';
import { buildSteps, isSettled, passedOf } from './steps';
import type { PurchaseStatus } from './api';

const states = (status: PurchaseStatus) => buildSteps(status).map(step => step.state);

test('a new order waits for authorization', () => {
  expect(states('created')).toEqual(['done', 'now', 'todo', 'todo', 'todo']);
});

test('probation marks authorization done and the run in progress', () => {
  expect(states('authorized')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
  expect(states('probation')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
});

test('a passed bot is captured then paid out', () => {
  expect(states('passed')).toEqual(['done', 'done', 'done', 'done', 'now']);
  expect(states('captured')).toEqual(['done', 'done', 'done', 'done', 'now']);
  expect(states('paid_out')).toEqual(['done', 'done', 'done', 'done', 'done']);
  expect(buildSteps('paid_out')[4].label).toBe('Captured and paid out');
});

test('a failed bot is voided and shown as stopped', () => {
  expect(states('failed')).toEqual(['done', 'done', 'done', 'bad', 'now']);
  expect(states('voided')).toEqual(['done', 'done', 'done', 'bad', 'bad']);
  expect(buildSteps('voided')[3].label).toBe('Verdict: failed');
  expect(buildSteps('voided')[4].label).toBe('Voided, never charged');
});

test('cancelled and error stop at the step that did not finish', () => {
  expect(states('cancelled')).toEqual(['done', 'bad', 'todo', 'todo', 'todo']);
  expect(states('error')).toEqual(['done', 'done', 'done', 'done', 'bad']);
});

test('settled and verdict helpers', () => {
  expect(isSettled('paid_out')).toBe(true);
  expect(isSettled('voided')).toBe(true);
  expect(isSettled('probation')).toBe(false);
  expect(passedOf('captured')).toBe(true);
  expect(passedOf('failed')).toBe(false);
  expect(passedOf('probation')).toBeNull();
});
