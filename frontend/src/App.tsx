import { useEffect, useState } from 'react';
import { fetchInfo, fetchListings, fetchMe, fetchStats, logout, type Listing } from './api';
import { useTheme } from './hooks/useTheme';
import { usePoll } from './hooks/usePoll';
import { useRoute } from './route';
import { Agent } from './sections/Agent';
import { Checkout } from './sections/Checkout';
import { Hero } from './sections/Hero';
import { Footer, How } from './sections/How';
import { Ledger } from './sections/Ledger';
import { Market } from './sections/Market';
import { PurchasePage } from './sections/Purchase';
import { Purchases } from './sections/Purchases';
import { Sell } from './sections/Sell';
import { ModeBanner, Topbar } from './sections/Topbar';

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const info = usePoll(fetchInfo, { every: 10000 });
  const stats = usePoll(fetchStats, { every: 4000 });
  const me = usePoll(fetchMe, { every: 20000 });
  const listings = usePoll(fetchListings, { every: 5000 });
  const [buying, setBuying] = useState<Listing | null>(null);

  useEffect(() => {
    if (route.page === 'market' && route.hash) document.getElementById('market')?.scrollIntoView();
    else window.scrollTo(0, 0);
  }, [route.page, route.id]);

  async function signOut() {
    await logout();
    await me.reload();
  }

  return <>
    <Topbar route={route} me={me.data} theme={theme} onToggleTheme={toggle} onLogout={signOut}/>
    <ModeBanner mode={info.data?.paypal_mode ?? me.data?.paypal_mode}/>
    <main>
      {route.page === 'market' && <>
        <Hero stats={stats.data} ethPrice={info.data?.eth_price_usd}/>
        <Agent listings={listings.data ?? []} onBuy={setBuying}/>
        <Market listings={listings.data} error={listings.error} onBuy={setBuying}/>
        <How/>
      </>}
      {route.page === 'sell' && <Sell me={me.data} info={info.data} listings={listings.data ?? []} onChanged={() => { listings.reload(); stats.reload(); }}/>}
      {route.page === 'purchases' && <Purchases/>}
      {route.page === 'purchase' && <PurchasePage id={route.id} key={route.id}/>}
      {route.page === 'ledger' && <Ledger/>}
    </main>
    <Footer/>
    {buying && info.data && <Checkout listing={buying} info={info.data} onClose={() => setBuying(null)}/>}
  </>;
}
