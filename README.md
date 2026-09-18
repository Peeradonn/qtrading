# qtrading — momentum-rotation bot for Roostoo

Entry for the **HK vs Australia vs India Quant Trading Hackathon 2026** (Susquehanna × Roostoo).
A long-only, rule-based momentum-rotation strategy trading a $100k mock spot portfolio autonomously
on the Roostoo exchange, designed around the competition's scoring (return, then
0.4·Sortino + 0.3·Sharpe + 0.3·Calmar).

**Status (2026-09-18):** the core was locked on 2026-09-16 after six research runs and an out-of-sample check; runs 7–11
mapped the exposure frontier, chose the competition entry on it (whitepaper §5.2) and closed the stocks question: the same signal with equal weights
and a 3%/day volatility target, `configs/eqvt3.toml`, with the core kept as the fallback. Live engine complete; three books
(core, entry, entry with a short leg) paper-trading on real Roostoo prices. On 2026-09-18 the universe became a rule,
a rolling liquidity floor over all 65 listed crypto pairs, after we measured a hindsight bias in the fixed list of 35
(whitepaper §8). Next: EC2 deployment, then the competition account on Oct 1.
**Start here:** [the whitepaper](docs/whitepaper.md) explains the strategy, the reasoning about the scoring
function, the evidence, and every hypothesis we tested and rejected. The [design doc](docs/superpowers/specs/2026-09-14-roostoo-bot-design.md)
is the full decision log and research history; [docs/competition-brief.md](docs/competition-brief.md) is
the organizers' rules, timeline and scoring, as received.

**The strategy in one paragraph.** Hourly, score every crypto pair Roostoo lists (65, gold included) whose trailing
7-day volume clears $5M a day, on its 3-, 7- and 14-day returns divided by its own volatility. Once a day, hold the top 6, keeping a holding while it stays in
the top 12. Weight them equally and scale the whole book so estimated portfolio volatility is 3% a day; the rest is
cash. Rebalance only when a holding drifts more than 5 points from target. No regime switches, no machine learning.
The fallback core weights by inverse volatility at a 2% target: shallower tails, less of a rally. The rules allow a 1x short, and both uses of it went through the harness (whitepaper §7). A BTC hedge improves nothing
the competition scores. A short leg on the ranking's losers is different: it loses money on its own, yet as a
quarter of the book it roughly doubles the ratios and cuts the tails, at some cost in rally rank. It is not in the
book because it rests on exchange mechanics the API documents do not describe and we have not yet been able to test. In-sample, at every
liquidity floor we tested, the entry beats BTC on median fortnight and total return and cuts its worst fortnight from
−30% to between −17% and −20%; the core roughly halves BTC's tails and nearly triples its total, with a median about
level with BTC's. Those are the figures after we found a hindsight bias in our own universe and removed it, which cost
most of the edge the first backtests showed, and after we found that the ratios move with an arbitrary parameter
more than the tails do (whitepaper §6, §8).

## Layout

```
src/qtrading/roostoo/   API client — signing, server-clock sync, typed endpoints, retry/throttle policy
src/qtrading/data/      Binance (crypto) + Yahoo (stock underlyings) history, parquet cache, hourly UTC panel
src/qtrading/strategy/  pure signal → target-weight functions, shared by backtest and live; baselines; momentum
src/qtrading/backtest/  simulator (Roostoo fees/precision/min-order), rolling-14-day scorer, look-ahead check
src/qtrading/execution.py  plan_orders() — the one order planner shared by backtest and live
src/qtrading/engine/    live loop: reconcile, decide, plan, execute, journal; paper + Roostoo exchanges
configs/                one TOML per bot (mode, strategy params, paths, limits)
src/qtrading/secrets.py    credential scanner behind the pre-commit hook
data/snapshots/         committed exchangeInfo snapshot the universe is built from
data/cache/             (git-ignored) parquet price cache — populate with scripts/fetch_history.py
tests/                  offline unit tests (pytest)
scripts/                research runs, data fetches, the bot runner
docs/                   design spec, research log, and the organizers' brief
```

## Setup

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
copy .env.example .env        # then fill in ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY — .env is git-ignored
.venv\Scripts\python.exe scripts\install_hooks.py   # pre-commit hook that blocks credentials
```

This repo is published for judging, so every credential lives in `.env` (git-ignored) and never in a tracked file.
The pre-commit hook scans staged changes for webhook URLs, bot tokens and secret-looking assignments; run
`scripts\check_secrets.py --all` to scan the whole tree. Mark a deliberately public value (such as the API docs'
test vector) with a trailing `# pragma: allowlist secret`.

## Verify

```powershell
.venv\Scripts\python.exe -m pytest                                              # offline unit tests
.venv\Scripts\python.exe scripts\smoke_public.py                                # live check of public endpoints, no keys
.venv\Scripts\python.exe scripts\fetch_history.py                               # ~2y of hourly history into data/cache
.venv\Scripts\python.exe scripts\run_backtest.py                                # rolling 14-day scoring (--oos for the holdout)
.venv\Scripts\python.exe scripts\run_bot.py --config configs\paper-core.toml --once   # one live paper cycle, no keys
.venv\Scripts\python.exe scripts\run_bot.py --config configs\paper-core.toml          # hourly loop
```

Rehearsing the signed order path without a competition key — a local server implementing the documented API,
with the real client, exchange adapter and engine running against it:

```powershell
.venv\Scripts\python.exe scripts\mock_roostoo.py --live-prices                       # terminal 1
.venv\Scripts\python.exe scripts\run_bot.py --config configs\mock-core.toml --once   # terminal 2
```

Runtime evidence: `logs/<bot>.jsonl` is the append-only journal (every cycle, order and error, stamped with the
commit that produced it); `logs/<bot>.log` is the human-readable log. Fault stop, for a genuine malfunction only — the
rules prohibit stopping a bot by hand, so the commit must say what broke: set `mode = "hold"` (or
`"liquidate"`) in the bot's config and commit — it is re-read every cycle.

## Deploy

The competition bot runs on the organizers' EC2 host under systemd. [docs/runbook.md](docs/runbook.md) is the
operator's page: deploy, watch, what each alert means, how to change anything within the rules, day one and the
last day. The pieces:

```
deploy/setup_ec2.sh        one-shot host setup (Ubuntu 24.04; Amazon Linux 2023 untested): clone, venv, tests, bots
deploy/qtrading@.service   systemd template, one instance per config: Restart=always, never fights a live lock
Dockerfile                 the same bot as a container, for anyone who wants to run it elsewhere
requirements.txt           runtime dependencies (pyproject.toml is the source of truth)
scripts/supervise.py       the laptop stand-in for systemd, used for paper trading
```

## Data conventions

Every bar is indexed by its **close time** — the moment its close price became known — and the hourly panel
places a bar in the first grid hour at or after that moment. Consumers may use anything with index ≤ *now*;
look-ahead is impossible by construction. Hours with no closing bar (stocks outside US trading hours) carry the
last close forward and are flagged in a `stale` mask so signals can treat them correctly.

## Principles

- **Autonomous.** The bot alone calls the API. There is no manual-trading path, by design.
- **Never trade blind.** On any uncertainty (lost response, stale data, unexplained equity move) the bot holds and
  alerts; it never guesses.
- **Backtest = live.** Strategy code and order planning are shared, so the simulator can replay live decisions exactly.
- **Every request logged.** Signed requests and responses, and every cycle's decisions, are journaled with the running commit hash.
