# A Volatility-Managed Momentum Rotation Strategy for the Roostoo Mock Exchange

**HK vs Australia vs India Quant Trading Hackathon 2026** · Susquehanna × Roostoo
Repository: `qtrading` · Strategy locked 2026-09-16 · Live 2026-09-30 → 2026-10-13

---

## 1. Summary

We trade a long-only momentum rotation over the most liquid assets on Roostoo, sized so that the portfolio's
estimated volatility stays near 3% per day. The signal is deliberately ordinary — three-, seven- and fourteen-day
returns divided by each asset's own volatility — and the work went into the two things that actually decide a
14-day contest: **controlling turnover** and **controlling drawdown**.

Against buying and holding Bitcoin over the same two years:

| | Median fortnight | Bad fortnight (p10) | Worst fortnight | Max drawdown | Total return |
|---|---|---|---|---|---|
| **Entry: equal weight, 3% target** | **+1.38%** | −10.3% | −23.3% | −47% | **+176%** |
| Core: inverse-vol, 2% target (the fallback) | +0.96% | **−6.7%** | **−15.8%** | **−34%** | +103% |
| BTC buy-and-hold | +0.80% | −9.1% | −29.8% | −50% | +28% |

The core was locked first and passed a sealed test on four months held out and looked at exactly once: worst
fortnight −8.3% against BTC's −20.7%, max drawdown −14.6% against −29.4%, total +36.8% against +13.8%. The entry
was chosen afterwards, on the frontier of §5.2, and on the same four months it made +35.5% with a worst fortnight
of −8.2% (§6). It buys participation in rallies, which the competition's return gate rewards, at the price of
deeper tails, which §8 states plainly.

We think the interesting parts of this submission are not the returns. They are: the reasoning about what the
scoring function rewards (§2), the list of ideas we tested and **rejected** (§7), and the fact that every live
decision can be mechanically re-derived from the journal (§9).

## 2. What the scoring function actually rewards

The competition ranks in stages, and each stage wants something different. Reading them in order changed our
design more than any backtest did.

**Screen 2 is a threshold, not a race.** Only a top-20 return in the region is needed to advance. Maximising
expected return is therefore the wrong objective; maximising the *probability of clearing a bar* is the right
one, and those differ sharply in the tails. How high the bar sits depends on the number of teams in the region
and on the market path over those fourteen days; §8 quantifies where the core lands against naive competitors in
rising and falling markets.

**Screen 3 rewards the shape of the return, not its size.** The composite is 0.4 × Sortino + 0.3 × Sharpe +
0.3 × Calmar. Sortino penalises only downside deviation, and Calmar is return divided by maximum drawdown. Both
are maximised by a strategy whose losses are small and whose gains are allowed to be large — a **positively
skewed** return distribution. Momentum produces exactly that shape (Fung & Hsieh 2001 describe trend following as
a lookback straddle: many small losses, few large gains). Mean reversion produces the opposite shape and is
therefore structurally unsuited to this scoring, independent of whether it makes money.

**Calmar makes drawdown the most valuable number on the board.** Halving the worst drawdown doubles that term.
No other single quantity in the score responds so directly to a design choice.

The two screens pull against each other — return versus risk — and the resolution is *conditional exposure*:
be invested when trends exist and hold cash when they do not. Cash has zero volatility and, in a long-only book,
is the only defensive instrument. A short hedge is the other candidate; §7 explains why we do not use it.

## 3. Constraints and universe

Roostoo lists 88 pairs: about 64 cryptocurrencies, 21 tokenised US equities and PAXG (gold). Spot only, no
leverage; the rules allow a 1x short, which we tested and do not use (§7), so in the shipped strategy every asset
is either held or in cash. Commission is 0.1% on market orders and 0.05%
on limit orders, and there is no historical price endpoint, so signals are computed from Binance's public hourly
candles while Roostoo is used for execution and portfolio state.

We trade the **35 crypto pairs above $5M daily volume, plus PAXG**. Tokenised equities are excluded from v1 for
two reasons: they only price during US market hours, so at a 00:00 UTC decision every one of them is stale; and
their weekend pricing behaviour on Roostoo is unverified. They remain a candidate for a second bot.

