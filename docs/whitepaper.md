# A Volatility-Managed Momentum Rotation Strategy for the Roostoo Mock Exchange

**HK vs Australia vs India Quant Trading Hackathon 2026** · Susquehanna × Roostoo
Repository: `qtrading` · Strategy locked 2026-09-16 · Live 2026-09-30 → 2026-10-13

---

## 1. Summary

We trade a long-only momentum rotation over the most liquid assets on Roostoo, sized so that the portfolio's
estimated volatility stays near 2% per day. The signal is deliberately ordinary — three-, seven- and fourteen-day
returns divided by each asset's own volatility — and the work went into the two things that actually decide a
14-day contest: **controlling turnover** and **controlling drawdown**.

Against buying and holding Bitcoin over the same two years:

| | Median fortnight | Bad fortnight (p10) | Worst fortnight | Max drawdown | Total return |
|---|---|---|---|---|---|
| **Core strategy** | +0.88% | **−6.4%** | **−16.1%** | **−32%** | **+108%** |
| BTC buy-and-hold | +0.80% | −9.1% | −29.8% | −50% | +32% |

On four months of data held out and looked at exactly once, the pattern repeated: worst fortnight −8.3% against
BTC's −20.7%, max drawdown −14.6% against −29.4%, total +36.8% against +13.8%.

We think the interesting parts of this submission are not the returns. They are: the reasoning about what the
scoring function rewards (§2), the list of ideas we tested and **rejected** (§7), and the fact that every live
decision can be mechanically re-derived from the journal (§9).

## 2. What the scoring function actually rewards

The competition ranks in stages, and each stage wants something different. Reading them in order changed our
design more than any backtest did.

**Screen 2 is a threshold, not a race.** Only a top-20 return in the region is needed to advance. Maximising
expected return is therefore the wrong objective; maximising the *probability of clearing a bar* is the right
one, and those differ sharply in the tails.

**Screen 3 rewards the shape of the return, not its size.** The composite is 0.4 × Sortino + 0.3 × Sharpe +
0.3 × Calmar. Sortino penalises only downside deviation, and Calmar is return divided by maximum drawdown. Both
are maximised by a strategy whose losses are small and whose gains are allowed to be large — a **positively
skewed** return distribution. Momentum produces exactly that shape (Fung & Hsieh 2001 describe trend following as
a lookback straddle: many small losses, few large gains). Mean reversion produces the opposite shape and is
therefore structurally unsuited to this scoring, independent of whether it makes money.

**Calmar makes drawdown the most valuable number on the board.** Halving the worst drawdown doubles that term.
No other single quantity in the score responds so directly to a design choice.

The two screens pull against each other — return versus risk — and the resolution is *conditional exposure*:
be invested when trends exist and hold cash when they do not. Cash has zero volatility and, under a long-only
spot mandate, is the only defensive instrument available.

## 3. Constraints and universe

Roostoo lists 88 pairs: about 64 cryptocurrencies, 21 tokenised US equities and PAXG (gold). Spot only, no
leverage and no shorting — every asset is either held or in cash. Commission is 0.1% on market orders and 0.05%
on limit orders, and there is no historical price endpoint, so signals are computed from Binance's public hourly
candles while Roostoo is used for execution and portfolio state.

We trade the **35 crypto pairs above $5M daily volume, plus PAXG**. Tokenised equities are excluded from v1 for
two reasons: they only price during US market hours, so at a 00:00 UTC decision every one of them is stale; and
their weekend pricing behaviour on Roostoo is unverified. They remain a candidate for a second bot.

**Fees are the binding constraint.** A market-order round trip costs 0.2%. Rotating the whole book once a day
costs roughly 2.8% over the competition — more than the edge we can expect to find. Every design decision below
that looks like caution is really a fee decision.

## 4. The strategy

Hourly, for each asset in the universe:

