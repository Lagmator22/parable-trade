import { describe, expect, it } from 'vitest';
import { parseRoute } from './route';

describe('parseRoute', () => {
  it.each([
    ['#build', { page: 'build', id: '' }],
    ['#build/a_123', { page: 'build', id: 'a_123' }],
    ['#sell', { page: 'build', id: '' }],
    ['#market', { page: 'market', id: '' }],
    ['', { page: 'market', id: '' }],
    ['#', { page: 'market', id: '' }],
    ['#agent/l_1', { page: 'agent', id: 'l_1' }],
    ['#agent', { page: 'market', id: '' }],
    ['#mine', { page: 'mine', id: '' }],
    ['#purchases', { page: 'purchases', id: '' }],
    ['#purchase/p_1', { page: 'purchase', id: 'p_1' }],
    ['#purchase', { page: 'market', id: '' }],
    ['#ledger', { page: 'ledger', id: '' }],
    ['#/ledger', { page: 'ledger', id: '' }],
    ['#nope', { page: 'market', id: '' }],
  ])('%s', (hash, route) => expect(parseRoute(hash)).toEqual(route));
});
