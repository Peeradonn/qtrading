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
  data/       Binance klines fetch + cache; Roostoo price logger                        [to be designed]
  strategy/   pure functions: universe → signals → target weights                       [to be designed]
  backtest/   competition-faithful simulator + rolling-window scorer                    [to be designed]
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

## 5. Components to be designed

Each gets its own section here before implementation: data layer, strategy (signal definitions, gate design, parameters and their backtest plateaus), backtester (fee model, precision rounding, min-order, scoring windows), engine (state reconciliation, order idempotency, kill switch via committed config, alerting), deployment (EC2, systemd, log rotation).

## 6. Non-goals for v1

Limit orders; tokenized stocks (need a second data source and non-trading-hours logic); a second bot; any LLM or RL component; any arbitrage-like behaviour (banned).

## 7. Testing approach

TDD throughout. Unit tests are offline and deterministic (fake transport, fake clocks). Live checks are scripts under `scripts/` run by hand: `smoke_public.py` (no keys) now; a signed smoke test once competition keys exist. Before go-live: replay the backtester over the dry-run window and confirm it reproduces the live bot's decisions.

## 8. Open questions (Sep 18 workshop)

Ratio sampling frequency, annualisation and cross-team normalisation · definition of an "active trading day" · limit-order fill model · rate limits per endpoint · portfolio valuation price and final snapshot time · weekend price source for tokenized stocks · whether "1x short" exists · multi-bot capital and ranking rules.