1. **Signal.** Compute returns over 3, 7 and 14 days, each ignoring the most recent 12 hours, and divide each by
   the asset's realised volatility over the matching horizon. Average the three. This asks "how many standard
   deviations has this moved?", not "how much has this moved" — without it, the highest-volatility memecoin wins
   the ranking every day. Volatility is measured on live bars only, so a carried-forward price is never mistaken
   for a zero return.
2. **Selection, once per day at 00:00 UTC.** Rank by score and hold the top 6. An existing holding is kept while
   it remains in the top 12. This hysteresis is what makes the strategy affordable.
3. **Weighting.** Inverse volatility, so each position contributes similar risk rather than similar dollars.
4. **Exposure.** Scale the whole book so estimated portfolio volatility is 2% per day under a constant-correlation
   model; the remainder stays in cash. Typical realised exposure is 40–70%.
5. **Execution.** Trade a holding only when it has drifted more than 5 percentage points from its target. Market
   orders, sells before buys so a rotation fits in available cash.

There is no regime switch, no machine learning, no discretionary override. The entire strategy is about 150 lines
of pure functions with no I/O, which is what allows the backtester and the live engine to run identical code.

### Why each component exists

| Component | Evidence |
|---|---|
| Multi-horizon, vol-adjusted signal | Momentum is documented in crypto at 1–4 week horizons (Liu & Tsyvinski 2021; Liu, Tsyvinski & Wu 2022). Vol-scaling roughly doubles momentum's Sharpe and removes most of its crash risk (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016). Averaging three horizons is a cheap ensemble against picking the wrong one. |
| Skip the most recent 12 hours | Short-horizon returns exhibit reversal, not continuation (Jegadeesh 1990). |
| Daily selection + rank hysteresis | Hourly re-selection churned ~1.4× of capital per day and paid **85% of starting capital in fees** over the sample. Moving to daily selection took the same signal from +87% to +170% net; dropping the noisiest (1-day) horizon took it to +188% on a third of the trades. |
| Inverse-volatility weights | Equalises risk contribution; prevents one volatile asset dominating the portfolio. |
| 2%/day volatility target | The single most effective drawdown control we found (see §5). |
| 5-point drift band | Suppresses rebalancing trades that cost more in fees than they improve tracking. |

## 5. The central empirical finding

We expected a regime filter — "go to cash when Bitcoin is below trend" — to be the main drawdown control. **It
was not.** Every version we tested (fast, slow, banded, per-asset) gave up 70–80% of total return in exchange for
roughly 5 points of improvement in the worst fortnight, and their in-market ratios went sharply negative, the
signature of whipsaw: selling after falls and buying back after rises.

What worked instead was continuous de-risking. Scaling exposure to a volatility target produced a result we did
not anticipate: **a lower target produced both higher returns and smaller losses.**

| Daily volatility target | Median fortnight | Worst fortnight | Max drawdown | Total |
|---|---|---|---|---|
| 1.5% | +0.65% | −12.1% | −26% | +82% |
| **2.0% (chosen)** | **+0.88%** | **−16.1%** | **−32%** | **+108%** |
| 3.0% | +0.44% | −21.6% | −41% | +86% |
| 4.0% | +0.20% | −24.3% | −46% | +64% |
| none | +0.17% | −24.5% | −52% | +90% |

In a long-only book, volatility targeting can only ever *reduce* exposure. For reducing exposure to raise returns,
the periods it removes must be net losers — and in crypto they are, because volatility rises inside selloffs. This
is Moreira & Muir's (2017) volatility-managed portfolio result appearing in our data, and it explains why a
continuous control beat every binary switch we tried: it never has to be right about a regime.

We chose 2.0% rather than the best-scoring cell because 1.5% and 2.0% sit on a plateau while 2.5% and above fall
away. Selecting the peak of a noisy surface is how backtests are overfitted.

## 6. Results

### In sample: 2024-09-19 → 2026-05-14, ~43 independent fortnights

