import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
import { Out } from './Glyphs';

type Look = { variant?: 'solid' | 'line' | 'quiet'; icon?: ReactNode };

export function Button({ variant = 'line', icon, children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & Look) {
  return <button {...props} className={`btn btn-${variant} ${className}`}>{icon}<span>{children}</span></button>;
}

export function LinkButton({ variant = 'line', icon, children, className = '', ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & Look) {
  return <a {...props} className={`btn btn-${variant} ${className}`}>{icon}<span>{children}</span></a>;
}

export function OutLink({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  if (!href) return null;
  return <a className="out-link" href={href} target="_blank" rel="noreferrer">{children}<Out size={13}/></a>;
}
