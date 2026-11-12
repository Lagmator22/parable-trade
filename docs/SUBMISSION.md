# Devpost text (paste each part into the matching box)

Replace everything in `<angle brackets>` before you submit.

## Project name

Parable

## Tagline (under 200 characters)

Pay when the work passes: AI turns a job brief into an acceptance checklist, PayPal holds the money, the agent checks delivered work live, and PayPal pays the freelancer or returns the funds.

## Inspiration

Clients hate paying upfront for freelance work that misses the brief. Freelancers hate delivering work and chasing invoices. Traditional escrow takes days of manual arbitration. What if an AI agent turned the client's brief into a concrete checklist upfront, PayPal held the funds with `AUTHORIZE`, and the moment the freelancer submitted work, the agent verified every check and triggered PayPal `capture_authorization` + `create_payout` (or `void_authorization` on cancellation)?

We also applied the exact same "pay only when verified" pattern to a second vertical — trading agents — where anyone can show a fake backtest, so Parable lets buyers re-run the proof deterministically and holds payment in PayPal until a live paper trial passes.

## What it does

### 1. Parable Deals — "Pay when the work passes" (Lead product)
- **Build the checklist agent.** A client types a job brief, sets a price in USD, and enters the freelancer's PayPal email. AI turns the brief into 2–8 checkable acceptance criteria (`AI check`, `Min words`, `Must include`). The client can edit, add, or remove items.
- **Hold with PayPal.** Parable creates a PayPal Order v2 (`intent="AUTHORIZE"`) and authorizes the hold. Money moves into PayPal hold (`HELD $X` on the live `MoneyFlow` track).
- **Deliver and verify live.** The freelancer opens their tokenized link (`/#deal/<id>.<token>`) and submits work (up to 3 attempts). Code deterministically checks `min_words` and `must_include` rules; AI checks `ai` criteria while treating the submission as untrusted data. Each item flips one by one to a green tick or orange cross with evidence.
- **Settle with PayPal.** When all checks pass, Parable captures the authorization (storing `capture_id` before payout so retries never double-capture) and sends the net payout to the freelancer via PayPal Payouts (`PAID $X`). The client can also override (`Release anyway`) or cancel (`Cancel and return money` → `void_authorization`).
- **Hash-chained ledger.** Every deal event is appended to the SHA-256 hash-chained ledger without leaking emails, briefs, work text, or PayPal IDs.

### 2. Second vertical — Trading Agents ("Pay if proven")
Parable is also an agent workshop and marketplace for paper-trading strategies.

- **Build.** You write your steps in plain words. An AI model (OpenAI, Gemini or Claude with your own key, or free platform models, or the Jev models) turns them into a small set of rules in a safe formula language. You can also start from a template or edit the formulas.
- **Test.** Backtest on real prices with fees and slippage. "Find best" tunes settings on 70% of the data and checks on the other 30%, and marks overfit results. "Replay" animates the backtest. "Go live" runs the agent on real prices with paper money.
- **Benchmark models.** The same steps go to many AI models. Each writes its own rules. All are tested on the same prices and compared with buy and hold.
- **Sell.** The creator lists the agent in one of two modes. A public live track starts for it.
- **Prove.** A buyer presses "Re-run the proof". Parable runs the stored rules on the stored prices again. If the result hash matches, the claim is exact. The buyer can also test-drive other dates or markets for free.
- **Pay with PayPal.** In "Pay if proven" mode PayPal authorizes the payment and holds it. The agent runs a live trial, and a fixed rule (not AI) checks the minimum return and the maximum loss. Pass: the payment is captured and the creator is paid with PayPal Payouts. Fail: the authorization is voided and the buyer pays nothing. In "Instant" mode the order is captured at once and the creator is paid out.
- **Run or download.** After payment the buyer can run the agent on Parable or download it as a JSON file.

Other parts: AI due diligence reports, an AI shopper, MCP tools for other AI assistants, a hash-chained public ledger with a "try to rewrite history" demo, and uploads (CSV, JSON, Excel, Word table) for markets without a live feed, such as options and futures.

Everything is paper trading in the PayPal sandbox. No real orders, no real money.

## How we built it

