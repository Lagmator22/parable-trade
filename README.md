# Parable

**Build a trading agent from a plain sentence, prove it with a result anyone can re-run, and sell it with PayPal.**

Parable is an agent workshop and a marketplace. Creators build and test agents. Buyers check the proof themselves, pay with PayPal, then run or download the agent. It is paper trading only. No real orders are ever placed.

Built for the PayPal AI Hackathon (Devpost). License: MIT.

## The problem

Anyone can show a backtest that looks great. Backtest means "pretend to trade on old prices to see what would have happened". A seller can pick the best dates, hide the runs that failed, or just make the numbers up. Buyers cannot check, so trading-bot scams are easy. Parable tries to make the check cheap: the buyer can run the same test again, on the same stored prices, and see if the numbers match exactly.

## What Parable does

1. **Build.** You type your steps in plain words. An AI model turns them into a small set of rules (a "Strategy Spec"). You can also pick a template, or edit the formulas yourself.
2. **Test.** Run a backtest. Search for better settings with "Find best" (it tunes on the first 70% of the prices and checks on the last 30%, and warns about overfit results). Replay the backtest as an animation. Go live on real prices with paper money.
3. **Benchmark models.** The same steps are given to several AI models. Each model writes its own rules. All of them are tested on the same prices and shown next to "buy and hold".
4. **Sell.** You list the agent with a price and one of two modes. Parable starts a public live track for it (a paper run on real prices that anyone can watch).
5. **Buyer checks.** The buyer presses "Re-run the proof". Parable runs the stored rules on the stored prices again. If the result hash is the same, the claim matches. The buyer can also test-drive the agent on other dates or another market, for free, with no key.
6. **Pay with PayPal.**
   - **Pay if proven (hold mode).** PayPal holds the money. The agent runs a live trial. A fixed rule (not AI) checks the minimum return and the maximum loss. If it passes, the money is captured and the creator is paid. If it fails, the hold is voided and the buyer is never charged.
   - **Instant mode.** The buyer pays now. The money is captured and the creator is paid at once.
7. **Run or download.** After payment the buyer gets a license. They can run the agent on Parable, or download it as a JSON file.

## How PayPal is used

All of this uses the PayPal sandbox. A built-in fake PayPal is used only when you set `PARABLE_MOCK_PAYPAL=1`, so the whole app can also run offline. Without PayPal keys and without that flag the server refuses to start.

| PayPal feature | What it does here | Files |
|---|---|---|
| Log in with PayPal (OpenID Connect) | The only way to sign in, for creators and buyers. Scopes: `openid profile email https://uri.paypal.com/services/paypalattributes` | `engine/parable/identity.py`, `engine/parable/paypal.py` (`oauth_authorize_url`, `exchange_code`, `userinfo`) |
| Orders v2: create + authorize, then capture or void | Hold mode. Creates an order with intent AUTHORIZE, authorizes it after the buyer approves, captures it if the trial passes, voids it if it fails | `engine/parable/paypal.py` (`create_order`, `authorize_order`, `capture_authorization`, `void_authorization`), `engine/parable/purchases.py`, `engine/parable/settlement.py` |
| Orders v2: create + capture | Instant mode. Creates an order with intent CAPTURE and captures it. The capture id is saved before the payout is sent, and nothing is ever captured twice | `engine/parable/paypal.py` (`capture_order`), `engine/parable/instant.py` |
| Payouts | After capture, the creator is paid the price minus the platform fee, to the email of their PayPal account | `engine/parable/paypal.py` (`create_payout`, `get_payout`), `engine/parable/settlement.py` |
| Webhooks with signature check | Events are checked with PayPal's verify-webhook-signature call. Unverified events are stored but never change anything | `engine/parable/webhooks.py`, `engine/parable/paypal.py` (`verify_webhook`), `engine/parable/market.py` (`on_webhook`) |
| JavaScript SDK buttons | The PayPal button in checkout. The page loads the SDK with `intent=authorize` for hold mode and `intent=capture` for instant mode | `frontend/src/paypalSdk.ts`, `frontend/src/sections/Checkout.tsx` |
| Fake PayPal for offline use | Same interface as the real client, used when keys are missing | `engine/parable/paypal_mock.py`, `engine/parable/paypal_routes.py` |

