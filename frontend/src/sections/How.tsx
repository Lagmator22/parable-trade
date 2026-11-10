import { Section } from '../components/ui/Section';
import { Fall, Ledger, Lock, Price, Sprout } from '../components/ui/Glyphs';

const STEPS = [
  [Sprout, 'A seller lists a bot', 'They sign in with PayPal and publish the bot’s strategy, its price and a promise: how long it will survive and the minimum return.'],
  [Lock, 'You approve, PayPal holds', 'You authorize the price in PayPal. Nothing is charged. The money is only held while the bot is on probation.'],
  [Price, 'A referee runs the bot', 'The bot trades live prices with paper money. The referee fills its trades, enforces its limits and refuses what it should not do.'],
  [Fall, 'A fixed rule decides', 'Survived and met its promise: PayPal captures the payment and pays the seller, minus the platform fee. Otherwise the hold is voided.'],
  [Ledger, 'Nobody can hide a failure', 'Every trade, refusal and outcome goes into a hash-chained public ledger. A failed bot stays on its seller’s record forever.'],
] as const;

export function How() {
  return <Section id="how" label="03 How it works">
    <h2>Five steps, no trust required.</h2>
    <ol className="how-list five">
      {STEPS.map(([Icon, title, text], index) => <li key={title}>
        <Icon size={26}/>
        <h3><span className="mono muted">{index + 1}. </span>{title}</h3>
        <p>{text}</p>
      </li>)}
    </ol>
  </Section>;
}

export function Footer() {
  return <footer>
    <div className="wrap">
      <span>PARABLE · pay only if the bot survives</span>
      <span>Built for the PayPal AI Hackathon</span>
    </div>
  </footer>;
}
