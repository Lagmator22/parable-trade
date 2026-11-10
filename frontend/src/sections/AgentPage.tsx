import type { Me, PublicListing } from '../api';

export function AgentPage(_props: { id: string; me: Me | null; onBuy: (l: PublicListing) => void }) {
  return <section className="section"><div className="wrap"><h2>Agent</h2></div></section>;
}
