# Demo video script (target 2:40, hard limit 2:50)

Rules for the recording: one voice, your own, simple English. Screen at 1280x720 or larger, browser zoom 110%. Light theme. No keys or passwords on screen. Show the Render address, not localhost.

Words in quotes are what to say. "Click" lines are exact. Say less if you run long. Cut the end first, not the payment part.

## Prepare before recording

- [ ] Render deploy is live and `PAYPAL_ENV=sandbox` with real sandbox keys (HANDOVER sections A to D done).
- [ ] Two browser profiles open and signed in: **Creator** (sandbox Business account) and **Buyer** (sandbox Personal account). Both on the Render address. The PayPal sandbox page must already be logged in or have the buyer password ready.
- [ ] Hide the bookmarks bar and other tabs. Close notifications.
- [ ] Creator has built nothing yet for the "build" scene. Or delete the old test agent from **My agents** (Delete button).
- [ ] The `Fast Demo Agent (1s, 2-minute hold)` is listed on the Market (it needs Binance reachable from Render). Buy it once as a rehearsal so you know the timing.
- [ ] A **voided** purchase already exists in the Buyer's **Purchases** page. To make one: with the Business account, list an agent in **Pay if proven** mode with **Min return %** set high (for example 50) and a 1 hour trial, buy it with the Personal account, and wait one hour. Do this the day before. Do not fake it.
- [ ] A **paid out** hold purchase already exists too (rehearsal buy of the Fast Demo).
- [ ] Creator agent saved and listed in **Instant** mode, price `1.00`, ready for the instant scene. Title it `Bitcoin Trend (demo)`.
- [ ] In the Buyer profile open the **Ledger** page in a second tab.
- [ ] The Creator AI chip shows free tries left (reset by a new day or a new browser profile).
- [ ] Record the hold scene's wait (2 minutes) as a separate take. In the edit, cut from "Charged now $0.00" to the verdict with a small on-screen text "2 minutes later".
- [ ] Rehearse the whole run twice with a timer. Total speaking time should be about 2:30.

## Storyboard

| Time | On screen (exact clicks) | Say |
|---|---|---|
| 0:00 to 0:12 | Creator profile. Show the Market page, scroll slowly past two agent cards with their green numbers | "Anyone can show you a backtest that looks great. You cannot check it. Trading-bot scams live on that. Parable makes the check cheap, and uses PayPal to make sure nobody pays for a lie." |
| 0:12 to 0:40 | Click **Build**. Click **Crypto**, click the **Bitcoin** chip. In **Describe your steps** type: `Buy when the 12 period moving average crosses above the 26 period one. Sell when it crosses back. Stop loss 3 percent.` Click **Build with AI** | "I build an agent by writing my steps in plain words. An AI model turns them into rules. These chips show the rules in plain language. The AI only writes rules. A fixed engine runs them, so there is no AI guessing at trade time." |
| 0:40 to 0:55 | Click **Backtest** in step 3. Point at the equity chart and the metrics grid (Return, Buy and hold, Worst drop) | "A backtest shows what this would have done on real Bitcoin prices, next to just holding. Fees and slippage are included." |
| 0:55 to 1:10 | Click **Benchmark models**. Tick three models. Click **Benchmark models** again. Wait for the table. Point at two rows and at the Buy and hold row | "Now the same sentence goes to several AI models. Each writes its own rules. All are tested on the same prices. I can see which model did best and adopt it." |
| 1:10 to 1:20 | Click **Save version**, then **Sell**. Type title and price `1.00`. Show the **Pay if proven** and **Instant** buttons for two seconds. Click **Instant**, then **List for sale** | "I list it. Two ways to sell: pay if proven, where PayPal holds the money, or instant. My rules stay private. Only a hash of them is public." |
| 1:20 to 1:40 | Switch to **Buyer** profile. Open Market, click the agent card. Click **Re-run the proof**. Hold on the claim versus re-run table and the "matches" result. Point at the two equal result hashes | "As a buyer I do not trust the numbers. I press Re-run the proof. Parable runs the same rules on the same stored prices again. The result hash is identical, so the claim matches exactly. I can also test-drive other dates for free." |
| 1:40 to 2:10 | Open **Market**, filter **Pay if proven**, open `Fast Demo Agent (1s, 2-minute hold)`. Click **Buy**. Point at "Charged now $0.00" and "Held in PayPal $9.00". Click the PayPal button, log in as the sandbox buyer, approve. Land on the Purchase page and show the live trial chart. Cut ("2 minutes later") to the verdict box and the timeline | "This agent has a two-minute hold so we can see the whole thing. Nothing is charged now. PayPal holds the money. The agent trades live with paper money for two minutes. A fixed rule, not AI, checks the result. It passed, so PayPal captures the money and Payouts sends the creator their share. Everything appears on the timeline." |
| 2:10 to 2:20 | Click **Purchases**. Open the voided purchase. Point at the voided status, the **Failed** verdict box and the timeline | "If it had failed, the hold is voided and the buyer never pays. Here is one that did fail." |
| 2:20 to 2:32 | Open `Bitcoin Trend (demo)` from the Market. Click **Buy**, pay with the PayPal button, land on the Purchase page. Click **Download JSON**. Show the file in the downloads bar | "Instant mode is one payment. PayPal captures it, Payouts pays the creator, and the buyer downloads the agent file, or runs it on Parable." |
| 2:32 to 2:45 | Click **Ledger**. Click **Verify chain** (green "Chain intact"). Click **Try to rewrite history**. Show "Chain broken at entry" | "Every listing, proof, trade and payment goes into a ledger where each entry contains the hash of the one before. If anyone edits the past, the chain breaks. That is Parable: build, prove, then sell with PayPal. Paper trading only." |
| 2:45 to 2:50 | Show the Render address and the GitHub repo name on a plain end card | "Parable. Open source, running in the PayPal sandbox." |

## Timing notes

- If you are over 2:50, shorten in this order: the benchmark (1:10 scene to one sentence), the voided scene, the instant scene. Never cut the re-run match or the hold purchase.
- Say "PayPal" clearly in the hold, void, instant and ledger scenes. The judges look for PayPal use.
- Do not claim real money, real trading or investment advice. Say "paper trading" once.
- Upload as Public or Unlisted on YouTube. Check the length shown by YouTube is under 3:00.
