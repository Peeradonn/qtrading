# The organizers' brief

Everything the organizers have told us about the **HK vs Australia vs India Quant Trading Hackathon 2026**
(Susquehanna × Roostoo): the announcement, the official FAQ and the data-sources pack, copied here so the rules we
design against live in the repo rather than in a chat thread.

**Source:** organizer announcement, official FAQ and data-sources pack, as received on **2026-09-17**, with the
organizers' later corrections folded in on **2026-09-18**: live trading starts **Oct 1**, and the capital is
**$100,000**.
Where the organizers' own wording is ambiguous, this file says so rather than picking a reading.
The last section lists the points where this brief differs from what our code and whitepaper currently assume —
those are our notes, not the organizers'.

Registration is by [Typeform](https://form.typeform.com/to/j3Rza4Ml), not Luma. The
[Roostoo API documents](https://github.com/roostoo/Roostoo-API-Documents) are the API reference.

## Timeline

All dates are the organizers'; times are GMT+8 (HKT) where given.

| When | What |
| --- | --- |
| Sep 18, 3pm HKT | Online info session and technical workshop (Zoom; the join link and passcode are deliberately not reproduced in this public repo); recording shared afterwards |
| Sep 26 – Sep 29 | Preparation period: build the bot and **test deployment on Roostoo** with the test-account keys |
| Sep 29, 11:59pm HKT | Team registration deadline. No late teams |
| Oct 1 – Oct 14 | Live trading, 14 full days. Strategies may be iterated and redeployed throughout |
| Oct 1, 8pm | First trade must have executed by this point (FAQ Q26) |
| Before Oct 10 | Submit the open-source repo link, with README, for judging |
| Oct 17 | Top 15 finalists announced, 5 per region |
| Oct 23 | Finalist deck submission deadline (slides and/or markdown explaining the team's logic) |
| Oct 26 – 30 | Virtual finale in HK, AU and IN (tentative, subject to exam schedules) |
| One day in Nov 2 – 6 | In-person networking event in HK, for selected Hong Kong participants only |

**The start date is Oct 1.** The organizers confirmed this on 2026-09-18, settling the contradiction in the
original material, where FAQ Q25 said the main round began September 30. The first trade must be in by Oct 1, 8pm
(FAQ Q26), and the 14 days run to Oct 14.

## The mandate

Build a bot that trades Roostoo's real-time mock exchange autonomously — buy, hold and sell decisions made without
any manual intervention, through the documented POST and GET endpoints. Any approach is allowed: LLMs,
reinforcement learning such as PPO, traditional rule-based strategies, hybrids or something built from scratch.
The objective is to maximize portfolio return while minimizing risk, measured by return, Sortino, Sharpe and Calmar.

Any data source may be used. Roostoo covers cloud server costs only; other data costs, such as LLM API calls, are
not covered.

## Rules and constraints

- **No high-frequency trading, market-making or arbitrage strategies.** Excessive requests will fail.
- **Spot only, 1x long and short, no leverage**, on any asset available on Roostoo. Both long and short are
  allowed (FAQ Q31).
- **$100,000 mock portfolio** per team. The organizers revised this on 2026-09-18; earlier material and our own
  backtests used $1,000,000. For reference, the `data/snapshots` exchangeInfo says `InitialWallet: {"USD": 50000}`,
  which is the general test account, not the competition one.
- **Fees:** 0.1% taker (market orders), 0.05% maker (limit orders).
- **Rate limit: 30 calls per minute**, counting queries and executions alike. Over the limit, calls fail.
- **Deployment:** the bot must run on an AWS EC2 instance in an AWS sub-account provided by Roostoo, in the Sydney
  region unless stated otherwise (FAQ Q15). The EC2 volume cannot be resized under the restricted permissions —
  to get a larger one, delete the instance and launch a new one (FAQ Q14).
- **No frontend access to the competition account**, by design, so that manual trades cannot compromise the
  competition. Monitoring during the competition happens through the Roostoo app leaderboard; during testing,
  through `/v3/balance` and `/v3/query_order`.
- **Repos must be open-source** and are submitted for code validation. Strict anti-plagiarism policy; all
  submissions must be original.
- **Teams of 1–4 students**, one team per participant. Finalists verify student status with a university ID.
- Organizers reserve final rights on all competition matters.

### Changing the bot mid-competition (FAQ Q28)

Strategies may be updated during the competition, subject to three conditions:

- Every strategy or code change is committed and recorded in the repository, with a clear commit history.
- **Manual intervention is strictly prohibited:** no manually stopping the bot, no overriding its decisions, no
  discretionary trades through the API.
- All trades are generated autonomously by the submitted bot logic.

### API keys (FAQ Q30)

Two sets are issued: one for testing against a general Roostoo account, one for the official first round. They must
not be mixed up. Finalists receive a third, separate set for the finalist round.

### End of the competition (FAQ Q29)

Holdings are liquidated automatically by the system. Pausing bots afterwards is recommended to save resources.

## How teams are judged

Four screens, applied in order.

**Screen 1 — rule compliance (mandatory).** Violating either of these means not being selected as a finalist:

- *Trade log integrity:* the bot must show consistent, autonomous execution aligned with its declared strategy.
- *Commit history transparency:* strategy updates must have a consistent, traceable commit history, with no traces
  of manually called APIs.

**Screen 2 — portfolio return.** The top 20 teams per region by return advance:
`(final portfolio value − initial portfolio value) / initial portfolio value`.

**Screen 3 — composite risk-adjusted score.** `0.4 × Sortino + 0.3 × Sharpe + 0.3 × Calmar`. All underlying data,
calculations and results are published on finale day.

**Screen 4 — code and strategy review.** Clear and coherent strategy logic; a clean, well-structured, maintained
repository; and something that runs continuously and is compatible with the Roostoo platform.

The top 5 teams per region become finalists. At the final presentation round, sponsor and industry judges apply
their own criteria to pick the top 3 per region.

### Activity requirement

Each bot must have **at least 8 active trading days** out of the 14, with enough trades made from strategies each
day. Missing the first day is not itself disqualifying, but finalist and prize consideration favours bots active
for the full period (FAQ Q27).

## Prizes

Three categories: best finalist presentations, portfolio performance rewards, and a winning region award — the
region with the highest average return across its top 5 finalist teams. Three cash prizes per region. Total prize
pool and education continuity fund is at least HKD 80,000 / AUD 14,235 / INR 973,000.

Teams with strong, production-ready repositories may continue afterwards: continued Roostoo access, sponsored cloud
infrastructure, performance-based incentives, an invitation to contribute to an educational trading fund, and
profit-sharing opportunities with no downside risk.

## The Roostoo API, per the FAQ

- **Authentication:** API key, payload signed with HMAC SHA256, a timestamp, and the `RST-API-KEY` and
  `MSG-SIGNATURE` headers (Q19).
- **Endpoints:** `/v3/serverTime`, `/v3/exchangeInfo`, `/v3/ticker`, `/v3/balance`, `/v3/place_order`,
  `/v3/query_order`, `/v3/cancel_order` (Q20).
- **No OHLCV** — the API gives a ticker snapshot only, so candles must come from elsewhere (Q18).
- **Pricing is streamed from Binance**, so Roostoo's real-time prices are not different from Binance's (Q17).
- **Small negative balances** such as −0.01 after a sell are rounding error and harmless (Q24).
- **On `HTTP: Max retries exceeded`:** retry with exponential backoff, reduce request frequency, catch exceptions
  properly (Q21).

| Issue | Likely cause | Fix |
| --- | --- | --- |
| 422 error | Invalid params | Check the API docs |
| Max retries exceeded | Too many requests | Reduce frequency |
| Negative balance −0.01 | Rounding | Ignore |
| Cannot see the IAM role | Wrong login method | Use the invitation email |
| Instance error | Not fully provisioned | Wait and refresh |

## What the organizers recommend

Logging, at a minimum: timestamp, symbol, side, price, quantity, order ID and the API response; optionally PnL,
signal reason and strategy state (Q41). Local files, CloudWatch, SQLite/Postgres or CSV export all qualify (Q42).
Recording every request's success or failure internally is strongly recommended.

Repository practice (Q40, Q44): `.env` for API keys, a clear README, git branches, a tagged final submission,
reproducibility. The README should let a judge understand and reproduce the project — an overview of the strategy,
the architecture and components, the strategy itself (entry, exit, risk management, position sizing, assumptions)
and setup and run instructions.

### Data sources the organizers suggest

- **[Binance public data](https://data.binance.vision) (highly recommended, free).** Bulk archives of Binance
  history with no account or key: klines from 1s to 1mo, raw and aggregated trades, for spot and futures.
- **[CryptoDataDownload](https://www.cryptodatadownload.com) (free).** Pre-formatted CSVs across Coinbase,
  Binance, Kraken and others, plus derived metrics: market breadth, VaR and correlations, on-chain and macro data,
  and derivatives data.
- **[CoinAPI](https://docs.coinapi.io) (paid, with a free tier).** 400+ exchanges normalized into one format:
  tick data, L2/L3 order books, OHLCV, over REST, WebSocket/FIX and S3 flat files.

If Binance is blocked from a region: use the Roostoo API (same pricing stream), the Binance data dump site, or a
proxy if permitted (Q43).

## Where this differs from what our repo assumes

Our notes as of 2026-09-18, not the organizers' words. Each of these is open until someone resolves it.

- **Starting capital is $100,000**, ten times smaller than the $1,000,000 our whitepaper, backtests and paper
  wallets use. The strategy itself is scale-free — it works in weights, not dollars — and the order sizes survive
  the change: with six names at ~60% invested, a position is about $10,000, the coarsest quantity step in the
  universe is ZEC at $1.35 (0.014% of a position), every pair's exchange minimum is $1, and `min_trade_notional
  = 50` is 0.5% of a position, still small enough to be a dust filter rather than a constraint. Nothing needs
  changing, and the paper books can keep running at their current size.
- **Competition start: resolved to Oct 1**, and `configs/core.toml`, `configs/eqvt3.toml` and
  `configs/riskon.toml` now set `competition_start = 2026-10-01`, so the 8-of-14 activity floor counts the window
  the organizers actually score.
- **Rate limit.** The client's `min_interval_s = 2.0` spaces requests at exactly 30 per minute — the documented
  ceiling, with no headroom for a retry landing inside the same minute.
- **Maker fees.** We model and pay 0.1% taker on market orders. Limit orders are charged half that. Weighed on
  2026-09-18: the entry pays about 0.25% of equity a fortnight in fees, so limit orders can save 0.12% at most, and
  in the harness the halved fee is worth less than path noise (in-sample total +146% to +159%, holdout +32% to
  +28%). Whether the saving is free depends on what Roostoo does with a marketable limit order, which the API
  documents do not say. One pre-registered order on the test account decides (`scripts/limit_order_check.py`,
  runbook "Limit orders"); until then nothing is built.