## How AI is used

| Where | What the AI does | Files |
|---|---|---|
| Steps to rules | Turns your plain words into a Strategy Spec. The server checks the result and retries once with the error message if it is wrong. Works with OpenAI, Gemini or Claude using your own key (kept in your browser, never stored by the server), or with the free daily allowance on the platform's own models | `engine/parable/lab/compiler.py`, `engine/parable/lab/llm.py`, `engine/parable/routes_ai.py` |
| Jev questionnaire builder | The Jev models cannot write text, so they answer four multiple-choice questions (strategy family, speed, risk, size). Those answers are turned into rules by fixed code | `engine/parable/lab/questionnaire.py`, `engine/parable/jev.py`, `engine/parable/lab/compiler.py` |
| Model benchmark | Many models build rules from the same steps. All are backtested on the same prices and compared with buy and hold. You can adopt the best one as a new version | `engine/parable/benchmarks.py`, `engine/parable/routes_agents.py` |
| AI ideas | Suggests variants of your current rules. Each variant is checked before it is shown | `engine/parable/lab/compiler.py` (`ideas`), `engine/parable/routes_ai.py` |
| AI column mapping | When you upload a price file whose columns are not recognised, an AI model maps them to time, open, high, low, close and volume | `engine/parable/lab/datasets.py` (`ai_map_columns`) |
| AI due diligence | Writes a plain-words report on a listing from its real numbers. Numbers the AI invents are rejected. It never sees the rules | `engine/parable/diligence.py`, `engine/parable/analyst.py`, `engine/parable/minds.py` |
| AI shopper | A buyer types what they want. It ranks listings by their proof numbers | `engine/parable/shopper.py` |
| MCP tools | Lets another AI assistant search agents, read proofs, re-run a proof, test-drive, run due diligence, check the ledger, and get a buy link. A human must finish the PayPal payment | `engine/parable/mcp_server.py` |

The AI never decides a trade. AI only writes rules. A fixed engine runs them.

## How trust works

- **Deterministic engine.** The same rules on the same prices always give the same numbers. Signals are read on closed bars only. Orders fill at the next bar's open, with fees and slippage.
- **Exact re-run with a result hash.** Every proof has a `result_hash`. A re-run on the stored prices must give the same hash. Same hash means the claim matches.
- **Stored prices.** The exact bars used for a proof are saved under their `data_hash`. A re-run does not need the internet. An optional "fetch the data again" check shows whether fresh data is the same.
- **Hash-chained ledger.** Important events (listings, proofs, trades, payments, payouts) are written to a ledger. Each entry contains the hash of the one before it. The Ledger page has "Verify chain" and "Try to rewrite history", which edits a copy and shows that verification fails.
- **The rules stay private.** The rules (entry and exit formulas, settings, your steps) are stored in one place. Public pages, proofs, runs and the ledger only carry a hash of the rules. The buyer gets the rules only after payment is captured. A test in the repo (`engine/tests/test_spec_leak.py`) checks that no public output contains them.

## Supported markets and honest limits

| Market | Source | Notes |
|---|---|---|
| Crypto, gold token (PAXG) | Binance public market data | Live prices and deep history. Intervals from 1 second to 1 week |
| Forex (USD, EUR, GBP, JPY, INR, CHF, AUD, CAD, CNY pairs) | Frankfurter | Daily bars only |
| Indian mutual funds | mfapi.in | Daily NAV only |
| Stocks and ETFs | Yahoo Finance (best effort), Twelve Data (needs a free key) | Yahoo can block some servers, so stocks may be unavailable. Without a key, stocks work by upload only |
| Options, futures, anything else | Upload (CSV, TSV, JSON, Excel, Word table; max 5 MB) | Upload only. There is no live feed |
| Bundled samples | Real files in `engine/parable/lab/samples/` (BTC, ETH, SOL, gold, EURUSD, one fund) | Used for offline mode. Labelled "sample data" |