- **Backend:** Python 3.12, FastAPI, SQLite, httpx. A safe formula parser (built on Python's `ast`, with a whitelist of nodes, never `eval`) feeds a deterministic backtest engine.
- **PayPal:** Log in with PayPal (OpenID Connect) is the only sign-in. Orders v2 with intent AUTHORIZE, authorize, capture and void for hold mode. Orders v2 with intent CAPTURE for instant mode. Payouts to creators. Webhooks checked with PayPal's verify-webhook-signature call. PayPal JS SDK buttons for checkout. A fake PayPal with the same interface lets the whole app and its tests run offline.
- **Safe money handling:** amounts are integers (cents and micro-units). The capture id is saved before any payout is sent. A payout can be retried without capturing twice. A buyer cannot buy their own listing, checked by account and by PayPal payer id.
- **AI:** a rules compiler with one corrective retry, a multi-model benchmark, the Jev questionnaire builder, AI column mapping for uploads, AI due diligence (numbers it invents are rejected), an AI shopper, and MCP tools. A visitor's own key stays in their browser and is never stored or logged by the server. Free tries are limited per visitor per day.
- **Data:** Binance, Frankfurter, mfapi.in, Yahoo Finance (best effort) and Twelve Data, plus real sample files bundled in the repo.
- **Trust:** the same rules on the same stored prices give the same result hash. A ledger where each entry holds the hash of the previous one. A test checks that the creator's rules never appear in any public output.
- **Frontend:** React 19, TypeScript, Vite, Tailwind, lightweight-charts for live charts.
- **Deploy:** Docker image on Render with a persistent disk for the SQLite file.

## Challenges

- Keeping the rules private but the proof checkable. The answer was to store the rules in one place, expose only hashes, and store the exact bars used for each proof so a re-run needs nothing from the internet.
- Making the engine deterministic. Signals use closed bars only and orders fill at the next bar's open, so a backtest and a live run behave the same.
- Letting an AI write rules safely. Every AI answer is parsed, limited and dry-run before it is used. One retry shows the model its own error.
- Payment edge cases: capture and then payout failure, double clicks, buying your own listing, and webhooks that arrive late or twice.
- Rebuilding a whole product in two days after starting from a very different project.

## Accomplishments that we're proud of

- A buyer can check a seller's claim in one click and get an exact match or a mismatch.
- Both PayPal payment shapes (hold then capture or void, and instant capture) work end to end, with payouts and verified webhooks.
- The model benchmark shows many AI models side by side on identical data.
- The whole app, including payments, runs offline with a fake PayPal and bundled real data, and the test suite never touches the network.
- The project is open source and meant to be used after the hackathon.

## What we learned

- PayPal's authorize, capture and void flow is a good fit for "pay only if it works".
- Asking an AI for structured rules, then validating them hard, is much more reliable than asking it to decide trades.
- Small, boring rules (integers for money, ids saved before the next step) prevent most payment bugs.
- A proof is only useful if the other side can run it.

## What's next

Real-money trading through a broker, live feeds for options and futures, PDF price files, refunds and subscriptions, a PayPal multiparty split of sale money, a seller assistant using the PayPal Agent Toolkit, more login options, and a database that can run on more than one server. The owner will keep running Parable as a product after the hackathon.

## Built with (technologies)

PayPal Log in with PayPal, PayPal Orders v2 (authorize, capture, void), PayPal Payouts, PayPal Webhooks, PayPal JavaScript SDK, PayPal Sandbox, OpenAI API, Google Gemini API, Google Gemma, Anthropic Claude API, Jev (Autoloops), Model Context Protocol (MCP), Python, FastAPI, SQLite, pydantic, httpx, uvicorn, React, TypeScript, Vite, Tailwind CSS, lightweight-charts, Docker, Render, Binance market data, Frankfurter, mfapi.in, Yahoo Finance, Twelve Data.

## How the project was significantly updated during the submission period

(Submission period: 1 Oct to 12 Nov 2026.)

Parable existed before the period as an ETHGlobal Mumbai 2026 hackathon project. It was an on-chain system: a vault smart contract, World ID sign-in, ENS names and Arkiv storage, with AI trading bots that could not hide failed runs. The last commit of that version is dated 7 Nov 2026 in this repository's history.

On 10 Nov 2026 we removed the whole on-chain stack (vault, World ID, ENS, Arkiv, the old dashboard, and the AI-decides-every-tick bots with preset ETH bots) and rebuilt the project around PayPal. Between 10 and 12 Nov 2026 we wrote, almost completely new:

- PayPal sign-in, hold mode (authorize, capture or void), instant mode (capture), Payouts, verified webhooks, JS SDK checkout, and a fake PayPal for offline use
- A safe formula language, a deterministic backtest engine, an optimiser with an overfit warning, and a rules compiler for OpenAI, Gemini and Claude
- A model benchmark, the Jev questionnaire builder, AI ideas, AI column mapping, AI due diligence, an AI shopper and MCP tools
- Market data providers, uploads, bundled real sample data, agents with immutable versions, exact re-run proofs, free test-drive, and public live tracks
- A rewritten ledger and a new website (Market, Build workshop, Agent page, My agents, Purchases, Ledger)
- Docker and Render deployment, and a new test suite that never touches the network

The git history in the public repo shows the ETHGlobal-era commits before 10 Nov 2026 and the PayPal rebuild after it (see commits "Start PayPal edition: drop the on-chain stack ..." through the latest).

## Testing instructions for judges

**Hosted app:** `<https://your-service.onrender.com>`
**Source code:** `<https://github.com/your-name/parable>` (MIT license)

Parable runs in the PayPal **sandbox**. No real money moves. Sign in with PayPal using these sandbox accounts:

- Buyer (Personal): email `<sandbox-buyer-email>`, password `<sandbox-buyer-password>`
- Creator (Business): email `<sandbox-creator-email>`, password `<sandbox-creator-password>`

Steps:

1. Open the hosted app. Click **Sign in with PayPal** (top right) and log in with the buyer account.
2. Click **Market**. Open any agent. Click **Re-run the proof**. The two result hashes match.
3. Click **Test-drive** on the same page to try other dates for free.
4. Click **Read the report** under AI due diligence.
5. Hold mode: filter **Pay if proven** and open **Fast Demo Agent (1s, 2-minute hold)**. Click **Buy**, pay with the PayPal button using the buyer account. Nothing is charged now. After 2 minutes the purchase page shows **Passed** (captured and paid out) or **Failed** (voided).
6. Instant mode: open any agent marked **Instant**, click **Buy**, pay, then click **Download JSON** or **Run on Parable**.
7. Click **Ledger**, then **Verify chain**, then **Try to rewrite history**.
8. To build an agent, sign in with the creator account, click **Build**, pick **Crypto** and **Bitcoin**, write your steps, click **Build with AI** (a few free tries per day), then **Backtest**.

You can also run it yourself with no keys and no internet: see "Run it locally in 2 commands" in the README. That mode uses a fake PayPal and bundled sample data.

Note: the demo creators have made-up emails, so the payout for the demo agents may show as needing a retry in the sandbox. Use an agent listed by the creator account above to see a clean payout. `<delete this note if you checked and it works>`
