import { Moon, Sun } from 'lucide-react';
import { useState } from 'react';
import type { Me, PaypalMode } from '../api';
import { hasOwnKey, loadAiSettings } from '../aiSettings';
import { AiKeyDialog } from '../components/AiKeyDialog';
import { Tomb } from '../components/ui/Glyphs';
import type { Route } from '../route';
import type { Theme } from '../hooks/useTheme';
import { rememberReturn } from '../signIn';

const NAV: [string, string, Route['page'][]][] = [
  ['Deals', '#deals', ['deals', 'deal']],
  ['Trading agents', '#market', ['market']],
  ['Build', '#build', ['build']],
  ['My agents', '#mine', ['mine', 'agent']],
  ['Purchases', '#purchases', ['purchases', 'purchase']],
  ['Ledger', '#ledger', ['ledger']],
];

type Props = { route: Route; me: Me | null; theme: Theme; onToggleTheme: () => void; onLogout: () => void };

export function Topbar({ route, me, theme, onToggleTheme, onLogout }: Props) {
  const [keyOpen, setKeyOpen] = useState(false);
  const [own, setOwn] = useState(() => hasOwnKey(loadAiSettings()));
  const tries = me?.free_tries;
  return <header className="topbar">
    <div className="wrap">
      <a className="brand" href="#deals"><Tomb size={24}/>PARABLE</a>
      <nav aria-label="Sections">
        {NAV.map(([label, href, pages]) => <a key={href} href={href} aria-current={pages.includes(route.page) ? 'page' : undefined}>{label}</a>)}
      </nav>
      <button type="button" className="ai-chip" onClick={() => setKeyOpen(true)} aria-label="AI settings">
        AI {own ? 'own key' : tries ? `${tries.remaining}/${tries.limit} free` : 'free'}
      </button>
      <Account me={me} onLogout={onLogout}/>
      <button type="button" className="square-btn" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
        {theme === 'dark' ? <Sun size={20}/> : <Moon size={20}/>}
      </button>
    </div>
    {keyOpen && <AiKeyDialog onClose={() => { setKeyOpen(false); setOwn(hasOwnKey(loadAiSettings())); }}/>}
  </header>;
}

function Account({ me, onLogout }: { me: Me | null; onLogout: () => void }) {
  if (!me) return null;
  if (!me.seller) return <a className="signin" href="/api/deals/demo-signin" onClick={() => rememberReturn(window.location.hash || '#deals')}>Sign in with PayPal</a>;
  return <div className="account">
    <a href="#mine" className="account-name">{me.seller.name}</a>
    <button type="button" className="link-btn" onClick={onLogout}>Sign out</button>
  </div>;
}

const BANNER: Record<PaypalMode, string | null> = {
  mock: 'PayPal sandbox mode — no real money moves.',
  sandbox: 'PayPal sandbox mode — no real money moves.',
  live: null,
};

export function ModeBanner({ mode }: { mode: PaypalMode | undefined }) {
  const message = mode ? BANNER[mode] : null;
  return message ? <div className="notice" role="status">{message}</div> : null;
}