**Gold is in the universe as a candidate, not as a hedge.** The ranking treats PAXG like any other asset, and
gold's 2025 trend put it at the top often enough to average 18% of the book in-sample, as much as 55% in
February 2025, and 22–29% in the January 2026 crash windows, where it saved roughly three points against a book
without it. When gold stopped trending after May 2026 the ranking held 4%. Removing PAXG from the universe costs
a third of the total return and three points of worst fortnight. We also tested holding gold *by rule*, as a
permanent sleeve for the cash the volatility target leaves idle; it was rejected, for reasons that mirror the
regime-gate result (§7).

**Fees are the binding constraint.** A market-order round trip costs 0.2%. Rotating the whole book once a day
costs roughly 2.8% over the competition — more than the edge we can expect to find. Every design decision below
that looks like caution is really a fee decision.

## 4. The strategy

Hourly, for each asset in the universe:

1. **Signal.** Compute returns over 3, 7 and 14 days, each ignoring the most recent 12 hours, and divide each by
   the asset's forecast volatility (an exponentially weighted estimate, §5.1). Average the three. This asks "how many standard
   deviations has this moved?", not "how much has this moved" — without it, the highest-volatility memecoin wins
   the ranking every day. Volatility is measured on live bars only, so a carried-forward price is never mistaken
   for a zero return.
2. **Selection, once per day at 00:00 UTC.** Rank by score and hold the top 6. An existing holding is kept while
   it remains in the top 12. This hysteresis is what makes the strategy affordable.
3. **Weighting.** Equal, one sixth of the book each. The core weighted by inverse volatility; §5.2 shows why the
   entry does not.
4. **Exposure.** Scale the whole book so estimated portfolio volatility is 3% per day under a constant-correlation
   model; the remainder stays in cash. Average invested weight is about 70%. The fallback core targets 2%.
5. **Execution.** Trade a holding only when it has drifted more than 5 percentage points from its target. Market
   orders, sells before buys so a rotation fits in available cash.

There is no regime switch, no learned return model and no discretionary override. Volatility *is* modelled (§5.1) — because volatility is forecastable and returns, at this horizon, are not. The entire strategy is about 150 lines
of pure functions with no I/O, which is what allows the backtester and the live engine to run identical code.

### Why each component exists

| Component | Evidence |
|---|---|
| Multi-horizon, vol-adjusted signal | Momentum is documented in crypto at 1–4 week horizons (Liu & Tsyvinski 2021; Liu, Tsyvinski & Wu 2022). Vol-scaling roughly doubles momentum's Sharpe and removes most of its crash risk (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016). Averaging three horizons is a cheap ensemble against picking the wrong one. |
| Skip the most recent 12 hours | Short-horizon returns exhibit reversal, not continuation (Jegadeesh 1990). |
| Daily selection + rank hysteresis | Hourly re-selection churned ~1.4× of capital per day and paid **85% of starting capital in fees** over the sample. Moving to daily selection took the same signal from +87% to +170% net; dropping the noisiest (1-day) horizon took it to +188% on a third of the trades. |
| Equal weights | Inverse-volatility weights tilt the book toward Bitcoin and gold, which lag an alt rally, and cost ratios at every volatility target (§5.2). The fallback core keeps them for their shallower tails. |
| 3%/day volatility target | Volatility targeting is the single most effective drawdown control we found (§5); 3% is the point on the exposure frontier that buys rally participation for the tail we are willing to pay (§5.2). |
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
away. Selecting the peak of a noisy surface is how backtests are overfitted. That table is for inverse-volatility
weights, the core's; with equal weights the picture changes, and §5.2 is where the entry's 3% comes from.

### 5.1 Forecasting volatility, not returns

Everything above rests on a volatility estimate: it is the denominator of the signal, it sets the weights, and it
sizes the book. We originally used a trailing 7-day realised standard deviation — a backward measure used as a
forward forecast — so we ran a pre-registered experiment to see whether it could be improved.

The design deliberately avoided returns. Candidate models were scored on **forecast error against realised
volatility** (QLIKE and MSE on log volatility, two horizons, walk-forward), with no PnL involved and no parameter
chosen against performance. The accept rule was fixed in advance: beat the incumbent on both horizons and both
losses, on a plateau of the parameter, and only then confirm the backtest does not degrade.

