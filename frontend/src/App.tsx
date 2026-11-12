import { useEffect, useState } from 'react';
import { fetchInfo, fetchMe, logout, type PublicListing } from './api';
import './build.css';
import { useTheme } from './hooks/useTheme';
import { usePoll } from './hooks/usePoll';
import { useRoute } from './route';
import { AgentPage } from './sections/AgentPage';
import { BuildPage } from './sections/build/BuildPage';
import { Checkout } from './sections/Checkout';
import { DealPage } from './sections/deals/DealPage';
import { DealsPage } from './sections/deals/DealsPage';
import { Footer } from './sections/How';
import { Ledger } from './sections/Ledger';
import { MarketPage } from './sections/MarketPage';
import { MinePage } from './sections/MinePage';
import { PurchasePage } from './sections/Purchase';
import { Purchases } from './sections/Purchases';
import { ModeBanner, Topbar } from './sections/Topbar';
import { takeReturn } from './signIn';

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const info = usePoll(fetchInfo, { every: 15000 });
  const me = usePoll(fetchMe, { every: 20000 });
  const [buying, setBuying] = useState<PublicListing | null>(null);

  useEffect(() => { window.scrollTo(0, 0); }, [route.page, route.id]);
  useEffect(() => {
    if (!me.data?.seller) return;
    const back = takeReturn();
    if (back && back !== window.location.hash) window.location.hash = back;
  }, [me.data?.seller?.id]);

  async function signOut() {
    await logout();
    await me.reload();
  }

  return <>
    <Topbar route={route} me={me.data} theme={theme} onToggleTheme={toggle} onLogout={signOut}/>
    <ModeBanner mode={info.data?.paypal_mode ?? me.data?.paypal_mode}/>
    <main>
      {route.page === 'deals' && <DealsPage me={me.data} info={info.data}/>}
      {route.page === 'deal' && <DealPage id={route.id} key={route.id} me={me.data} info={info.data}/>}
      {route.page === 'build' && <BuildPage key={route.id} agentId={route.id} me={me.data} info={info.data} onMe={me.reload}/>}
      {route.page === 'market' && <MarketPage onBuy={setBuying}/>}
      {route.page === 'agent' && <AgentPage id={route.id} key={route.id} me={me.data} onBuy={setBuying}/>}
      {route.page === 'mine' && <MinePage me={me.data}/>}
      {route.page === 'purchases' && <Purchases/>}
      {route.page === 'purchase' && <PurchasePage id={route.id} key={route.id}/>}
      {route.page === 'ledger' && <Ledger/>}
    </main>
    <Footer/>
    {buying && info.data && <Checkout listing={buying} info={info.data} me={me.data} onClose={() => setBuying(null)}/>}
  </>;
}
