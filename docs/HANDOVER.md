# Owner checklist: from this folder to a submitted project

Do the sections in order. Every command says which folder to run it in. Every website step says where to click.

Words used here:
- **Sandbox**: PayPal's test world. The money is fake.
- **REST app**: a record in your PayPal developer account that gives you a Client ID and a Secret (a user name and a password for your server).
- **Webhook**: PayPal calls your website to say "something happened" (for example, a payment was captured).
- **Basis points (bps)**: 100 bps = 1%.

Deadline: 12 Nov 2026, 12:00 PT. Do not start the Render deploy last.

---

## A. Create the PayPal sandbox app

1. Open https://developer.paypal.com and click **Log in to Dashboard** (top right). Use your normal PayPal login.
2. In the dashboard click **Apps & Credentials** (left menu).
3. Make sure the switch at the top says **Sandbox** (not Live).
4. Click **Create App**.
5. Type the name `Parable`. Choose the type **Merchant**. Click **Create App**.
6. On the app page, copy the **Client ID**. Under **Secret key 1** click **Show**, then copy the secret.
7. In the repo folder, create your settings file. Run this in the repo root folder (`parable-continuity`):
   ```bash
   cd ~/parable-continuity && cp .env.example .env
   ```
8. Open `.env` in an editor and fill in these lines (no spaces around `=`, no quotes):
   ```
   PAYPAL_CLIENT_ID=<paste Client ID>
   PAYPAL_CLIENT_SECRET=<paste Secret>
   PAYPAL_ENV=sandbox
   SESSION_SECRET=<a long random text>
   ```
   To make a random text, run this in any folder: `python3 -c "import secrets; print(secrets.token_hex(32))"`
9. Never paste these values into chat, a screenshot, a commit or the video. `.env` is already in `.gitignore`.

## B. Turn on "Log in with PayPal" and set the return URLs

Parable signs everyone in with PayPal. The code builds the return address as `PUBLIC_BASE_URL` + `/paypal/callback`.

1. Still on the app page (Apps & Credentials > Parable), scroll down to **Features**.
2. Tick **Log in with PayPal**. Click **Advanced settings** (a link next to it).
3. Tick the information Parable asks for. The code asks for these scopes: `openid`, `profile`, `email` and `https://uri.paypal.com/services/paypalattributes`. In the PayPal screen this means: **Full name**, **Email address**, and the account status / verification item. Tick all of them. PayPal's labels change from time to time, so tick every item that matches.
4. In **Return URL** add both of these, one at a time (use **Add** after each one). For `localhost` PayPal accepts `http` in sandbox:
   - `http://localhost:8000/paypal/callback`
   - `https://<your-render-name>.onrender.com/paypal/callback` (add this in section H when you know the address)
5. Click **Save changes** at the bottom.
6. Also tick **Payouts** under **Features** (see section C) and save.

If sign-in later shows "redirect_uri mismatch", the Return URL list does not contain exactly `PUBLIC_BASE_URL/paypal/callback`. Check for a missing `https`, a slash at the end, or a different port.

## C. Create the sandbox accounts

You need at least two sandbox accounts. They are fake PayPal accounts with fake money.

1. In the dashboard click **Testing Tools** (left menu), then **Sandbox Accounts**.
2. Click **Create account**.
3. Create a **Personal** account. Country: United States. Click **Create**. This is the **buyer**. It pays.
4. Click **Create account** again and create a **Business** account. Country: United States. This is the **creator**. It signs in to sell and receives payouts.
5. PayPal also made one default Business account when you opened the dashboard. It owns the REST app, so captured money lands there and payouts are sent from it. Leave it alone.
6. To see a sandbox account's email and password, click the three dots (**...**) on its row, then **View/Edit account**. Copy the email and the system-generated password. You use these to log in on the PayPal pages that Parable opens.
7. Check that **Payouts** is on for the app: Apps & Credentials > Parable > **Features** > **Payouts** is ticked. If you cannot tick it in sandbox, payouts will show as errors in Parable. In that case open a PayPal developer support ticket or ask in the hackathon chat.
8. The buyer and the creator must be different accounts. Parable refuses a self-purchase (the same PayPal account as buyer and seller).

Important: the demo creators (Priya Raman, Tomas Lindqvist, Dana Whitfield) have made-up `example.com` emails. A payout to such an email goes to no real sandbox account, so PayPal may mark it unclaimed or failed, and Parable shows the purchase as needing a retry. For a clean payout demo, use an agent that your own Business sandbox account listed (see test steps 12 to 19).

## D. Add the webhook