| | Median | p10 | p90 | Worst | Beats BTC | Median MDD | Sharpe | Sortino | Calmar | Total | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Core** | +0.88% | −6.4% | +11.5% | −16.1% | **56%** | 4.6% | **0.89** | **1.47** | **0.18** | **+108%** | **−32%** |
| BTC hold | +0.80% | −9.1% | +10.4% | −29.8% | — | 6.3% | 0.72 | 1.17 | 0.14 | +32% | −50% |

Fees run about 0.3% per fortnight. The strategy beats BTC on every column, which is unusual enough that we treated
it as a warning rather than a result and went looking for the ways it could be an artefact (§8).

### Out of sample: 2026-05-15 → 2026-09-14, looked at once

Before unsealing, we committed to a pass rule: a smaller worst fortnight and smaller max drawdown than BTC, and
beating BTC in at least 45% of windows.

| | Median | p10 | Worst | Beats BTC | Max DD | Total |
|---|---|---|---|---|---|---|
| **Core** | +0.41% | −3.8% | **−8.3%** | 51% | **−14.6%** | **+36.8%** |
| BTC hold | +0.03% | −12.8% | −20.7% | — | −29.4% | +13.8% |

It passed. The claim that survived out of sample is specific: **the strategy roughly halves Bitcoin's tails and
multiplies its total return.** That is the claim we would defend.

The same window also produced a genuine surprise. A variant with equal weights and *no* volatility target — the
same signal at full exposure — returned +65% with a Sharpe of 1.56 and beat BTC in 62% of fortnights. Those four
months were volatile and rising, and volatility targeting cuts exposure exactly when volatility rises, which in a
volatile rally means missing upside. The vol target's advantage is therefore **regime-dependent**, not universal.
This is the evidence behind running a second, risk-on bot alongside the core: the two win in different worlds.

## 7. What we rejected

We consider this the most informative section. Every item below was pre-registered as a hypothesis, implemented,
tested through the same harness, and discarded.

| Idea | Why it was rejected |
|---|---|
| **Buying losers / mean reversion** | The user's own hypothesis, tested first. −80% over the sample with a −92% drawdown. It won in sharp V-shaped rebounds (84 windows, BTC median +6.9%) and lost in 186 others. Its negative skew is also the worst possible fit for a Sortino-weighted score. |
| **Regime gates** (market and per-asset) | Cost 70–80% of return for ~5 points of tail improvement. Whipsaw. |
| **Drawdown brake** | The first version had no reset and locked the book in cash permanently once triggered. With a cooldown it re-entered into continuing drawdowns: more trades, less return, 1.3 points of tail improvement. |
| **Residual momentum** (BTC-beta-neutral) | Alone, lifted Sharpe by ~0.15 with return and tails unchanged. |
| **Volume confirmation** | Alone, a similar small lift. |
| **Both together** | *Worse than either alone and worse than the plain core* (+73% vs +108%). Two real effects do not cancel; two noise-level effects do exactly this. Both excluded. |
| **Funding-rate crowding filter** | Effect flipped sign between thresholds of 0.02% and 0.03% per 8 hours. Noise, plus a live dependency on another API for no demonstrated gain. |
| **Overlapping selection tranches** | Averaged the single-hour results and added 2–4 points of fees. |
| **Tokenised equities** | Deferred: unverified weekend pricing, and selecting during US hours degraded the crypto book. |
| **LLM-driven trading** | Cannot be backtested honestly — the model has already seen the history it would be tested on. Nondeterministic, and it costs money per decision. |
| **Reinforcement learning** | Sample-hungry and regime-overfitting; 14 days cannot distinguish skill from luck in its output. |
| **Arbitrage / HFT / market making** | Explicitly banned by the rules. We also avoid anything resembling it, such as trading Roostoo's feed against a faster external one, or exploiting stale weekend prices. |

## 8. Known limitations

We would rather state these than have them found.

- **The sample is small.** Two years of hourly data contains roughly 43 independent fortnights. Medians are
  trustworthy; extreme quantiles are indicative at best.
