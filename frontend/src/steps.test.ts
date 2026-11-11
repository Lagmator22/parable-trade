import { expect, test } from 'vitest';
import { buildSteps, isSettled, passedOf, stampOf } from './steps';
import type { PurchaseStatus } from './api';

const states = (status: PurchaseStatus) => buildSteps(status).map(step => step.state);
const instant = (status: PurchaseStatus, captured = false) => buildSteps(status, 'instant', captured).map(step => step.state);

test('a new hold order waits for authorization', () => {
  expect(states('created')).toEqual(['done', 'now', 'todo', 'todo', 'todo']);
});

test('trial marks authorization done and the run in progress', () => {
  expect(states('authorized')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
  expect(states('probation')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
});

test('a passed agent is captured then paid out', () => {
  expect(states('passed')).toEqual(['done', 'done', 'done', 'done', 'now']);
  expect(states('captured')).toEqual(['done', 'done', 'done', 'done', 'now']);
  expect(states('paid_out')).toEqual(['done', 'done', 'done', 'done', 'done']);
  expect(buildSteps('paid_out')[4].label).toBe('Captured and paid out');
});

test('a failed agent is voided and shown as stopped', () => {
  expect(states('failed')).toEqual(['done', 'done', 'done', 'bad', 'now']);
  expect(states('voided')).toEqual(['done', 'done', 'done', 'bad', 'bad']);
  expect(buildSteps('voided')[4].label).toBe('Voided, never charged');
});

test('cancelled and error stop at the step that did not finish', () => {
  expect(states('cancelled')).toEqual(['done', 'bad', 'todo', 'todo', 'todo']);
  expect(states('error')).toEqual(['done', 'done', 'done', 'done', 'bad']);
});

test('instant purchases use the short timeline', () => {
  expect(buildSteps('created', 'instant').map(step => step.label)).toEqual(['Order created', 'Payment captured', 'Seller paid out']);
  expect(instant('created')).toEqual(['done', 'now', 'todo']);
  expect(instant('captured')).toEqual(['done', 'done', 'now']);
  expect(instant('paid_out')).toEqual(['done', 'done', 'done']);
  expect(instant('error', false)).toEqual(['done', 'bad', 'todo']);
  expect(instant('error', true)).toEqual(['done', 'done', 'bad']);
  expect(instant('cancelled')).toEqual(['done', 'bad', 'todo']);
});

test('settled, verdict and stamp helpers', () => {
  expect(isSettled('paid_out')).toBe(true);
  expect(isSettled('voided')).toBe(true);
  expect(isSettled('probation')).toBe(false);
  expect(passedOf('captured')).toBe(true);
  expect(passedOf('failed')).toBe(false);
  expect(passedOf('probation')).toBeNull();
  expect(stampOf('paid_out')).toEqual({ text: 'PAID', tone: 'good' });
  expect(stampOf('voided')).toEqual({ text: 'VOIDED', tone: 'bad' });
  expect(stampOf('probation')).toBeNull();
});
