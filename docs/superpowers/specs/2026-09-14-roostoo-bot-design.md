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

## 2. Strategy summary (approved; details to be designed in §5)

Long-only **dual momentum rotation** over Roostoo's liquid universe (crypto, PAXG, later tokenized stocks):

- Cross-sectional ranking by multi-horizon, volatility-adjusted momentum; hold top *K* (≈6).
- Absolute-momentum and market-regime gate → cash when trends are absent. Spike evidence (2026-09-14) showed a naive 7-day BTC gate whipsaws; the filter must be slower and banded.
- Inverse-volatility weights; portfolio volatility target ≈ 3%/day; drawdown brake.
- Hysteresis: hold while rank ≤ 2K. Spike showed this halves turnover at no cost.
- Hourly decisions, market orders in v1; limit orders with fallback in v1.5.

Evidence: a rolling-14-day backtest over Sep 2024 – Sep 2026 on 35 liquid pairs rejected a "buy the losers" alternative (−80% over the sample, −92% max drawdown) and confirmed momentum as the only long-only approach with positive expectancy and the right skew.

## 3. Architecture

```
src/qtrading/
  roostoo/    API client: signing, clock sync, typed endpoints, retry/throttle policy   [done]
  data/       Binance + Yahoo history, parquet cache, hourly UTC panel with stale mask   [done]
  strategy/   pure functions: universe → signals → target weights; baselines; momentum  [done]
  backtest/   competition-faithful simulator, rolling-window scorer, look-ahead check   [done]
  engine/     live loop: reconcile state, diff targets vs holdings, place orders, log   [to be designed]
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

## 7. Component: momentum strategy family — **implemented; research in progress**

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
| 4 | 09-15 | Plateau check and families 4–7 as additions — results to be recorded |

## 8. Components to be designed

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

## 9. Non-goals for v1

Limit orders; tokenized stocks (need a second data source and non-trading-hours logic); a second bot; any LLM or RL component; any arbitrage-like behaviour (banned).

## 10. Testing approach

TDD throughout. Unit tests are offline and deterministic (fake transport, fake clocks). Live checks are scripts under `scripts/` run by hand: `smoke_public.py` (no keys) now; a signed smoke test once competition keys exist. Before go-live: replay the backtester over the dry-run window and confirm it reproduces the live bot's decisions.

## 11. Open questions (Sep 18 workshop)

Ratio sampling frequency, annualisation and cross-team normalisation · definition of an "active trading day" · limit-order fill model · rate limits per endpoint · portfolio valuation price and final snapshot time · weekend price source for tokenized stocks · whether "1x short" exists · multi-bot capital and ranking rules.
