import { act, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { vi } from 'vitest';

export async function mount(node: ReactNode) {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return {
    host,
    rerender: (next: ReactNode) => act(async () => root.render(next)),
    click: (element: Element | null) => act(async () => (element as HTMLElement).click()),
    unmount: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}