| Model | 24h QLIKE | 24h MSE | 168h QLIKE | 168h MSE |
|---|---|---|---|---|
| Trailing 7-day (incumbent) | 0.397 | 0.179 | 0.322 | 0.116 |
| EWMA λ=0.98 | **0.360** | 0.166 | 0.325 ✗ | 0.113 |
| **EWMA λ=0.99 (adopted)** | 0.364 | 0.173 | **0.291** | **0.105** |
| EWMA λ=0.995 | 0.381 | 0.187 ✗ | **0.274** | **0.103** |
| HAR regression, walk-forward | 0.397 ✗ | **0.150** | 0.335 ✗ | **0.100** |

Two findings are worth stating plainly.

**A one-parameter rule beat the fitted model on the criterion that matters.** The HAR regression — the machine
learning entrant, refitted walk-forward on daily, weekly and monthly volatility components — won both MSE tests
and lost both QLIKE tests. That is not noise: QLIKE punishes *under*-forecasting variance far more than
over-forecasting, and a fitted model's coefficients shrink toward the mean, so it systematically under-predicts
spikes. For a risk control, under-forecasting volatility is the failure that cannot be tolerated — it produces
maximum exposure exactly when markets turn violent. The model that looked better under the generic metric was
worse for the purpose.

**The optimum moves with the horizon** (λ=0.98 for a day, λ=0.995 for a week), so we took the value that wins
everywhere rather than the best single cell. For the core strategy the backtest was a wash within our noise band
(+104% against +108%), which satisfies the rule; the reason to adopt is that the forecast is measurably more
accurate on evidence independent of returns, so the 2%/day target means what it says during volatility spikes the
sample does not contain.

The risk-on variant gained far more (+180% → +265%, Sharpe 0.67 → 1.06, identical max drawdown), because with
equal weights and no volatility target the estimate enters only the signal's denominator. A flat 7-day window
takes days to notice that an asset has become dangerous; an exponentially weighted one notices within hours and
drops it from the selection. That is what makes risk-adjusted momentum risk-adjusted in real time.

### 5.2 The exposure frontier

Screen 2 is a rank, and a rank against whom matters. We ranked every fortnight of the core against 34 competitors
who simply hold one liquid coin. When Bitcoin falls, the core beats at least 60% of that field 88% of the time. When
Bitcoin gains more than 10%, it captures 60% of the move and reaches the top 40% of the field about one time in
five; above +20%, never. The full-exposure twin reaches it four times in five, and pays with a −33% worst
fortnight. The cause is sizing, not information: crypto rallies arrive with rising volatility, and a total-volatility
target cuts exposure into exactly the move the gate rewards. (We tested whether sentiment carries information
prices do not; §7.)

Two sizing changes were pre-registered to buy rally participation without paying in tails, and both failed. Sizing
on downside deviation alone is a wash with the core, because downside deviation rises in a crypto rally too. A floor
on exposure leaves the book 77–80% invested yet still outside the top 40% in most big rallies, while giving up 3–4
points of worst fortnight.

What the tables exposed instead is that the **weighting** is a second brake. Inverse-volatility weights tilt the
book toward Bitcoin and gold, which lag an alt rally. Equal weight under the same volatility target had never been
tested, and it is a smooth dial between the core and the twin:

| Equal weight, daily vol target | Top 40% when BTC rises | Top 40% when BTC falls | Worst fortnight | p10 | Sharpe | Sortino | Total |
|---|---|---|---|---|---|---|---|
| **Core (inverse-vol, 2%)** | 40% | 88% | −15.8% | −6.7% | 0.87 | 1.36 | +103% |
| 2.0% | 40% | 89% | −16.5% | −6.8% | 1.09 | 1.69 | +121% |
| 2.5% | 46% | 88% | −20.5% | −8.5% | 1.00 | 1.51 | +149% |
| 3.0% | 52% | 85% | −23.3% | −10.3% | 1.04 | 1.68 | +176% |
| 3.5% | 57% | 80% | −26.6% | −11.3% | 1.14 | 1.92 | +206% |
| 4.0% | 60% | 77% | −28.8% | −12.1% | 1.11 | 1.68 | +240% |
| Twin (equal weight, no target) | 67% | 65% | −33.2% | −14.4% | 1.06 | 1.68 | +263% |

