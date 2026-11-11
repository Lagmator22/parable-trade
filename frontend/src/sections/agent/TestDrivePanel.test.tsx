import { expect, test } from 'vitest';
import { intervalChoices } from './TestDrivePanel';

test('interval chips always include the agent interval', () => {
  expect(intervalChoices('1h')).toEqual(['1h', '4h', '1d']);
  expect(intervalChoices('15m')).toEqual(['15m', '1h', '4h', '1d']);
  expect(intervalChoices('1s')[0]).toBe('1s');
});