Limits to know:
- Sold agents that use uploaded or sample data can only be sold in Instant mode. Hold mode needs a live market to track.
- Agents are long-only: they buy and later sell. There is no shorting and no leverage.
- Free test-drives on uploaded data are refused, so a creator's file is never shared.

## Run it locally in 2 commands

You need: Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and Node 20 or newer. You do not need any keys. Offline mode uses a fake PayPal and the bundled real sample prices.

Command 1. Build the website. Run it in the `frontend` folder:

```bash
cd frontend && npm install && npm run build
```

Command 2. Start the server. Run it in the `engine` folder:

```bash
cd engine && PARABLE_MOCK_PAYPAL=1 MARKETS_OFFLINE=1 PARABLE_DEMO_SEED=1 uv run uvicorn parable.api:app --port 8000
```

Open http://localhost:8000. Click "Sign in with PayPal" and fill in any name and email on the fake sign-in page. Offline mode seeds six demo agents, all in Instant mode, on the sample data. The "Pay if proven" mode needs a live market, so it needs an internet connection and a real or fake PayPal with `MARKETS_OFFLINE` left unset.

With internet but no PayPal keys, leave out `MARKETS_OFFLINE=1`. Parable then uses real Binance prices and the fake PayPal. The demo list then also has the "Fast Demo Agent", which has a 2-minute hold.

To use real PayPal sandbox keys, see `docs/HANDOVER.md`.

For frontend development with auto reload, run this in the `frontend` folder (the server above must be running):

```bash
cd frontend && npm run dev
```

## Configuration

Settings are read from environment variables or from a `.env` file in the repo root. `.env.example` lists them all. Names are not case sensitive. Source: `engine/parable/config.py`.

