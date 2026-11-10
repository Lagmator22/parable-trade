import type { ReactNode } from 'react';

export function Section({ id, label, className = '', children }: { id: string; label: string; className?: string; children: ReactNode }) {
  return <section className={`section ${className}`} id={id}>
    <div className="wrap">
      <div className="section-label">{label}</div>
      <div className="section-body">{children}</div>
    </div>
  </section>;
}
