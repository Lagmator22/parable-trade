# Demo video script (target 2:50, hard limit 3:00)

Rules for the recording: one voice, your own, simple English. Screen at 1280x720 or larger, browser zoom 110%. Light theme. No keys or passwords on screen.

## Storyboard (Deals lead + Trading Agents finale)

| Time | On screen (exact clicks) | Say |
|---|---|---|
| 0:00 to 0:10 | Open `/#deals` (`Pay when the work passes.`) | "Clients hate paying for work that misses the brief, and freelancers hate chasing invoices. With Parable Deals, PayPal holds the money, an AI agent checks the work, and PayPal pays out or returns the funds." |
| 0:10 to 0:35 | Click **Blog post** preset chip (or type brief), set price and freelancer PayPal email, click **Build the agent**. Checklist items animate in one by one (`AI check`, `Min words`, `Must include`). Edit one item, click **Create deal** | "I describe the job and click Build the agent. AI turns my brief into concrete checks — word count, required phrases, and AI review items. I can edit any check and create the deal." |
| 0:35 to 0:55 | On `/#deal/<id>`, click **Hold with PayPal** (PayPal window or simulated hold). Watch the `MoneyFlow` dot slide from `Client` to `PayPal` and pulse (`HELD $25.00`) | "Now I fund the deal with PayPal Orders v2 authorization. Nothing is captured yet — PayPal holds the money safely in the middle." |
| 0:55 to 1:20 | Click **Open as freelancer** (opens `/#deal/<id>.<token>`). Click **Try failing draft** chip, then click **Submit work**. Watch the 4-step live verification strip, items flipping one by one to crosses, and the orange `NOT YET` stamp; dot stays at `PayPal` | "The freelancer opens their link and submits an incomplete draft. Deterministic rules and the AI reviewer check each item live. It fails, so the stamp says NOT YET and the money stays held in PayPal." |
| 1:20 to 1:50 | Click **Fill passing work** chip and click **Submit work**. Watch each item flip to a green tick, the green `PAID $24.25` stamp land, and the `MoneyFlow` dot slide to `Freelancer`. Then click **← Deals**, open **Webhook Retry Idempotency Postmortem** (`Held in PayPal`), and click **Cancel and return money → Confirm return** to show `RETURNED $40.00` | "They resubmit work that meets every check. Each item ticks green, Parable captures the PayPal authorization and triggers a PayPal Payout to the freelancer, and the money slides to Paid. Or if a deal is cancelled, Parable voids the authorization and returns the money." |
| 1:55 to 2:10 | Scroll to **Deal ledger**, click **Verify the ledger →** (`/#ledger`). Click **Verify chain**, then **Try to rewrite history** | "Every deal event is chained with SHA-256 on the public ledger without exposing private text or emails. Editing history breaks the chain immediately." |
| 2:10 to 2:50 | Click **Trading agents** (`/#market`) and **Build** (`/#build`). Show building a trading agent from a sentence, multi-model benchmark, **Re-run the proof** (`MATCH`), and **Pay if proven** live trial hold mode | "We also built a second vertical on the same PayPal hold-until-proven engine: trading agents. Anyone can build a strategy from a plain sentence, benchmark multiple AI models on real market data, let buyers re-run the backtest proof hash in one click, and hold the purchase in PayPal during a live paper-trading probation." |
| 2:50 to 2:58 | Return to `/#deals` end card | "Parable: pay when the work passes, powered by PayPal and AI." |

## Timing notes

- If you are over 2:50, shorten in this order: the benchmark (1:10 scene to one sentence), the voided scene, the instant scene. Never cut the re-run match or the hold purchase.
- Say "PayPal" clearly in the hold, void, instant and ledger scenes. The judges look for PayPal use.
- Do not claim real money, real trading or investment advice. Say "paper trading" once.
- Upload as Public or Unlisted on YouTube. Check the length shown by YouTube is under 3:00.