| Variable | Meaning | Default |
|---|---|---|
| `PAYPAL_CLIENT_ID` | Client ID of your PayPal REST app | empty |
| `PAYPAL_CLIENT_SECRET` | Secret of that app | empty |
| `PAYPAL_ENV` | `sandbox` or `live` | `sandbox` |
| `PAYPAL_WEBHOOK_ID` | ID of the webhook, used to verify signatures | empty |
| `PARABLE_MOCK_PAYPAL` | `1` uses the fake PayPal (offline development only). It is never used unless you set it, and the server refuses to start without PayPal keys when it is off | `0` |
| `PARABLE_ENV` | `production` makes the server refuse to start with the fake PayPal, `PRICE_SOURCE=sim`, or a `SESSION_SECRET` shorter than 32 characters | empty |
| `DEMO_PAYOUT_EMAIL` | Payout email given to the seeded demo creators (use a PayPal sandbox account you own). Empty keeps the example.com addresses | empty |
| `PUBLIC_BASE_URL` | Public address of the site, used for PayPal login and return URLs. An `https://` value turns on secure cookies | `http://localhost:8000` |
| `SESSION_SECRET` | Signs login cookies. Must be at least 32 random characters (the placeholder text and short values are refused unless the fake PayPal is on). If empty, a random one is made at each start and everyone is signed out on restart; `PARABLE_ENV=production` refuses empty | empty |
| `PLATFORM_FEE_BPS` | Platform fee in basis points (100 = 1%) | `1000` |
| `DATABASE_PATH` | SQLite file path | `parable.db` |
| `PRICE_SOURCE` | `live` or `sim` | `live` |
| `BOT_INTERVAL_S` | Seconds between ticks of a running agent | `15` |
| `PARABLE_DEMO_SEED` | `1` creates demo creators and agents at start | `0` |
| `MARKETS_OFFLINE` | `1` never calls market data sites | `0` |
| `TWELVE_DATA_KEY` | Twelve Data key for stocks | empty |
| `GEMINI_API_KEY` | Google key for Gemini and Gemma models, AI due diligence, AI shopper | empty |
| `GEMINI_MODELS` | Comma-separated Gemini models to offer. Empty with a key = one default model | empty |
| `GEMMA_MODELS` | Comma-separated Gemma models to offer | empty |
| `AUTOLOOPS_API_KEY` | Key for the Jev models | empty |
| `JEV_MODELS` | Comma-separated Jev models to offer | `gemma-4-31b-it,deepseek-v4.1-flash` |
| `AI_ANALYST_BRAIN` | Model for due diligence and shopper, as `provider:model` | `gemini:gemini-3.5-flash-lite` |
| `AI_FREE_TRIES_PER_DAY` | Free platform AI calls per visitor per day | `5` |
| `ANTHROPIC_API_KEY` | Only for a `claude:` analyst | empty |
| `CLAUDE_MODELS` | Claude models for that analyst | empty |
| `BOT_MODEL` | Left over from the old version. Not used | `claude-haiku-5-5` |
| `UPLOAD_MAX_BYTES` | Largest upload | `5000000` |
| `UPLOAD_MAX_ROWS` | Most rows in an upload | `200000` |
| `MAX_LIVE_RUNS_PER_ACCOUNT` | Live practice runs at once per account | `5` |
| `MAX_RUN_POINTS_PER_RUN` | Equity points kept per run | `20000` |
| `MAX_AGENTS_PER_ACCOUNT` | Agents per account | `50` |
| `MAX_VERSIONS_PER_AGENT` | Versions per agent | `100` |
| `MAX_DATASETS_PER_ACCOUNT` | Uploaded datasets per account | `20` |
| `MAX_JOBS_PER_ACCOUNT` | Background jobs (benchmark, Find best) at once | `2` |
| `BENCHMARK_MAX_MODELS` | Models per benchmark | `6` |
| `RATE_LAB_PER_MINUTE` | Backtests per minute per visitor | `30` |
| `RATE_AI_PER_MINUTE` | AI calls per minute per visitor | `10` |
| `RATE_PROOFS_PER_HOUR` | Re-runs and test-drives per hour per visitor | `30` |
| `RATE_PURCHASES_PER_HOUR` | Purchase starts per hour per account | `20` |
| `TRACK_LEASE_SECONDS` | Length of one live track run | `2592000` (30 days) |
| `RUN_START_CASH` | Paper cash of a run, in millionths of a unit | `10000000000` (10,000) |

Own-key AI settings (OpenAI, Anthropic, Gemini) are not server settings. A visitor types them into the AI dialog in the site's top bar. They are kept in that browser and sent with each AI request.

## Tests

Tests never use the network. Run them in these folders:

```bash
cd engine && uv run pytest -q
cd frontend && npm test
cd frontend && npm run build
```

`engine/tests/test_e2e.py` walks the whole flow with the fake PayPal: build, backtest, benchmark, list in both modes, re-run, test-drive, buy and pass, buy and fail, instant buy, download, ledger check.

## Deploy

A `Dockerfile` and a `render.yaml` are included for Render. See `docs/HANDOVER.md`, section H.

## Project layout

```
engine/                  Python backend (FastAPI, SQLite)
  parable/
    api.py               App start, serves the built website
    lab/                 Formula language, backtest, optimiser, markets, uploads, AI, jobs, samples
    agents.py proofs.py benchmarks.py listings.py purchases.py settlement.py instant.py
    referee*.py runs.py bot_runner.py   Paper accounts and live runs
    paypal*.py identity.py webhooks.py  PayPal client, fake PayPal, login, webhooks
    ledger.py            Hash-chained ledger
    diligence.py shopper.py analyst.py mcp_server.py   AI helpers and MCP
    seed.py              Demo creators and agents
  tests/                 Pytest suite
frontend/                React + TypeScript + Vite website
  src/sections/          Pages (Market, Build, Agent, My agents, Purchases, Ledger)
docs/                    HANDOVER.md, SUBMISSION.md, VIDEO_SCRIPT.md
internal-notes/          Plan and build contract
Dockerfile render.yaml   Deploy on Render
```

