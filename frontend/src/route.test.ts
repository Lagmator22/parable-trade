import { describe, expect, it } from 'vitest';
import { parseRoute } from './route';

describe('parseRoute', () => {
  it.each([
    ['#deals', { page: 'deals', id: '' }],
    ['#deal/dl_1', { page: 'deal', id: 'dl_1' }],
    ['#deal/dl_1.tok_2', { page: 'deal', id: 'dl_1.tok_2' }],
    ['#build', { page: 'build', id: '' }],
    ['#build/a_123', { page: 'build', id: 'a_123' }],
    ['#sell', { page: 'build', id: '' }],
    ['#market', { page: 'market', id: '' }],
    ['', { page: 'deals', id: '' }],
    ['#', { page: 'deals', id: '' }],
    ['#agent/l_1', { page: 'agent', id: 'l_1' }],
    ['#agent', { page: 'deals', id: '' }],
    ['#mine', { page: 'mine', id: '' }],
    ['#purchases', { page: 'purchases', id: '' }],
    ['#purchase/p_1', { page: 'purchase', id: 'p_1' }],
    ['#purchase', { page: 'deals', id: '' }],
    ['#ledger', { page: 'ledger', id: '' }],
    ['#/ledger', { page: 'ledger', id: '' }],
    ['#nope', { page: 'deals', id: '' }],
  ])('%s', (hash, route) => expect(parseRoute(hash)).toEqual(route));
});