Three things follow. Ratios sit above the core's at every setting, so inverse-volatility weighting was costing
ratios at every target. With equal weight the target is a pure return-for-tails dial, and the "lower target, higher
return" result of §5 turns out to be specific to inverse-volatility weights. And the trade-off is real: no setting
gains ten points of rally rank without giving up at least four points of worst fortnight. The family is consistent
on the post-May period and at the 12:00 UTC selection hour, but the ratio gain at 3% does not survive K=8, so we
treat it as about 0.1 of Sharpe, uncertain.

We run the 3% point. We asked whether the choice should depend on the size of the field, and it does not: against
a field of N compliant teams with twenty passing, the 3% book passes Screen 2 at least as often as the core at every
size (N = 30: 88% against 82%; N = 50: 67% against 60%; N = 100: 29% against 30%), so a rule that switched books on
the observed count was considered and dropped. What the point costs is tail, stated in §8, and the core remains
deployable as the fallback.

## 6. Results

### In sample: 2024-09-19 → 2026-05-14, ~43 independent fortnights

| | Median | p10 | p90 | Worst | Beats BTC | Median MDD | Sharpe | Sortino | Calmar | Total | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Entry** (equal weight, 3%) | **+1.38%** | −10.3% | **+18.0%** | −23.3% | 56% | 6.8% | **1.04** | **1.68** | **0.20** | **+176%** | −47% |
| Core (inverse-vol, 2%) | +0.96% | **−6.7%** | +11.7% | **−15.8%** | **57%** | **4.6%** | 0.87 | 1.36 | 0.18 | +103% | **−34%** |
| BTC hold | +0.80% | −9.1% | +10.4% | −29.8% | — | 6.3% | 0.72 | 1.17 | 0.14 | +28% | −50% |

Fees run about 0.3% per fortnight for either book. The core beats BTC on every column, which is unusual enough
that we treated it as a warning rather than a result and went looking for the ways it could be an artefact (§8).
The entry gives up the two tail columns and max drawdown for the rest; that is the choice §5.2 describes.

### Out of sample: 2026-05-15 → 2026-09-14, looked at once

Before unsealing, we committed to a pass rule: a smaller worst fortnight and smaller max drawdown than BTC, and
beating BTC in at least 45% of windows.

| | Median | p10 | Worst | Beats BTC | Max DD | Total |
|---|---|---|---|---|---|---|
| **Core** | +0.41% | −3.8% | **−8.3%** | 51% | **−14.6%** | **+36.8%** |
| BTC hold | +0.03% | −12.8% | −20.7% | — | −29.4% | +13.8% |

It passed. The claim that survived out of sample is specific: **the core roughly halves Bitcoin's tails and
multiplies its total return.** That is the claim we would defend.

The entry was chosen after this period was unsealed, so for it these four months are a consistency check, not a
holdout. On the same windows, from one continuous run of both books:

| | Median | p10 | Worst | Beats BTC | Max DD | Total |
|---|---|---|---|---|---|---|
| Entry (equal weight, 3%) | +2.11% | −4.5% | −8.2% | 61% | −16.1% | +35.5% |
| Core (inverse-vol, 2%) | +0.92% | −3.1% | −7.9% | 56% | −12.9% | +23.3% |