A webhook needs an address PayPal can reach from the internet. `localhost` does not work. Do this on Render (section H), or locally with a tunnel tool such as ngrok or cloudflared.

1. Apps & Credentials > Parable. Scroll down to **Webhooks**. Click **Add Webhook**.
2. **Webhook URL**: `https://<your-render-name>.onrender.com/paypal/webhook`
3. Tick these **Event types** (these are the ones Parable handles):
   - Payment authorization created (`PAYMENT.AUTHORIZATION.CREATED`)
   - Payment authorization voided (`PAYMENT.AUTHORIZATION.VOIDED`)
   - Payment capture completed (`PAYMENT.CAPTURE.COMPLETED`)
   - Payment capture denied (`PAYMENT.CAPTURE.DENIED`)
   - Payouts batch success (`PAYMENT.PAYOUTSBATCH.SUCCESS`)
   - Payouts batch denied (`PAYMENT.PAYOUTSBATCH.DENIED`)
   - Payouts item succeeded (`PAYMENT.PAYOUTS-ITEM.SUCCEEDED`)
   - Payouts item failed (`PAYMENT.PAYOUTS-ITEM.FAILED`)
   - Payouts item unclaimed (`PAYMENT.PAYOUTS-ITEM.UNCLAIMED`)
4. Click **Save**. The webhook now shows an **ID** (a short code). Copy it.
5. Put it in your settings as `PAYPAL_WEBHOOK_ID=<the ID>`. On Render, set it in the service's Environment tab (section H). Without it, every webhook is stored as "unverified" and is ignored.
6. To see that it works: open the **Ledger** page in Parable. The box **Recent PayPal webhooks** lists events with a verified mark.

Each webhook URL has its own ID. If you also make a tunnel webhook for local tests, use that ID locally and the Render ID on Render.

## E. Optional keys

| What | Where to get it | Setting |
|---|---|---|
| Stocks (Twelve Data) | https://twelvedata.com : **Sign up**, then in the dashboard click **API keys** and copy the key | `TWELVE_DATA_KEY` |
| Free AI models, AI due diligence, AI shopper (Google) | https://aistudio.google.com/apikey : click **Create API key** | `GEMINI_API_KEY` (and optionally `GEMINI_MODELS`, `GEMMA_MODELS`, comma-separated model names) |
| Jev models | https://autoloops.ai/console : sign up, copy the key | `AUTOLOOPS_API_KEY` |
| Claude analyst (optional) | https://console.anthropic.com : API keys | `ANTHROPIC_API_KEY` and `CLAUDE_MODELS`, and set `AI_ANALYST_BRAIN=claude:<model>` |
| A visitor's own OpenAI, Anthropic or Gemini key | Not a server setting. In the site click the **AI** chip in the top bar, choose the provider, paste the key | stored in that browser only |

Without `GEMINI_API_KEY`, the free AI choices are empty, due diligence uses plain rules instead of AI, and visitors can still build with their own key.

## F. Run it locally with the real sandbox keys

1. Build the website. Run in the `frontend` folder:
   ```bash
   cd ~/parable-continuity/frontend && npm install && npm run build
   ```
2. Start the server. Run in the `engine` folder:
   ```bash
   cd ~/parable-continuity/engine && PARABLE_DEMO_SEED=1 uv run uvicorn parable.api:app --port 8000
   ```
   The server reads `.env` from the repo root. `PUBLIC_BASE_URL` is `http://localhost:8000` by default, which matches the first Return URL in section B.
3. Open http://localhost:8000. The top of the page should say "PayPal sandbox mode — no real money moves." If it says "PayPal sandbox keys not set — payments are simulated", the keys were not read. Check the `.env` file name and location (repo root).
4. To start fresh, stop the server and delete `engine/parable.db`, then start again.

## G. Manual test script (about 20 steps)

Use two browser windows: a normal one for the **creator** and a private window for the **buyer**. Keep section F running.

