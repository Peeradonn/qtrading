# qtrading — momentum-rotation bot for Roostoo

Entry for the **HK vs Australia vs India Quant Trading Hackathon 2026** (Susquehanna × Roostoo).
A long-only, rule-based momentum-rotation strategy trading a $1M mock spot portfolio autonomously
on the Roostoo exchange, designed around the competition's scoring (return, then
0.4·Sortino + 0.3·Sharpe + 0.3·Calmar).

**Status (2026-09-14):** Roostoo API client, market-data layer, and competition-faithful backtester complete and
tested. Strategy research in progress; live engine next. See [the design doc](docs/superpowers/specs/2026-09-14-roostoo-bot-design.md)
for the strategy rationale, architecture and decision log.

## Layout

```
src/qtrading/roostoo/   API client — signing, server-clock sync, typed endpoints, retry/throttle policy
src/qtrading/data/      Binance (crypto) + Yahoo (stock underlyings) history, parquet cache, hourly UTC panel
data/snapshots/         committed exchangeInfo snapshot the universe is built from
data/cache/             (git-ignored) parquet price cache — populate with scripts/fetch_history.py
src/qtrading/strategy/  pure signal → target-weight functions, shared by backtest and live; baselines
src/qtrading/backtest/  simulator (Roostoo fees/precision/min-order), rolling-14-day scorer, look-ahead check
src/qtrading/engine/    (planned) live loop: reconcile, diff, order, log
tests/                  offline unit tests (pytest)
scripts/                live checks run by hand
docs/                   design spec
```

## Setup

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
copy .env.example .env        # then fill in ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY — .env is git-ignored
```

## Verify

```powershell
.venv\Scripts\python.exe -m pytest              # offline unit tests
.venv\Scripts\python.exe scripts\smoke_public.py  # live check of public endpoints, no keys needed
.venv\Scripts\python.exe scripts\fetch_history.py # pull ~2y of hourly history into data/cache (re-runs fetch only the tail)
.venv\Scripts\python.exe scripts\run_backtest.py  # score strategies on rolling 14-day windows (add --oos for the holdout)
```

## Data conventions

Every bar is indexed by its **close time** — the moment its close price became known — and the hourly panel
places a bar in the first grid hour at or after that moment. Consumers may use anything with index ≤ *now*;
look-ahead is impossible by construction. Hours with no closing bar (stocks outside US trading hours) carry the
last close forward and are flagged in a `stale` mask so signals can treat them correctly.

## Principles

- **Autonomous.** The bot alone calls the API. There is no manual-trading path, by design.
- **Never trade blind.** On any uncertainty (lost response, stale data, clock drift) the bot reconciles or holds; it never guesses.
- **Backtest = live.** Strategy code is pure and shared, so the simulator can replay live decisions exactly.
- **Every request logged.** Signed requests and responses are logged with the running commit hash.
