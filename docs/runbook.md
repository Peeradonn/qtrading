# Runbook: running the bot for the fourteen days

One page for the operator. The rules that shape it: the bot must trade autonomously; stopping it by hand,
overriding it, or trading through the API yourself is prohibited; every change must be a commit; the first trade
must execute by October 1, 8pm HKT; the system liquidates on October 13.

## Deploy (once, on the Sydney EC2 host)

```bash
sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git eqvt3
sudo nano /opt/qtrading/.env            # ROOSTOO_API_KEY, ROOSTOO_SECRET_KEY, ALERT_WEBHOOK_URL, HEARTBEAT_URL_EQVT3
sudo -u ubuntu /opt/qtrading/.venv/bin/python /opt/qtrading/scripts/run_bot.py --config /opt/qtrading/configs/paper-eqvt3.toml --once
sudo systemctl start qtrading@eqvt3 && journalctl -u qtrading@eqvt3 -f
```

The setup script runs the test suite on the host's Python before enabling anything. The keyless cycle proves the
host can reach Binance and Roostoo and that the clock is right. The same script sets up a personal VPS for the
paper bots: `sudo bash deploy/setup_ec2.sh <url> paper-core paper-eqvt3 paper-ls25`, one systemd instance each.
Give every bot its own healthchecks.io check, `HEARTBEAT_URL_<NAME>` in `.env`: with one shared check, the live
bots keep it green while a dead one goes unnoticed. The first real cycle buys the book from cash, which satisfies
the first-trade deadline on its own.

## Watch

- `journalctl -u qtrading@eqvt3 -f` is the live log; `logs/eqvt3.jsonl` is the journal, one JSON line per cycle, order
  and error, each stamped with the commit that produced it.
- Discord gets an alert on every error and a digest every four hours. healthchecks.io gets a ping after every
  cycle and notifies only on a change of state, so silence there means the bot is cycling.
- Once a day: the last `cycle_end` line has today's date, `equity` is sane, `active_days` is on pace (8 of 14),
  and `journalctl` shows no restarts you did not expect.
- `scripts/replay.py --config configs/eqvt3.toml` re-derives every journalled decision from its inputs and
  diffs it. Run it whenever a decision looks odd. It has reproduced live cycles exactly so far.

## When something fires

| Alert or symptom | What it means | What to do |
|---|---|---|
| `error` line, then the next cycle is clean | A transient API or network fault; the cycle placed no orders by design | Nothing. Note it. |
| Repeated `error` lines every hour | Something persistent: a bad key, a Roostoo outage, the host cannot reach Binance | Read the message. Keys: fix `.env`, `systemctl restart qtrading@eqvt3`. Outage: wait; the bot holds. |
| "stale data" or "freshness" errors | Binance bars are not arriving | Check the host's network. The bot refuses to trade blind and will resume when bars arrive. |
| "equity moved more than 5%" hold | The wallet or the price feed does not match the last cycle | Compare `/v3/balance` with the journal's last `cycle_end`. If the exchange is right, the next cycle proceeds on its own. |
| `OrderUncertain` | An order was sent and the response was lost | The bot stopped that cycle rather than risk a duplicate fill. Check `/v3/query_order`; the next cycle reconciles from the wallet. |
| Rate-limit failures | More than 30 calls in a minute | Should not happen at two-second pacing. If it does, raise `min_interval_s` in a commit and restart. |
| Service restarted by systemd | The process died | Read `journalctl -u qtrading@eqvt3 --since -1h` for the traceback. If it repeats, treat as a fault, below. |
| Healthchecks "DOWN" | No cycle completed within the grace period | Check the service is running and the host is up. |

## Changing anything

- Code: commit, `git -C /opt/qtrading pull --ff-only`, `sudo systemctl restart qtrading@eqvt3`. The journal stamps the
  new commit from the next cycle.
- Config, including `mode`: commit and pull. `mode` is re-read every cycle; no restart needed.
- `mode = "hold"` is a fault stop, not a pause. Use it only for a genuine malfunction, say what broke in the commit
  message, and set it back to `"trade"` with the fix. Stopping the bot because you dislike the market is the
  intervention the rules prohibit.
- Do not change the strategy parameters during the competition. The whitepaper declares them; the journal proves
  they were used.

## The short leg (only if adopted)

`configs/paper-ls25.toml` is the entry with a short leg on the ranking's losers. It is a paper bot until the test
account proves the mechanics the backtest assumes. The check, to run once when the test keys arrive: sell a small
quantity of an alt the account does not hold, then read `/v3/balance`. Adopt only if the order fills, the balance
goes negative, portfolio value moves one-for-one with the price, nothing is charged for holding it for a day, a
BUY closes it, and the 1x limit rejects new exposure instead of liquidating. If any of those fails, the entry
stays long-only and nothing else changes. If all hold, the competition config is `eqvt3.toml` plus the
`allow_short` line and the five short-leg lines from the paper config, committed before the 30th.

## Day one (September 30)

1. Official keys into `.env`; `sudo systemctl restart qtrading@eqvt3`.
2. Watch the first cycle in the log: reconcile shows the starting cash, targets are set, orders fill.
3. Confirm the fills on the Roostoo app leaderboard, and count the bots in the region while you are there.
4. Confirm the healthchecks ping and the Discord digest arrived.

## Last day (October 13)

The system liquidates. After it has, `sudo systemctl stop qtrading@eqvt3` to save resources, and tag the repository at
the commit that traded.
