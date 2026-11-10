import { fetchCandles, fetchQuote } from '../../api';
import { MarketPicker } from '../../components/MarketPicker';
import { LiveChart } from '../../components/ui/LiveChart';
import { usePoll } from '../../hooks/usePoll';
import type { Build } from './useBuild';

export function StepMarket({ build }: { build: Build }) {
  const { market, interval } = build;
  const symbol = market?.symbol ?? '';
  const live = market?.live ?? false;
  const quote = usePoll(() => (symbol && live ? fetchQuote(symbol) : Promise.resolve(null)), { every: 5000, deps: [symbol, live] });
  const candles = usePoll(() => (symbol ? fetchCandles(symbol, interval, 500) : Promise.resolve(null)), { every: live ? 5000 : 60000, deps: [symbol, interval] });
  const bars = candles.data?.bars ?? [];
  const price = quote.data;

  return <div className="step-body">
    <MarketPicker value={symbol} onSelect={build.setMarket} initialKind={market?.kind ?? 'crypto'}/>
    {market && <div className="market-now">
      <div className="market-head">
        <strong>{market.name}</strong>
        {price && <span className="price-chip mono">{price.price.toLocaleString(undefined, { maximumFractionDigits: 6 })} {price.quote}{price.stale ? ' stale' : ''}</span>}
        {live && <span className="live" aria-label="live"/>}
        {!live && <span className="badge">sample data</span>}
      </div>
      {market.intervals.length > 1 && <div className="toggle" role="group" aria-label="Candle size">
        {market.intervals.map(i => <button key={i} type="button" aria-pressed={i === interval} onClick={() => build.setInterval(i)}>{i}</button>)}
      </div>}
      {candles.error && <p className="say bad">{candles.error}</p>}
      <LiveChart key={`${symbol}${interval}`} label={`${market.name} price`} showVolume series={[{ id: 'price', kind: 'candles', name: market.name, data: bars }]}/>
    </div>}
    {!market && <p className="empty">Pick a market to begin.</p>}
  </div>;
}
