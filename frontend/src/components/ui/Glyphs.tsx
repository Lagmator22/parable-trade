import type { SVGProps } from 'react';

type GlyphProps = SVGProps<SVGSVGElement> & { size?: number };

function Glyph({ size = 22, children, ...props }: GlyphProps) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true" focusable="false" {...props}>{children}</svg>;
}

export const Tomb = (p: GlyphProps) => <Glyph {...p}><path d="M6 21V10a6 6 0 0 1 12 0v11"/><path d="M3 21h18"/><path d="M10 12h4"/></Glyph>;

export const Sprout = (p: GlyphProps) => <Glyph {...p}><path d="M12 21v-8"/><path d="M12 13c0-4.2 2.8-6.5 7.5-6.5 0 4.2-2.8 6.5-7.5 6.5Z"/><path d="M12 15.5c0-3.3-2.2-5.2-6-5.2 0 3.3 2.2 5.2 6 5.2Z"/></Glyph>;

export const Trade = (p: GlyphProps) => <Glyph {...p}><path d="M5 8h13l-3.5-3.5"/><path d="M19 16H6l3.5 3.5"/></Glyph>;

export const Shield = (p: GlyphProps) => <Glyph {...p}><rect x="4" y="4" width="16" height="16"/><path d="m8 8 8 8m0-8-8 8"/></Glyph>;

export const Person = (p: GlyphProps) => <Glyph {...p}><circle cx="12" cy="8" r="3.5"/><path d="M5 20.5c1-4 3.8-6 7-6s6 2 7 6"/></Glyph>;

export const Tag = (p: GlyphProps) => <Glyph {...p}><path d="M3.5 11.6V4.5a1 1 0 0 1 1-1h7.1l9 9-8.1 8.1Z"/><circle cx="8" cy="8" r="1.4"/></Glyph>;

export const Ledger = (p: GlyphProps) => <Glyph {...p}><path d="M12 6.5C10 5 7.5 4.5 4 4.5v14c3.5 0 6 .5 8 2 2-1.5 4.5-2 8-2v-14c-3.5 0-6 .5-8 2Z"/><path d="M12 6.5v14"/></Glyph>;

export const Price = (p: GlyphProps) => <Glyph {...p}><path d="m3.5 17 5-5 4 3 7.5-7.5"/><path d="M15 7.5h5v5"/></Glyph>;

export const Hourglass = (p: GlyphProps) => <Glyph {...p}><path d="M7 3.5h10M7 20.5h10"/><path d="M8 3.5c0 4.5 8 4.5 8 8.5s-8 4-8 8.5M16 3.5c0 4.5-8 4.5-8 8.5s8 4 8 8.5"/></Glyph>;

export const Hand = (p: GlyphProps) => <Glyph {...p}><path d="M8 12.5V6a1.5 1.5 0 0 1 3 0v5m0-6.5a1.5 1.5 0 0 1 3 0V11m0-4.5a1.5 1.5 0 0 1 3 0v7c0 4-2.5 7-6 7-2.8 0-4.4-1.6-5.8-4.4L4.8 13a1.5 1.5 0 0 1 2.6-1.5l.6 1"/></Glyph>;

export const Fall = (p: GlyphProps) => <Glyph {...p}><path d="m3.5 7 5.5 5.5 4-4 7.5 7.5"/><path d="M20.5 11v5h-5"/></Glyph>;

export const Brain = (p: GlyphProps) => <Glyph {...p}><rect x="5" y="8" width="14" height="11" rx="3.5"/><path d="M12 8V4.5"/><circle cx="12" cy="3.8" r=".8"/><path d="M9.5 13v1M14.5 13v1"/></Glyph>;

export const Wallet = (p: GlyphProps) => <Glyph {...p}><rect x="3.5" y="6" width="17" height="13" rx="2.5"/><path d="M3.5 9.5h17M15.5 14h2"/></Glyph>;

export const Coin = (p: GlyphProps) => <Glyph {...p}><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v9M9.5 10h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4"/></Glyph>;

export const Vault = (p: GlyphProps) => <Glyph {...p}><rect x="3.5" y="4" width="17" height="15" rx="2"/><circle cx="12" cy="11.5" r="3.5"/><path d="M12 8v1.2M12 13.8V15M8.5 11.5h1.2M14.3 11.5h1.2M6 19v1.5M18 19v1.5"/></Glyph>;

export const Check = (p: GlyphProps) => <Glyph {...p}><path d="m5 12.5 4.5 4.5L19 7.5"/></Glyph>;

export const Out = (p: GlyphProps) => <Glyph {...p}><path d="M7.5 16.5 16.5 7.5M9 7.5h7.5V15"/></Glyph>;

export function Heartbeat({ size = 22, ...p }: GlyphProps) {
  return <Glyph size={size} {...p} className={`heartbeat ${p.className || ''}`}><path pathLength={100} d="M2.5 12.5h4.5l2-5 4 10 2.5-6.5 1.5 1.5h4.5"/></Glyph>;
}

export const causeGlyph = (cause: string) => cause === 'killed' ? Hand : cause === 'loss_limit' ? Fall : Hourglass;

export const eventGlyph = (kind: string) => kind === 'birth' ? Sprout : kind === 'rejected' ? Shield : kind === 'death' ? Tomb : Trade;

export const Lock = (p: GlyphProps) => <Glyph {...p}><rect x="5" y="10.5" width="14" height="10"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/><path d="M12 14.5v2.5"/></Glyph>;

export const Refresh = (p: GlyphProps) => <Glyph {...p}><path d="M19.5 12a7.5 7.5 0 1 1-2.4-5.5"/><path d="M19.5 4.5v4h-4"/></Glyph>;

export const Copy = (p: GlyphProps) => <Glyph {...p}><rect x="8.5" y="8.5" width="11" height="11"/><path d="M15.5 8.5v-4h-11v11h4"/></Glyph>;