## What changed since the ETHGlobal version

Parable began at ETHGlobal Mumbai 2026 as a different product: AI trading bots that put money in an on-chain vault and could not hide failed runs. It used World ID, ENS and Arkiv. That version is still in this repository's history (last ETHGlobal-era commit: 7 Nov 2026).

On 10 and 11 Nov 2026, inside the PayPal hackathon period, it was rebuilt. Almost all of the code is new.

Removed (commit "Start PayPal edition", 10 Nov 2026):
- The on-chain vault and smart contract code
- World ID sign-in
- ENS names
- Arkiv storage
- The old dashboard
- Bots where an AI model decides every trade, and the fixed list of preset ETH bots

Built:
- PayPal as the centre: Log in with PayPal, hold mode (authorize, capture or void), instant mode (capture), Payouts, verified webhooks, JS SDK buttons, and a fake PayPal for offline use
- A safe formula language for rules, with indicators such as SMA, EMA, RSI, MACD, Bollinger bands and ATR, a deterministic backtest engine with fees, slippage and stops, a settings optimiser with an overfit warning
- A rules compiler that turns plain words into rules with OpenAI, Gemini or Claude, plus the Jev questionnaire builder and the model benchmark
- Market data from Binance, Frankfurter, mfapi, Yahoo and Twelve Data, uploads (CSV, JSON, Excel, Word) with AI column mapping, and real sample data
- Agents with immutable versions, proofs with result hashes, exact re-run, free test-drive, public live tracks
- A rewritten hash-chained ledger, AI due diligence, AI shopper, MCP tools
- A new website: Market, Build workshop with live charts, Agent page, My agents, Purchases, Ledger
- Deploy files and docs

Kept from the old version: the idea that results must be checkable, the hash-chained ledger concept, and the referee that keeps paper accounts with integer money.

## Screenshots

TODO (owner): add screenshots of the Build page, an Agent page with the re-run result, a Purchase page, and the Ledger page. Save them in `docs/images/` and link them here.

## Limits and disclaimers

- **Paper trading only.** Parable never places a real order on any exchange.
- **Not investment advice.** Nothing here is a recommendation to buy or sell anything.
- **Backtests do not predict the future.** A good past result can fail on new prices. Overfit settings often do.
- **Options and futures work by upload only.** There is no live feed for them.
- **PayPal is in sandbox mode.** No real money moves unless you set `PAYPAL_ENV=live`, which this project has not been tested with.
- **One server, one SQLite file.** There is no clustering. Run one copy of the server only.
- The payout goes to the email of the creator's PayPal account. A payout to an email with no PayPal account can fail or stay unclaimed.
- **Known gaps (not fixed).**
  - Refunds, disputes and chargebacks are not handled (M3). An instant sale pays the seller at once, so a later dispute is only logged and the license is not revoked.
  - A live track shows its trades and equity while it runs (M4), and test-drive acts as a partial oracle for how an agent behaves (M5). Anyone can learn an agent's habits without buying it.
  - Run exactly one server process (M12). Purchase locks, rate limits, jobs and the draft store live in memory, and every extra process would restart the bots again.
  - Sessions are stateless cookies that last 7 days (M15). Logging out removes the cookie but a stolen cookie stays valid until it expires.
  - Payouts go by email, and PayPal's verified flag is not required to list (L7).
  - The ledger chain lives in the same database it protects (L9). Whoever can write the file could rebuild it. Publish the head hash somewhere else if that matters.
  - The number of backtests a creator tried before listing is not shown.

## Roadmap

- Real-money trading through a broker
- Live feeds for options and futures
- PDF price files
- Refunds and subscriptions
- PayPal multiparty split of sale money
- A seller assistant that uses the PayPal Agent Toolkit
- More login options besides PayPal
- A database that can run on more than one server

## License

MIT. See `LICENSE`.