| # | Do this | Expect |
|---|---|---|
| 1 | Normal window: open http://localhost:8000 | Market page with demo agents and the sandbox banner |
| 2 | Click **Sign in with PayPal** (top right). On the PayPal page log in with the sandbox **Business** account. Click the consent button | You return to the site and your name shows top right |
| 3 | Click **Build**. In step 1 click **Crypto**, then the **Bitcoin** chip | A live price and a candle chart appear |
| 4 | In step 2 type in **Describe your steps**: `Buy when the 12 period moving average crosses above the 26 period one. Sell when it crosses back. Stop loss 3 percent.` Click **Build with AI** | Rule chips appear in plain words, and "Formulas are valid." The AI chip in the top bar counts one free try down |
| 5 | In step 3 click **Backtest** | A metrics grid (Return, Buy and hold, Worst drop, Sharpe, Trades, Win rate...) and an equity chart against buy and hold |
| 6 | Click **Benchmark models**, tick two or more models, click **Benchmark models** again | A table with one row per model and a "Buy and hold" row, and an overlay chart. A model that fails shows an error row instead of stopping the run |
| 7 | Click **Find best** | A table of settings with Train and Test columns. Overfit ones are marked. Click one to use it |
| 8 | Click **Replay**, then **Play** | The backtest is animated with buy and sell markers |
| 9 | Click **Save version** at the top | Button changes to **Saved**. The page you see in **My agents** now lists the agent |
| 10 | Upload test: in step 1 click **Mine**, drag in `engine/parable/lab/samples/BTCUSDT_1h.csv`, and click **Use this data** if it asks to match columns | The dataset appears as a chip. A backtest on it works. Selling it only offers **Instant** |
| 11 | Back on your saved Bitcoin agent: click **Go live** (Test step) | Live equity points arrive every few seconds. The chart updates |
| 12 | Click **Sell**. Title `Test Trend`, price `1`, choose **Instant**, keep "Allow free test-drive" ticked, click **List for sale** | You land on the agent page. It shows a proof, a live track starts, and the **Buy** button is not shown, only "Your listing" |
| 13 | Private window: open http://localhost:8000, click **Sign in with PayPal**, log in with the sandbox **Personal** account | Signed in as the buyer |
| 14 | Open **Market** and click the `Test Trend` card. Click **Re-run the proof** | A claim-versus-re-run table. The result hashes are equal and it says the proof matches |
| 15 | On the same page use **Test-drive**: pick a start date and click **Test-drive** | A new result on other dates, free, no key |
| 16 | Click **Read the report** under **AI due diligence** | A short plain-words report with red flags if there are any. Numbers match the page |
| 17 | Click **Buy**. In the Checkout box click the PayPal button. Log in with the Personal account and click **Pay**/**Continue** | You return to the Purchase page. Status goes to captured, then paid out. A **Your license** box shows |
| 18 | Click **Download JSON** and then **Run on Parable** | A `.json` file downloads. A live practice run starts. It also shows in **My agents** under bought agents |
| 19 | In the creator window open the PayPal sandbox site https://www.sandbox.paypal.com and log in with the **Business** account | Activity shows the payout of the price minus the fee (10% by default) |
| 20 | Hold mode: in the buyer window open **Market**, filter **Pay if proven**, open **Fast Demo Agent (1s, 2-minute hold)** (only exists with internet) and click **Buy** | Checkout says "Charged now $0.00" and "Held in PayPal $9.00". Pay with PayPal. The purchase page shows a live trial for 2 minutes |
| 21 | Wait 2 minutes | A verdict box says **Passed** or **Failed**. Passed: the hold is captured and the seller payout is sent. Failed: the hold is voided and the buyer is not charged. If the payout fails because the demo creator email is fake, a **Needs a retry** box appears. Use **Retry** or test payouts with your own Business listing instead |
| 22 | Ledger: click **Ledger**, then **Verify chain** | "Chain intact. N entries checked" |
| 23 | Click **Try to rewrite history** | Shows a before and after of one entry, and "Chain broken at entry #N" |
| 24 | On **Ledger** look at **Recent PayPal webhooks** (needs section D done and a public URL) | Events listed with a verified mark |
| 25 | As the creator, open your own listing and try to buy it | "This is your own listing." Nothing is charged |

Things that go wrong most often: wrong Return URL (step 2), no Payouts feature (step 19), `PUBLIC_BASE_URL` not matching the address in your browser, and a fake demo-creator email in step 21.

## H. Deploy on Render

### H1. Push the code to a new public GitHub repo

Important: this folder has a remote called `ethglobal-local`. It points to your frozen ETHGlobal project folder. **Never push to it.** Remove it so you cannot do that by accident. This does not touch the other folder.

1. Look at what would be committed. Run in the repo root:
   ```bash
   cd ~/parable-continuity && git status
   ```
   Delete scratch files you do not want (the loose `*.json` files in `engine/`, for example `engine/bench.json`, `engine/ids.json`, `engine/proof.json`, `engine/spec.json`).
2. Check that no secret is tracked. Run in the repo root:
   ```bash
   cd ~/parable-continuity && git ls-files | grep -i "\.env"
   ```
   The only line allowed is `.env.example`.
3. Search the history for key-like text. Run in the repo root and read the output:
   ```bash
   cd ~/parable-continuity && git log --all -p | grep -nE "AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}|PRIVATE_KEY=0x[0-9a-fA-F]{60,}" | head
   ```
   Empty output is good. If anything shows, stop and rotate that key first.
4. Remove the dangerous remote:
   ```bash
   cd ~/parable-continuity && git remote remove ethglobal-local
   ```
5. Make the commit:
   ```bash
   cd ~/parable-continuity && git add -A && git commit -m "Parable v2: agent workshop and marketplace with PayPal"
   ```
6. On https://github.com click **+** (top right) > **New repository**. Name `parable`. Choose **Public**. Do **not** tick "Add a README" or "Add a license". Click **Create repository**.
7. Connect and push (replace `<you>`):
   ```bash
   cd ~/parable-continuity && git remote add origin https://github.com/<you>/parable.git && git push -u origin main
   ```
8. Open the repo page and check that the license shows as **MIT** on the right side.

### H2. Create the service on Render

1. Open https://dashboard.render.com and sign in. Click **New +** (top right) > **Blueprint**.
2. Connect your GitHub account if asked, and choose the `parable` repo. Click **Connect**.
3. Render reads `render.yaml`. It creates one web service called `parable`, built from the `Dockerfile`, with a 1 GB disk mounted at `/var/data`. The disk needs a paid instance type (the file uses `starter`). The database file lives at `/var/data/parable.db`, so it survives deploys.
4. Render asks for the values marked secret. Fill them in:
   - `PUBLIC_BASE_URL`: `https://parable.onrender.com` (if the name `parable` is taken, Render gives another name; put the real address in step 6)
   - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`: from section A
   - `PAYPAL_WEBHOOK_ID`: leave empty for now
   - `GEMINI_API_KEY`, `AUTOLOOPS_API_KEY`, `TWELVE_DATA_KEY`: from section E (leave empty to skip)
   - `GEMINI_MODELS`, `GEMMA_MODELS`, `ANTHROPIC_API_KEY`, `CLAUDE_MODELS`: optional
   `SESSION_SECRET` is generated for you.
5. Click **Apply**. Wait until the service says **Live** (the first build takes a few minutes).

### H3. Set the public address in PayPal

1. On the service page, copy the address at the top (like `https://parable-abcd.onrender.com`).
2. Render dashboard > your service > **Environment** (left). Set `PUBLIC_BASE_URL` to exactly that address with no slash at the end. Click **Save, rebuild, and deploy**.
3. PayPal dashboard > Apps & Credentials > Parable > **Return URL**: add `https://<that address>/paypal/callback`. Save.
4. Add the webhook (section D) with `https://<that address>/paypal/webhook`. Copy its ID.
5. Back on Render > **Environment**: set `PAYPAL_WEBHOOK_ID` to that ID. Save and deploy.
6. Open the Render address. The page should show the sandbox banner and the seeded demo agents. Run test steps 2, 14, 17, 20 and 24 on the live address.

Notes:
- The demo agents (`PARABLE_DEMO_SEED=1`) are created at each start if they are missing. They never duplicate.
- Run one copy of the service only. The database is a single SQLite file.
- If Render says the health check failed, open the service's **Logs**. The check calls `/api/info`.
- Yahoo stock data may be blocked from Render. Crypto, forex and funds do not use Yahoo. Add `TWELVE_DATA_KEY` for stocks.

## I. Devpost submission checklist

Open https://devpost.com, find the PayPal AI Hackathon, click **Enter a submission**.

- [ ] Project name and tagline from `docs/SUBMISSION.md`
- [ ] The story sections (Inspiration, What it does, How we built it, Challenges, Accomplishments, What we learned, What's next) pasted from `docs/SUBMISSION.md`
- [ ] "Built with" list pasted from `docs/SUBMISSION.md`
- [ ] The explanation of how the project was significantly updated during the submission period (Oct 1 to Nov 12 2026) pasted from `docs/SUBMISSION.md`
- [ ] Public GitHub repo link, with the license showing as MIT
- [ ] Hosted link: the Render address
- [ ] Testing instructions and sandbox login details, with the placeholders replaced by real sandbox emails and passwords (they are fake accounts, but still do not use a real PayPal login)
- [ ] Demo video, 2 minutes 50 seconds at most, uploaded to YouTube or Vimeo as **Public** or **Unlisted** and linked (`docs/VIDEO_SCRIPT.md`)
- [ ] Screenshots (at least 3) uploaded to the gallery and added to the README (the README has a TODO for this)
- [ ] Cover image
- [ ] The Render service is running and has been tested after the last deploy
- [ ] README section "Screenshots" filled in or removed
- [ ] Submit before 12 Nov 2026, 12:00 PT. After submitting, open the public project page and check every link in a private window.