- **Part of the in-sample edge is timing luck.** We swept the selection hour across six values. Tails and total
  return were robust everywhere (worst fortnight −15% to −17%, max drawdown −32% to −35%, total +61% to +111%),
  but the "better median and Sharpe than BTC" claim holds only at 00:00 and 12:00 UTC. We kept 00:00 because it is
  the daily-candle convention chosen before any comparison was run — not because it scored best — and we discount
  the headline numbers accordingly.
- **Small differences are noise.** A single tie-break in the simulator's fill order once compounded into an
  11-point difference in total return over 20 months. We fixed the non-determinism, and we treat any gap under
  about 10 points of total return as meaningless.
- **The strategy will lose in choppy and V-shaped markets.** It is late to every turn by construction. Over one
  14-day window the market path dominates; what momentum reliably does is reshape the distribution, not pick the
  outcome.
- **We will not know if we were skilled or lucky.** Fourteen days is one draw. We can say what distribution we
  expected, and where the result fell in it.

## 9. Engineering

The strategy is only useful if it executes autonomously for 14 days without intervention.

**Backtest equals live, mechanically.** The strategy is two pure functions, and order planning lives in one
shared function used by both the simulator and the live engine. The engine journals the reconciled book and the
strategy memory each decision was made from, and `scripts/replay.py` re-derives every journalled decision and
diffs it. Live cycles reproduce exactly. A judge can run this against our committed journal.

**The bot never trades blind.** Any exception anywhere in a cycle means no orders. It refuses to trade on stale
data, holds for a cycle on an unexplained equity move over 5%, stops a cycle on an uncertain order response
rather than risking a duplicate fill (`place_order` never retries), and caps per-order size as a runaway guard.

**Rule compliance is built in, not promised.** Every request and decision is journalled as JSON stamped with the
git commit that produced it, so the trade log maps to the code that made it. There is no manual-trading path: the
emergency stop is a `mode` field in a committed config file that the loop re-reads every cycle. An activity
tracker watches the 8-active-day requirement and forces a genuine rebalance if the pace falls behind, because
backtests showed calm fortnights producing as few as 6 trading days.

**Testing.** 196 tests, all offline and deterministic. A look-ahead checker perturbs prices after time *t* and
asserts that signals up to *t* are unchanged; it runs on every strategy before its results are reported. Because
no test API key was available before the competition, we wrote a local server implementing the documented Roostoo
API over real HTTP — signature validation over the exact bytes sent, the timestamp window, the documented error
envelopes, and injectable faults — and rehearsed the full engine against it.

## 10. Reproducing our results

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest                  # 196 tests
.venv\Scripts\python.exe scripts\fetch_history.py   # ~2 years of hourly data
.venv\Scripts\python.exe scripts\run_backtest.py    # in-sample table
.venv\Scripts\python.exe scripts\run_backtest.py --oos --start 2026-04-01 --report-from 2026-05-15
.venv\Scripts\python.exe scripts\replay.py --config configs\core.toml   # live decisions vs the strategy
```

The universe is built from a committed snapshot of Roostoo's `exchangeInfo`, so results do not change if the
exchange relists pairs. The full decision log, including every rejected hypothesis and the run that produced it,
is in `docs/superpowers/specs/2026-09-14-roostoo-bot-design.md`.

## References

Barroso, P. & Santa-Clara, P. (2015). Momentum has its moments. *Journal of Financial Economics*.
Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics*.
Fung, W. & Hsieh, D. (2001). The risk in hedge fund strategies: theory and evidence from trend followers. *Review of Financial Studies*.
Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. *Journal of Finance*.
Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance*.
Liu, Y. & Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial Studies*.
Liu, Y., Tsyvinski, A. & Wu, X. (2022). Common risk factors in cryptocurrency. *Journal of Finance*.
Moreira, A. & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance*.
Moskowitz, T., Ooi, Y. H. & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics*.
