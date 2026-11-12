import { expect, test } from 'vitest';
import { mount } from '../../test/mount';
import { MoneyFlow } from './MoneyFlow';

test('renders distinct status and stage classes for each deal status', async () => {
  const draft = await mount(<MoneyFlow status="draft" amountCents={2500} payoutCents={2250}/>);
  expect(draft.host.querySelector('.money-flow')?.className).toContain('status-draft');
  expect(draft.host.querySelector('.money-flow')?.className).toContain('flow-draft');
  expect(draft.host.textContent).toContain('READY $25.00');
  await draft.unmount();

  const funded = await mount(<MoneyFlow status="funded" amountCents={2500} payoutCents={2250}/>);
  expect(funded.host.querySelector('.money-flow')?.className).toContain('status-funded');
  expect(funded.host.querySelector('.money-flow')?.className).toContain('flow-held');
  expect(funded.host.textContent).toContain('HELD $25.00');
  await funded.unmount();

  const submitted = await mount(<MoneyFlow status="submitted" amountCents={2500} payoutCents={2250}/>);
  expect(submitted.host.querySelector('.money-flow')?.className).toContain('status-submitted');
  expect(submitted.host.querySelector('.money-flow')?.className).toContain('flow-held');
  await submitted.unmount();

  const released = await mount(<MoneyFlow status="released" amountCents={2500} payoutCents={2250}/>);
  expect(released.host.querySelector('.money-flow')?.className).toContain('status-released');
  expect(released.host.querySelector('.money-flow')?.className).toContain('flow-released');
  expect(released.host.textContent).toContain('PAID $22.50');
  await released.unmount();

  const returned = await mount(<MoneyFlow status="returned" amountCents={2500} payoutCents={2250}/>);
  expect(returned.host.querySelector('.money-flow')?.className).toContain('status-returned');
  expect(returned.host.querySelector('.money-flow')?.className).toContain('flow-returned');
  expect(returned.host.textContent).toContain('RETURNED');
  await returned.unmount();
});
