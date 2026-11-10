import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, test, vi } from 'vitest';
import { SelectMenu } from './SelectMenu';

test('chooses an option by keyboard and closes the menu', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const onChange = vi.fn();
  await act(async () => root.render(<SelectMenu label="Brain" value="rule" options={[{ value: 'rule', label: 'Simple rule' }, { value: 'claude', label: 'Claude' }]} onChange={onChange}/>));
  await act(async () => host.querySelector('button')!.click());
  expect(host.querySelector('[role=listbox]')).not.toBeNull();
  await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })));
  await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  expect(onChange).toHaveBeenCalledWith('claude');
  expect(host.querySelector('[role=listbox]')).toBeNull();
  await act(async () => root.unmount());
  host.remove();
});
