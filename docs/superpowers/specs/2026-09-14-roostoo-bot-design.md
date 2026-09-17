# Roostoo Momentum-Rotation Bot — Design

Status: living document. Sections are marked **done**, **approved**, or **to be designed**.
Started 2026-09-14 for the HK vs AU vs IN Quant Trading Hackathon (Sep 30 – Oct 13, 2026).

## 1. Purpose and what the scoring rewards

Trade a $1M mock spot portfolio autonomously on Roostoo for 14 days. Judging is staged:

1. **Rule compliance** — autonomous execution consistent with the declared strategy; traceable commit history; no manual API calls.
2. **Portfolio return** — top 20 per region advance.
3. **Composite** 0.4·Sortino + 0.3·Sharpe + 0.3·Calmar.
4. **Code and strategy review.**

Design consequences: max drawdown is the most valuable number to control (Calmar); positive skew is rewarded (Sortino); turnover must be budgeted (0.1% taker / 0.05% maker per fill); the bot must never trade blind or double-order; every decision must be logged and attributable to a commit.

## 2. Strategy summary — **locked 2026-09-16** (the "core")

Long-only momentum rotation over the 35 most liquid crypto pairs on Roostoo plus PAXG:

- **Signal, hourly:** for each asset, the return over 3, 7 and 14 days (ignoring the most recent 12 hours), each divided by the asset's realised volatility; averaged. Volatility is measured on live bars only.
- **Selection, once a day at 00:00 UTC:** rank by score, hold the top 6; a holding stays while it remains in the top 12 (hysteresis).
- **Weights:** inverse volatility.
- **Exposure:** scaled so estimated portfolio volatility is 2% per day (constant-correlation model); the remainder is cash. This rule does the drawdown control.
- **Hourly:** re-check volatility and exposure; trade a holding only if it has drifted more than 5 points from target.
- **Off, by evidence:** regime gates, drawdown brake, residual momentum, volume confirmation, funding filter, multi-hour selection, tokenized stocks (pending the workshop answer on their weekend pricing), a permanent gold sleeve (run 7 — gold earns its place by rank, averaging 18% of the book in-sample), a BTC short hedge (run 8 — a return-for-tails dial that reproduces the core's fortnight distribution without improving it), news/sentiment (the Fear & Greed index is price momentum with a survey attached).

**Exposure point revised 2026-09-17 (runs 9–10):** the competition entry is the same signal and selection with **equal weights and a 3%/day volatility target** (`configs/eqvt3.toml`); the core above stays as the operational fallback. The trade — rally participation for tail — is quantified in the whitepaper §5.2 and rows 9–10 below.

Twins for a possible second bot, same engine and signal: **conservative** (1.5% vol target) and **risk-on** (equal weights, no vol target).

In-sample (Sep 2024 – May 2026, ~43 independent fortnights) versus BTC buy-and-hold: median fortnight +0.88% vs +0.80%; 10th-percentile fortnight −6.4% vs −9.1%; worst fortnight −16% vs −30%; beats BTC in 56% of fortnights; Sharpe 0.89 vs 0.72; Sortino 1.47 vs 1.17; total +108% vs +32%; max drawdown −32% vs −50%; fees ≈ 0.3% per fortnight. **Robust across selection hours:** tails and total. **Not robust:** the better-than-BTC median and Sharpe hold only at 00:00 and 12:00 UTC — the in-sample edge is partly hour luck; 00:00 is kept as the a-priori daily-close convention. Out-of-sample (2026-05-15 → 09-14, one look): passed its pre-committed rule — worst fortnight −8.3% vs BTC −20.7%, max drawdown −14.6% vs −29.4%, beats BTC in 51% of windows, total +36.8% vs +13.8%. The risk-on twin did better still in that volatile, net-up period (+65%, but max drawdown −28.5%) — the two win in different regimes, which is the case for running both.

Evidence trail: the spike (2026-09-14) rejected a "buy the losers" alternative (−80% over the sample, −92% max drawdown); runs 1–6 (§7) built the core one decision at a time.

## 3. Architecture

```
src/qtrading/
  roostoo/    API client: signing, clock sync, typed endpoints, retry/throttle policy   [done]
  data/       Binance + Yahoo history, parquet cache, hourly UTC panel with stale mask   [done]
  strategy/   pure functions: universe → signals → target weights; baselines; momentum  [done]
  backtest/   competition-faithful simulator, rolling-window scorer, look-ahead check   [done]
  engine/     live loop: reconcile, decide, plan, execute, journal; paper + Roostoo exchanges  [done]
```

Boundaries: `strategy` is pure (prices in, target weights out) so backtest and live share it byte-for-byte. `engine` is the only module that places orders. `roostoo` knows nothing about strategy. A second bot = a second strategy module + config, same engine.

## 4. Component: Roostoo client — **done**

Files: `roostoo/signing.py`, `clock.py`, `client.py`, `models.py`, `errors.py`. Tests: `tests/test_signing.py`, `test_clock.py`, `test_client.py` (25 tests, fake transport).

Decisions:

| Decision | Rationale |
|---|---|
| Canonical param string (`k=v` sorted, `&`-joined, values **not** URL-encoded) is signed and then sent **verbatim** as the GET query / POST body | Verified against the docs' published test vector; eliminates "signed one thing, sent another" bugs |
| `Clock` measures offset to `/v3/serverTime`, refreshes every 10 min, `invalidate()` forces resync | Server rejects timestamps > 60 s off; lazy sync keeps constructors network-free |
| Reads retry transient failures with exponential backoff (3 attempts); `place_order` **never** retries — a lost response raises `OrderUncertain` | The engine must reconcile via `query_order` rather than risk a duplicate fill |
| `Success:false` raises `RoostooAPIError`, except documented empty results (`no pending order…`, `no order matched`) which return empty | Those are not errors |
| Minimum 250 ms between requests | Rate limits are undocumented; nothing in the bot may hammer the API |
| Signed requests/responses logged at INFO; public at DEBUG; secrets never logged | Trade-log evidence for rule compliance |
| Fee rates are read from `CommissionPercent` in order responses, not hardcoded | Docs' examples show 0.012%/0.008%; hackathon rules state 0.1%/0.05% |

Deferred: automatic resync-and-retry on a timestamp-rejection error (need the real error message first); per-endpoint rate limits (ask at the Sep 18 workshop).

## 5. Component: data layer — **done**

Files: `data/binance.py`, `yahoo.py`, `universe.py`, `store.py`. Tests: `tests/test_binance.py`, `test_yahoo.py`, `test_universe.py`, `test_store.py` (14 tests, fake HTTP / fake download / fake sources, `tmp_path` cache).

| Decision | Rationale |
|---|---|
| **Bars are indexed by close time** — the moment the close became known — everywhere | Look-ahead becomes impossible by construction: at time T anything with index ≤ T is usable |
| Grid rule: hour T holds the last bar closing in (T−1h, T]; a stock bar closing at :30 appears at the *next* hour | Conservative by design; tested explicitly |
| Hours with no closing bar carry the last close forward and are flagged in a `stale` mask | Signals must not mistake a frozen weekend stock price for a flat market; the mask lets them treat it correctly |
| Crypto from Binance public spot klines (`data-api.binance.vision`), no key; funding rates from the futures API as a positioning signal | Exchange prices, deep history, covers the whole Roostoo list. Yahoo's crypto is aggregated and patchy (no WLFI; PEPE under `PEPE24478-USD`) |
| Stock underlyings from `yfinance` (free, unofficial); mapping table `STOCK_UNDERLYING` in `universe.py`; unverified entries flagged | The only free hourly source for equities; 730-day cap on hourly data. Throttles unpredictably → everything cached |
| Universe built from a **committed** `exchangeInfo` snapshot (`data/snapshots/`) using the `AssetType` field; `CanTrade=false` and unmapped stocks excluded | Research is reproducible even if Roostoo relists pairs |
| Per-symbol parquet cache with incremental head/tail fetches; only the missing range is requested | Re-runs are cheap; the live bot refreshes one hour per asset per cycle |

Known limitation: a cached range whose latest bar precedes a no-trading period (stock over a weekend) re-requests the empty tail on every refresh. Harmless at our request rates; fix by recording a `fetched_through` timestamp if it ever matters.

## 6. Component: strategy contract + backtester — **done**

Files: `strategy/__init__.py` (contract, `State`, `eligible_mask`), `strategy/baselines.py`, `backtest/simulator.py`, `backtest/metrics.py`, `backtest/checks.py`, `scripts/run_backtest.py`. Tests: `test_simulator.py`, `test_metrics.py`, `test_checks.py`, `test_baselines.py` (20 tests).

**Strategy contract.** Two pure functions: `signals(prices) → DataFrame` (vectorised, causal operations only) and `targets(t, signals_at_t, state) → {pair: weight}`. No I/O, no clocks. The backtester and the live engine call the identical code.

| Decision | Rationale |
|---|---|
| Fill at the decision hour's close, slippage configurable (default 0) | Roostoo's ticker shows bid == ask; its mock engine has no spread to model |
| Fee on notional (taker 0.1% default; maker 0.05% selectable) | Competition rule |
| Quantity floored to `AmountPrecision`; orders under `MiniOrder` or under a $50 minimum trade notional skipped | Exchange rules from the snapshot; we would never place dust trades |
| No trades on stale bars | Unknown whether Roostoo fills frozen weekend stock prices; conservative |
| Sells execute before buys | A full rotation must fit in cash without leverage |
| Assets with a price at the panel's first bar count as established; later listings need `min_age_h` of history | Avoids listing-day chaos without excluding the whole starting universe |
| Scoring: daily samples at 00:00 UTC, ratios from daily simple returns (sample std, √365), Calmar = window return / max DD, every 14-day window stepping daily | Judges' sampling is unknown; all are parameters. Un-annualised Calmar because every team is scored on the same 14 days |
| Composite reported rank-normalised across compared strategies (best = 1, worst = 0) | The judges' normalisation is unknown; we want robustness to it |
| Holdout: everything after 2026-05-14 hidden unless `--oos` | Out-of-sample check reserved for the final decision |
| `assert_no_lookahead`: perturb prices after t; signals ≤ t must not change. Runs on every strategy before its numbers are printed | The bug that ruins backtests, caught mechanically |

## 7. Component: momentum strategy family — **done; research closed 2026-09-16**

File: `strategy/momentum.py` — one class, `Momentum`, driven by `MomentumParams`, so every hypothesis in the research plan is a configuration rather than new code. Tests: `tests/test_momentum.py` (signal arithmetic and the gate path hand-computed; each `targets()` rule in isolation).

| Decision | Rationale |
|---|---|
| Score = mean over lookbacks of (return over L h, skipping the latest `skip_h`) / (hourly vol · √L) | Risk-adjusted momentum (Barroso & Santa-Clara; Daniel & Moskowitz); multi-horizon average is a cheap ensemble; skipping recent hours avoids short-term reversal |
| Volatility is measured on live bars only | A carried-forward stock price is not a zero-return observation; naive vol would understate stock risk and overweight it |
| Selection on its own cadence (`select_every_h` or `select_hour_utc`); gate, brake and drift band every decision | Run 1 showed hourly re-selection churns ~1.4× capital/day. Exit risk fast, rotate slowly |
| Rank hysteresis: hold while rank ≤ `buffer_rank` (2K) | Halves turnover at no cost (spike and run 2) |
| Inverse-vol weights; exposure scaled to a daily vol target under a constant-correlation model | Continuous de-risking; vol spikes inside crypto selloffs, so cutting exposure when vol rises cuts it at the right moments (Moreira & Muir) |
| Binary regime gates (`market`, `own`) kept as options, **off** in the core | Every variant tested (runs 1–3) gave up 70–80% of return for a 5-point better worst case — whipsaw |
| Drawdown brake with cooldown and peak reset, via a strategy-owned `State.memory` | A brake without reset locked the book in cash forever (run 1); with reset it re-enters into continuing drawdowns (run 2). Kept as an option, **off** in the core |
| Residual momentum: log-return residuals against a rolling beta to BTC, blended by `residual_weight`; the market keeps its raw score; residual scaled by total vol | Alts are ~0.7-correlated with BTC; residual ranks pick assets with their own trend. Scaling by total vol keeps a near-clone's score at ~0 instead of 0/0 |
| Volume confirmation: score × clip(7d/30d dollar-volume ratio, 0.5, 1.5) | Trends on rising volume persist longer; the clip bounds the effect |
| Funding-rate crowding filter: drop assets whose 3-day mean perpetual funding exceeds `funding_max` | Extreme positive funding = crowded longs = fragile. Data: Binance futures, full history, keyless |
| Stocks & gold: selection at a fixed US-hours UTC hour | At 00:00 UTC every tokenized stock is stale and can never be selected |

### Research log

| Run | Date | Finding |
|---|---|---|
| 1 | 09-15 | Gross edge strong (+175% gross) but hourly re-selection paid 85% of capital in fees; drawdown brake without reset went flat forever; rank composite gameable by a flat strategy |
| 2 | 09-15 | Daily selection + dropping the 24h horizon: +188% net, BTC-like ratios, beats BTC in 50% of windows. Gates cost 70–80% of return. Vol targeting did the Screen 3 work |
| 3 | 09-15 | **Core locked:** inverse-vol, 2%/day vol target, daily selection, 3/7/14-day horizons — dominates BTC on every metric in-sample (medR +0.88% vs +0.80%, worst −16% vs −30%, beats BTC 56%, Sharpe 0.89 vs 0.72, maxDD −32% vs −50%). Lower vol target → higher return and smaller tails. Own gate dead. K 6≈8. Simulator tie-break non-determinism found and fixed (±10 pts of total return is noise) |
| 4 | 09-15 | Vol-target plateau 1.5–2.0% (2.5% falls off); K=6 > 8. Residual momentum (½) and volume confirmation each lifted Sharpe/Sortino ~0.15 with return and tails unchanged; funding filter at 0.05%/8h never triggered; stocks improved ratios vs a same-hour control but selecting at 15:00 UTC hurt the crypto book. Active days p10 = 7 → engine needs an activity floor |
| 5 | 09-15 | Residual + volume **together** worse than either alone and than the core → both noise, excluded. Funding filter flips sign between 0.02% and 0.03% → noise, excluded. **Hour sweep:** tails and total robust across all six selection hours (worst −15…−17%, maxDD −32…−35%, total +61…+111%); median/Sharpe above BTC only at 00 and 12 UTC |
| 6 | 09-16 | Overlapping selection tranches (0+12, 6+18, 3-a-day) average the hours' results and add 2–4 points of fees — no gain. Single daily selection at 00:00 UTC kept. **Core locked.** |
| OOS | 09-16 | One look at the sealed holdout (windows from 2026-05-15): pre-committed pass rule — worst fortnight and max drawdown smaller than BTC's, beats BTC in ≥ 45% of windows. **Result (109 windows, ~8 independent fortnights; BTC: median +0.03%, worst −20.7%, maxDD −29.4%, total +13.8%):** core median +0.41%, worst −8.3%, maxDD −14.6%, beats BTC 51%, total +36.8% — **passes**. Risk-on twin: median +2.63%, worst −15.3%, maxDD −28.5%, beats BTC 62%, total +65.1%, Sharpe 1.56 — dominated this volatile net-up period, i.e. the vol target's in-sample advantage reversed OOS (regime-dependent, as its design implies). Evidence for running both bots. Active days median 8 / p10 6 for the core, 7 / 5 for risk-on → the engine's activity floor is mandatory |
| 7 | 09-17 | **Gold sleeve — pre-registered (`scripts/gold_sleeve_study.py`), rejected; gold-by-rank validated.** Motivation: a descriptive check (new `field_beaten` metric) ranked the core against 35 hold-one-coin competitors per fortnight — it beats ≥60% of that field in 88% of BTC-down fortnights but 36% of BTC-up ones (risk-on twin ≈65% in both) — and PAXG is the only asset whose fortnight returns are uncorrelated with the core (0.03; stocks ≈0.5, crypto >0.7). Test: hold the idle cash the vol target leaves in PAXG (`sleeve=("PAXG/USD",)`, cash mode, fractions 0.25–1.0; book mode for comparison). In-sample vs core: median +0.96% → +1.82%, Sharpe 0.87 → 1.57, Sortino 1.36 → 2.35, total +103% → +126%, but worst −15.8% → −19.3% (flat-gold counterfactual −15.9% → −20.3%); post-May-15 tails worse (p10 −3.1% → −6.2%) as gold fell 6% → fails rules 1, 4, 5. **Why:** the core already holds gold *by rank* — 18% of the book in-sample, 22–29% in the January 2026 crash windows, 4% post-May when gold stopped trending; a post-hoc `core:xg` baseline (PAXG removed from the ranking pool) is worse on everything (worst −18.7%, total +71%, Sharpe 0.76, beats BTC 51%). A cash sleeve stacks gold's risk on top of the 2% target and is pro-cyclical (little idle cash before a crash), and in January 2026 gold fell 8–10% with crypto. Conditional gold beats unconditional gold — the gates-vs-vol-target lesson again. Sleeve code kept, off by default; 212 tests |
| 8 | 09-17 | **BTC short hedge — pre-registered (`scripts/hedge_study.py`), rejected.** Context: the user confirmed shorting exists (1x); the API docs describe no mechanism, so the study assumes a short is a SELL beyond the holding valued as a negative quantity, 0.1% fee both ways, no borrow cost, gross ≤ 1x. Implemented behind flags the live engine never sets: `plan_orders(allow_short=)`, `SimConfig.allow_short`, `MomentumParams.hedge_pair/hedge_ratio/max_gross` (short = ratio × long notional, nets against a long in the same pair, whole book scaled to the gross cap); 8 new tests, 220 total; core and risk-on equity reproduce the pre-change runs to 1e-16 with the flag on. Family: h ∈ {0.25, 0.5, 0.75, 1.0} on the core leg and on the full-exposure twin. **Result, in-sample vs core (+103%, p10 −6.7%, worst −15.8%, Sharpe 0.87, Sortino 1.36, top-40% 61%):** on the core leg every h lowers total AND ratios (h0.5: +65%, Sharpe 0.57) — the vol target and the hedge are redundant beta controls; on the twin the hedge is a dial: h0.25 +234%/worst −26%; h0.5 +187%/p10 −7.8%/worst −19.6%/Sharpe 0.87; h0.75 +138%/p10 −6.3%/worst −15.2%/Sharpe 0.83/top-40% 57%; h1 +103%/worst −13%/Sharpe 0.38. Nothing met rules 1–4 together; h0.75 on the twin equals the core's fortnight distribution within noise and ranks no better in rising fortnights (top-40% 32% vs 40%). Post-May the hedged books have better ratios (h0.75 Sharpe 2.08 vs 1.50) because BTC fell — regime-dependent, as a short BTC must be. Also: shorting the bottom-6 loses (daily spike: −27%, worst −40%, squeezes); the daily spike had overstated the hedge's ratio gain (Sharpe ≈1.1 at every h) — the harness with hourly decisions, fees and the drift band did not confirm it. **Live implications if a short is ever used:** realised gross drifted to 1.14–1.20× between rebalances → the engine would need a gross guard below 1x and reconcile must accept negative balances. Core stays. |
| 9 | 09-17 | **Exposure frontier — pre-registered (`scripts/exposure_study.py`) for the user's Screen 2 concern ("if BTC goes +20% in the window and we miss it, we fall out of the top 20").** The concern measured: in BTC>+10% fortnights the core captures 60% of BTC's move and reaches the top 40% of a 34-book hold-one-coin field 21–24% of the time (0% when BTC>+20%); the risk-on twin 139% and 78%. Cause is sizing and weighting, not information (news/sentiment rejected, row 8 note). **Run 1: downside-deviation targeting (1.5/2/2.5%) and an exposure floor (50/70%) — nothing passed:** up-market top-40% stays 37–42% (downside deviation rises in a crypto rally too), and the 77–80%-invested variants give up 3–4 points of worst fortnight for no rank. Code: `vol_target_on="downside"` (+`dvol` signal), `min_exposure`; 223 tests. **Post-hoc family, labelled: equal weight + vol target ("eqvt")** — the original research compared inverse-vol+vt against equal-weight-without-vt and never equal-weight+vt. A smooth dial (in-sample top-40% in BTC-up / BTC-down fortnights; worst; p10; Sharpe; Sortino; total): core 40/88/−15.8/−6.7/0.87/1.36/+103 · eqvt2 40/89/−16.5/−6.8/1.09/1.69/+121 (fees 8% vs 12%, 47% invested) · eqvt2.5 46/88/−20.5/−8.5/1.00/1.51/+149 · **eqvt3 52/85/−23.3/−10.3/1.04/1.68/+176** (BTC>10%: captures 94%, top-40% 43%) · eqvt3.5 57/80/−26.6/−11.3/1.14/1.92/+206 · eqvt4 60/77/−28.8/−12.1/1.11/1.68/+240 · risk-on 67/65/−33.2/−14.4/1.06/1.68/+263. Ratios sit at 1.0–1.14 / 1.5–1.9 across the whole family against the core's 0.87 / 1.36: **inverse-vol weighting was costing ratios at every target**, and with equal weight the vol target is a pure return-for-tails dial (return rises with the target — the "lower target, higher return" result of run 4 was specific to inverse-vol). Post-May the family is consistent (eqvt2.5: up 47/dn 85, worst −5.5%, Sharpe 1.88; eqvt3: 45/81, −8.2%, 1.59; core 27/85, −7.9%, 1.50). **Robustness at eqvt3:** selection hour 12 agrees (Sharpe 1.30, up 55, worst −22%); **K=8 does not** (in-sample Sharpe 0.80, Sortino 1.21 — below the core; post-May the best of all) → the equal-weight book is K-sensitive where inverse-vol was not; keep K=6 and treat the ratio gain as ~0.1 uncertain. **Formal verdict:** no configuration met rules 1–4 together, because rule 1 (+10 points of rally rank) and rule 3 (tails within 2 points) cannot both hold — the trade-off is real, not a flaw. **What changed:** the core is a dominated point on the frontier (eqvt2 has its tails with better ratios and lower fees); which point to run is a risk-appetite decision for the user — taken in row 10. |
| 10 | 09-17 | **Decision: the competition entry is the 3% equal-weight book (`configs/eqvt3.toml`; paper run `configs/paper-eqvt3.toml`); the core stays as the operational fallback.** The user weighed the trade of run 9 and accepted it. A field-size rule was considered and dropped: against a field of N compliant teams with 20 passing, the 3% book passes Screen 2 at least as often as the core at every N (N=30: 88% vs 82%; 50: 67% vs 60%; 60: 56% vs 53%; 80: 41% vs 41%; 100: 29% vs 30%; the post-May ordering is the same), so the choice does not hinge on the unknown team count. **Costs accepted, in-sample:** P(fortnight < −10%) 4% → 11%; P(< −15%) 0 → 3%; median 14-day drawdown 4.6% → 6.8%, p90 8.7% → 13.6%; top-20%-of-field rate in mildly falling fortnights 50% → 40%. Head to head the entry beats the core in 57% of fortnights and trails by a median 2.4 points when behind (worst −9.2, 2025-01-24). Conditions: K stays 6 (the ratio edge does not survive 8); paper-trade 09-17 → 09-30; the whitepaper describes the post-May period as a consistency check for the entry, not a holdout. **Engineering:** two paper bots on one host must not share the price cache (parquet writes are not atomic) → `Paths.cache` per bot (default `data/cache`); `paper-eqvt3` runs on a copy at `data/cache-paper-eqvt3`, git-ignored; 224 tests. paper-eqvt3 started under the supervisor alongside paper-core. |

## 8. Component: live engine — **done, in paper trading since 2026-09-16**

Files: `execution.py` (shared `plan_orders`), `engine/exchange.py`, `state.py`, `activity.py`, `journal.py`, `config.py`, `alerts.py`, `loop.py`; `scripts/run_bot.py`; `configs/paper-core.toml`, `core.toml`, `riskon.toml`. Tests: `test_execution.py`, `test_exchange.py`, `test_engine_state.py`, `test_activity.py`, `test_journal.py`, `test_config.py`, `test_alerts.py`, `test_loop.py` (38 tests).

| Decision | Rationale |
|---|---|
| Order planning lives in one shared `plan_orders()` used by the simulator and the engine | Backtest == live by construction, not by care |
| `Exchange` interface with `PaperExchange` (fills at the public Roostoo ticker, real fee, wallet on disk) and `RoostooExchange` | The whole loop runs keyless on real prices; swapping to the competition account changes one config line |
| Every cycle reconciles holdings, cash and equity from the exchange; strategy memory (selection, hysteresis, peak) persists to disk | A restart resumes instead of re-selecting; the exchange is the source of truth |
| Freshness gate: newest live BTC bar must be within 2 h; any exception anywhere → journal, alert, **no orders** | The bot never trades blind |
| Equity sanity: an unexplained move over 5% since the last cycle → hold one cycle and alert | Catches a wrong wallet, a bad price feed, or a bug before it trades on it |
| Activity floor: when the days left are only just enough to reach 8 of 14, the strategy is asked for a full rebalance (one-cycle `force_rebalance` flag it honours) | Backtests showed 6–7 active days in calm fortnights; the rule is a disqualifier |
| Sells before buys; stop the cycle on `OrderUncertain`; per-order cap 60% of equity as a runaway guard; at most 12 orders per cycle | Fits rotations in cash; never risks a duplicate fill; bounds any bug |
| Modes `trade` / `hold` / `liquidate` re-read from the committed config every cycle | The emergency stop is a commit, never a manual API call |
| Append-only JSONL journal stamped with the running commit; Telegram alerts optional and never raising | Rule-compliance evidence tied to code; the operator hears about problems |
| Cycle at :00:30 every hour, after the Binance hourly candle closes | Signals use complete bars |

First live paper cycle (2026-09-16 05:30 UTC): 6 targets, 6 fills, ~43% of equity deployed with inverse-vol weights under the 2% vol target. Next: 48-hour paper run, `scripts/replay.py` to re-simulate the journaled period and diff decisions, EC2 deployment with systemd.

## 9. Operational hardening — **done 2026-09-16**

| Component | Decision | Rationale |
|---|---|---|
| `qtrading/secrets.py`, `scripts/check_secrets.py`, `scripts/install_hooks.py` | A pre-commit hook blocks webhook URLs, bot tokens, ping URLs, AWS keys and long values assigned to secret-looking names; `# pragma: allowlist secret` marks deliberate exceptions | The repo is published for judging. A Discord webhook URL was pasted into the tracked `.env.example` and caught before staging — nothing in the repo would have stopped it |
| `engine/lock.py` | A bot claims a lock file at startup and exits 2 if a live process holds it | Two instances on one account would double every order and race on the state files |
| `engine/lock._is_alive` | Windows liveness goes through `OpenProcess`/`GetExitCodeProcess`, never `os.kill(pid, 0)` | On Windows `os.kill` maps signals to `TerminateProcess`: the "check" **killed the running bot**, observed live. The tests characterise the real OS, because an injected fake is what hid it |
| `engine/alerts.py` | Alerts to a Discord webhook (`ALERT_WEBHOOK_URL`), Telegram as fallback; heartbeat pings to `HEARTBEAT_URL` after every cycle, `/fail` after a failed one | A dead bot sends nothing, and silence is indistinguishable from calm — only an external service can catch it |
| `engine/report.py` | Digest on a cadence: equity, return since start, drawdown from peak, exposure, holdings, active-days pace, fills | The five questions an operator asks at 3 a.m., in one message |
| `roostoo/mock_server.py`, `scripts/mock_roostoo.py`, `configs/mock-core.toml` | A local server implementing the documented API over real HTTP, with faults injectable per endpoint; `BotConfig.base_url` points a bot at it | **No competition key is available before Sep 26.** Without this the signed order path would first run against the real exchange on the day it matters |

Rehearsal result (2026-09-16): the engine placed six signed market orders against the mock, all filled, and the
next cycle reconciled all six holdings from `/v3/balance` and correctly traded nothing (drift band). Equity moved
by exactly the commission. The wire format was confirmed by inspection: `pair=CAKE/USD&quantity=49717.55&side=BUY&timestamp=…&type=MARKET`
— sorted, unencoded, HMAC validated over those exact bytes.

## 10. Components to be designed

Each gets its own section here before implementation: momentum strategy family (signal definitions, gate design, parameters and their backtest plateaus), engine (state reconciliation, order idempotency, kill switch via committed config, alerting; `PaperExchange` with the client's interface for keyless dry runs), deployment (EC2, systemd, log rotation).

### Research plan (pre-registered 2026-09-14)

Hypothesis families, tested in this order through one harness with one scoring rule (median composite, 10th-percentile 14-day return, turnover), preferring parameter plateaus over peaks. Research stops ~Sep 23 regardless.

1. Multi-horizon volatility-adjusted momentum ensemble, skipping the most recent 12–24 h
2. Slow, banded regime filter (the naive 7-day BTC gate whipsawed in the spike)
3. Inverse-volatility weights, portfolio volatility target, drawdown brake
4. Residual momentum: alt returns net of BTC beta
5. Funding-rate crowding filter (Binance futures; full history available, unlike open interest)
6. Volume-confirmed momentum
7. Stocks and gold in the universe with their own momentum scores
8. Pullback entries within uptrends
9. Intraday seasonality — expected to fail after fees; test cheaply and discard

Excluded by design: ML price prediction (insufficient data), LLM sentiment (unverifiable, costs money), RL (overfits regimes), anything arbitrage-like (banned).

## 11. Non-goals for v1

Limit orders; tokenized stocks (need a second data source and non-trading-hours logic); a second bot; any LLM or RL component; any arbitrage-like behaviour (banned).

## 12. Testing approach

TDD throughout. Unit tests are offline and deterministic (fake transport, fake clocks). Live checks are scripts under `scripts/` run by hand: `smoke_public.py` (no keys) now; a signed smoke test once competition keys exist. Before go-live: replay the backtester over the dry-run window and confirm it reproduces the live bot's decisions.

## 13. Open questions (Sep 18 workshop)

Ratio sampling frequency, annualisation and cross-team normalisation · definition of an "active trading day" · limit-order fill model · rate limits per endpoint · portfolio valuation price and final snapshot time · weekend price source for tokenized stocks · how a short is placed and valued through the API (shorting confirmed available 2026-09-17; the docs describe no mechanism; tested in run 8 and not used — to be established on the competition account if ever needed) · how many teams per region (sets the height of the Screen 2 bar) · multi-bot capital and ranking rules (the rules give $1M per *team*).