The core's figures differ slightly from the sealed run above because that run began its warm-up on 2026-04-01
rather than running continuously from 2024.

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
| **Gold as a permanent sleeve** (idle cash held in PAXG, or PAXG as a fixed position inside the risk budget) | Pre-registered and rejected. Against the core it raised the median fortnight from +0.96% to +1.82% and every ratio (Sharpe 0.87 → 1.57), but made the worst fortnight worse (−15.8% → −19.3%, and −20.3% with gold's drift removed) and lost in the post-May-2026 period as gold fell 6% (p10 −3.1% → −6.2%). Two reasons. A cash sleeve is pro-cyclical: before a crash crypto is calm, the vol target leaves little idle cash, so there is little gold exactly when it is needed. And gold's correlation with crypto is near zero on average but not in a crash: in January 2026 it fell 8–10% alongside Bitcoin. Gold held *by rank* is there because gold is trending, whatever crypto is doing; the core with PAXG removed from the ranking is worse on every metric (worst −18.7%, total +71% against +103%, Sharpe 0.76). Conditional gold beats unconditional gold, which is the same lesson as volatility targeting beating gates. |
| **Downside-deviation targeting; an exposure floor** | Pre-registered to buy rally participation without paying in tails (§5.2). Downside targeting is a wash with the core on every column; a 70% floor leaves the book 77% invested and still outside the top 40% in most big rallies, at a cost of four points of worst fortnight. |
| **A BTC short against the long book** (the rules' "1x short") | Pre-registered and rejected. A short sized at 25–100% of the long notional was tested on both the vol-targeted core and the full-exposure twin, gross capped at 1x. In the harness the hedge is a dial that trades return for tails almost one-for-one: on the full-exposure leg it runs from the twin (worst fortnight −33%, total +263%) to −13% and +103% at a full hedge, with the median-window Sharpe flat at 0.83–0.87 until three-quarters hedged and collapsing to 0.4 beyond. No ratio met the rule. At three-quarters hedged the fortnight distribution is the core's (median +0.84% vs +0.96%, p10 −6.3% vs −6.7%, worst −15.2% vs −15.8%, Sharpe 0.83 vs 0.87); the larger multi-year total (+138% vs +103%) comes from a fatter right tail, and in rising fortnights the hedged book ranks no better against naive competitors than the core does. Volatility targeting delivers the same distribution without shorts, without unverified exchange mechanics, and without a gross-exposure guard (realised gross drifted to 1.2× between rebalances). Shorting the bottom of the ranking was worse still: −27% over the sample with a −40% worst fortnight in a daily spike, the short squeeze in every rebound. That daily spike had suggested a large ratio gain from the hedge; the harness, with hourly decisions, fees and the drift band, did not confirm it, which is why the harness is the arbiter. |
| **LLM-driven trading** | Cannot be backtested honestly — the model has already seen the history it would be tested on. Nondeterministic, and it costs money per decision. |
| **News and sentiment** | News moves prices, but the question is whether a sentiment measure carries information the price signal does not. The one sentiment series with a free multi-year daily history, the Crypto Fear & Greed index, has a rank correlation with BTC's forward return of +0.02 at one day and +0.07 at fourteen, indistinguishable from zero, and is 0.56 rank-correlated with the trailing 14-day return: it is price momentum with a survey attached (`scripts/sentiment_check.py`). Headline-level scoring by an LLM cannot be validated on history for the reason above, and its exploitable horizon is hours, where fees dominate. Post-news drift is what momentum trades by construction, and the EWMA volatility estimate already cuts exposure within hours of a shock. |
| **HAR volatility regression** | Won on mean squared error, lost on QLIKE at both horizons: it under-predicts volatility spikes, which is the one error a risk control cannot make (§5.1). |
| **Learned return models generally** | Our 32 assets carry an average pairwise correlation of 0.55, so they are worth about 1.8 independent series; at a weekly horizon that leaves roughly 180 effective independent observations. Measured on our own data, trailing returns predict next-day returns with an R² of 0.001, against 0.048 for volatility. There is not enough independent information to fit a return model, and we have already seen two six-parameter "improvements" cancel each other. |
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
- **For Screen 2 the core is a selloff specialist.** Ranked each fortnight against 34 competitors who simply hold
  one liquid coin, it beats at least 60% of them in 88% of fortnights when Bitcoin falls and in 40% when Bitcoin
  rises; when Bitcoin gains more than 5% it reaches the top fifth of that field 5% of the time. §5.2 gives the
  frontier this sits on. How high the real bar sits depends on how many teams enter a region, which we do not know.
- **The entry was chosen after the holdout was opened.** The core passed a sealed test; the equal-weight book was
  found and chosen afterwards, on the frontier of §5.2, and its post-May figures are a consistency check. Its
  ratio advantage over the core is about 0.1 of Sharpe and does not survive K=8; its rally participation does.
- **The entry's tails are deeper by design.** One fortnight in nine loses more than 10%, against one in
  twenty-five for the core, and its typical 14-day drawdown is 6.8% against 4.6%. Those losses did not cost rank
  against naive competitors in falling markets, but they are real, and the core stays deployable as the fallback.
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

**Testing.** 224 tests, all offline and deterministic. A look-ahead checker perturbs prices after time *t* and
asserts that signals up to *t* are unchanged; it runs on every strategy before its results are reported. Because
no test API key was available before the competition, we wrote a local server implementing the documented Roostoo
API over real HTTP — signature validation over the exact bytes sent, the timestamp window, the documented error
envelopes, and injectable faults — and rehearsed the full engine against it.

## 10. Reproducing our results

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest                  # 224 tests
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
