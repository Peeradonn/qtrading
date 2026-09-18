# A Volatility-Managed Momentum Rotation Strategy for the Roostoo Mock Exchange

**HK vs Australia vs India Quant Trading Hackathon 2026** · Susquehanna × Roostoo
Repository: `qtrading` · Strategy locked 2026-09-16 · Universe made a rule 2026-09-18 · Live 2026-10-01 → 2026-10-14

---

## 1. Summary

We trade a long-only momentum rotation over every crypto pair on Roostoo that clears a rolling liquidity floor,
sized so that the portfolio's estimated volatility stays near 3% per day. The signal is deliberately ordinary —
three-, seven- and fourteen-day returns divided by each asset's own volatility — and the work went into the two
things that actually decide a 14-day contest: **controlling turnover** and **controlling drawdown**.

Against buying and holding Bitcoin, in-sample (2024-09-19 → 2026-05-14):

| | Median fortnight | Bad fortnight (p10) | Worst fortnight | Max drawdown | Total return |
|---|---|---|---|---|---|
| **Entry: equal weight, 3% target** | **+1.24%** | −8.6% | −17.3% | −38% | **+146%** |
| Core: inverse-vol, 2% target (the fallback) | +0.74% | **−5.7%** | **−13.0%** | **−29%** | +92% |
| BTC buy-and-hold | +0.80% | −9.1% | −29.8% | −50% | +28% |

These are not the figures this paper first reported, and the difference is the most important thing we found.
Until 2026-09-18 the universe was a list of 35 pairs chosen on September 2026 volume and then backtested over the
two years before it, so names were in the pool because of what they later did. We measured that bias and it was
most of the edge: with the same 35 pairs admitted honestly, by a rule that sees only past volume, the entry's
Screen 3 composite falls from 1.05 to 0.75, level with holding Bitcoin at 0.73. The universe is now that rule
applied to every pair Roostoo lists. It carries no hindsight and runs identically live.

The rule has one number in it, a $5M floor that was never derived, so we tested its neighbours, and the results
move with it more than we would like. The table above is the $5M row, which is the best of five floors on both
tail columns. Across $3M, $5M and $8M the entry averages a composite of 0.85, a worst fortnight of −18.8%, a max
drawdown of −39.5% and a total of +120%, and that average is the figure we stand behind (§6, §8). What holds at
every floor we tried is the shape: tails well inside Bitcoin's, and a total return above it.

The core was locked first and passed a sealed test on four months held out and looked at exactly once. That test
ran on the hindsight list too, and the list was chosen at the end of those four months, so we no longer present it
as clean. Under the rule, the same four months are a consistency check and not a holdout, because they have now
been looked at more than once: the entry made +32% with a worst fortnight of −8.9% and the core +13% with −10.3%,
against Bitcoin's −5% and −20.7% (§6). Those are the $5M figures, and in that period $5M is the best of the five
floors by a wide margin: at $3M and $8M the entry made +11% and +7%. The period holds about eight independent
fortnights, and most of that gap is one August rally the higher floors missed. The entry buys participation in
rallies, which the competition's return gate rewards, at the price of deeper tails than the core's, which §8
states plainly.

We think the interesting parts of this submission are not the returns. They are: the reasoning about what the
scoring function rewards (§2), the list of ideas we tested and **rejected** (§7), the bias we found in our own
backtest and what correcting it cost (§8), and the fact that every live decision can be mechanically re-derived
from the journal (§9).

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

We trade **every crypto pair Roostoo lists that Binance has history for, 65 at the snapshot, admitted hour by
hour by a liquidity rule**: a pair is eligible while its trailing seven-day dollar volume is at least $5M a day.
PAXG (gold) is in the pool like any other pair; OMNI and TON have no Binance history and are left out. The rule
lives inside the signal (`liquidity_min_daily`), so a decision at time *t* sees volume only to *t*, and the
backtest and the live bot apply it with the same code. `scripts/build_universe_list.py --pool` reproduces the
pool from the committed exchangeInfo snapshot. Until 2026-09-18 the universe was a fixed list of 35 pairs chosen
on that month's volume; §8 explains why that was a mistake and what it was worth.

Tokenised equities are not in the book, and
the reason changed on the last day of research. We had assumed they price only during US hours, so that at a
00:00 UTC decision every one of them is stale; that was an artefact of our data, the underlying share's history.
Roostoo's tokens price around the clock: seven hours after the US close, every one showed a live bid and ask and
half changed price within a minute, within 0.2% of Bybit's tokenised-stock quotes. Tested properly, with 24/7
token history from Bybit for the seven names it lists, stocks in the ranking are ballast: they improve the worst
fortnight and max drawdown and lower rally participation, ratios and total return (§7). They would suit the
fallback core; they do not suit the entry.

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
2. **Selection, once per day at 00:00 UTC.** Rank the pairs the liquidity rule admits (§3) by score and hold the
   top 6. An existing holding is kept while it remains in the top 12. This hysteresis is what makes the strategy
   affordable.
3. **Weighting.** Equal, one sixth of the book each. The core weighted by inverse volatility; §5.2 shows why the
   entry does not.
4. **Exposure.** Scale the whole book so estimated portfolio volatility is 3% per day under a constant-correlation
   model; the remainder stays in cash. Average invested weight is about 57%. The fallback core targets 2%.
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
| **Entry** (equal weight, 3%) | **+1.24%** | −8.6% | **+16.7%** | −17.3% | **54%** | 6.3% | **0.98** | **1.47** | 0.18 | **+146%** | −38% |
| Core (inverse-vol, 2%) | +0.74% | **−5.7%** | +10.8% | **−13.0%** | 52% | **4.5%** | 0.80 | 1.29 | **0.19** | +92% | **−29%** |
| BTC hold | +0.80% | −9.1% | +10.4% | −29.8% | — | 6.3% | 0.72 | 1.17 | 0.14 | +28% | −50% |

Both books trade the pool of 65 pairs under the rolling liquidity rule (§3). Fees run about 0.25% per fortnight
for either book, and both average 57% invested. The entry gives up the two tail columns and max drawdown for the
rest; that is the choice §5.2 describes.

The first version of this table, on the fixed list of 35, had the core beating BTC on every column. That is
unusual enough that we treated it as a warning rather than a result and went looking for the ways it could be an
artefact. The universe was the way. The same harness, the same panel and the same field of competitors, with only
the universe changed:

| Universe | Entry composite | Core composite | Entry worst fortnight | Entry max drawdown |
|---|---|---|---|---|
| Fixed 35, chosen on September 2026 volume (hindsight) | 1.05 | 0.86 | −23.3% | −47% |
| The same 35, admitted by the rolling $5M/day rule | 0.75 | 0.73 | −23.3% | −46.5% |
| **The pool of 65, admitted by the rule (what we trade)** | **0.94** | **0.81** | **−17.3%** | **−38.2%** |
| BTC hold | 0.73 | | −29.8% | −50% |

Composite is the Screen 3 formula, 0.4 × Sortino + 0.3 × Sharpe + 0.3 × Calmar, on the median fortnight's ratios.
The middle row is the honest price of the list: a tie with Bitcoin. The pool was pre-registered to be adopted
unless its tails or holdout ratios were materially worse, since a universe with no selection in it is the
principled one whatever it scores. It improved the worst fortnight by six points and max drawdown by eight, and
§2 calls drawdown the most valuable number on the board. Under the rule the core's median is below Bitcoin's. It
is a tail-control book, and it no longer looks like anything else.

The rule still contains one number, and it was never derived: $5M was a round figure applied by hand to a ticker
reading, carried into the rule unchanged. `scripts/liquidity_floor_study.py` tested its neighbours, with the
reading committed before the run. It is a robustness check, not a search; no floor is adopted for scoring best.
The entry, over the same pool:

| Floor | Composite | Worst fortnight | Max drawdown | Total | Composite after May | Total after May |
|---|---|---|---|---|---|---|
| $2M | 0.80 | −19.7% | −40.0% | +131% | 0.04 | +22.7% |
| $3M | 0.88 | −19.7% | −41.5% | +128% | −0.26 | +10.5% |
| **$5M (what we trade)** | 0.94 | **−17.3%** | **−38.2%** | **+146%** | **2.07** | **+32.2%** |
| $8M | 0.75 | −19.4% | −38.9% | +87% | 0.34 | +7.3% |
| $12M | **1.20** | −19.0% | −40.7% | +127% | −0.95 | −4.0% |
| BTC hold | 0.73 | −29.8% | −50% | +28% | 0.16 | −5.2% |

By the rule fixed beforehand this is SENSITIVE, in both books: a neighbour of $5M differs from it by more than
0.15 of composite or 2 points of tail. There is no trend in it either. $12M scores best in-sample and worst after
May, which is what picking a floor by score would have bought. So $5M stays, and three things change in how we
read our own numbers.

The headline is the mean of $3M, $5M and $8M, not the $5M row: for the entry a composite of 0.85, a worst
fortnight of −18.8%, a max drawdown of −39.5% and a total of +120%; for the core 0.75, −14.4%, −29.3% and +85%.
We did not choose $5M for its score, since the number predates every backtest, but it is the best of five on both
in-sample tail columns, and a reader should not take the best cell as the expectation.

The composite is a noisier statistic than we had been treating it. In-sample the five books are nearly the same
book: fortnight returns at $3M and $5M are 0.97 correlated, and at $5M and $8M the same. Yet the composite on
median window ratios runs from 0.75 to 1.20 across them. Differences of 0.2 between two variants are therefore
not findings, and that applies to our own table above: the pool's 0.94 against the 35 pairs' 0.75 is inside that
band. What the pool bought, against the 35 pairs at $5M, is tails: six points of worst fortnight at $5M and about
four at each of the other floors.

What holds at every floor is the claim about shape. In-sample, at all five, the entry's worst fortnight is
between −17% and −20% against Bitcoin's −30%, its max drawdown between −38% and −42% against −50%, its total
between +87% and +146% against +28%, and its composite at or above Bitcoin's.

### Out of sample: 2026-05-15 → 2026-09-14, looked at once

Before unsealing, we committed to a pass rule: a smaller worst fortnight and smaller max drawdown than BTC, and
beating BTC in at least 45% of windows.

| | Median | p10 | Worst | Beats BTC | Max DD | Total |
|---|---|---|---|---|---|---|
| **Core** | +0.41% | −3.8% | **−8.3%** | 51% | **−14.6%** | **+36.8%** |
| BTC hold | +0.03% | −12.8% | −20.7% | — | −29.4% | +13.8% |

It passed, and we reported it as the claim we would defend: that the core roughly halves Bitcoin's tails and
multiplies its total return. That table is the record of what was run on 2026-09-16 and we leave it as it was,
with two qualifications we did not know to make then. It ran on the fixed list, and the list was chosen on volume
at the *end* of these four months, so the holdout was exposed to the same hindsight as the sample: ZEC, the best
performer of the period, was in the list because of that performance. And its Total and Max DD columns count from
that run's start on 2026-04-01, six weeks before the first scored window; from 2026-05-15 Bitcoin's total is
−5.2%, not +13.8%.

The period has since been looked at more than once, and the entry was chosen after it was unsealed, so nothing run
on it now is a holdout. It is a consistency check. Under the rule the books now trade, on the same 109 windows,
from one continuous run, with totals and drawdowns counted from 2026-05-15:

| | Median | p10 | Worst | Beats BTC | Max DD | Total |
|---|---|---|---|---|---|---|
| Entry (pool, equal weight, 3%) | **+2.74%** | **−5.1%** | **−8.9%** | **63%** | −17.9% | **+32.2%** |
| Core (pool, inverse-vol, 2%) | +1.64% | −5.3% | −10.3% | 56% | **−17.2%** | +13.2% |
| BTC hold | +0.03% | −12.8% | −20.7% | — | −28.5% | −5.2% |

These are the $5M figures, and the floor table above shows how much that matters here: after May $5M is the best
of the five floors by a wide margin, and at $3M and $8M the entry made +10.5% and +7.3% with a composite near
zero. The period holds about eight independent fortnights, and the gap between $5M and $8M is mostly one of
them: in the fortnight from 2026-08-07 the book made +16% at $5M and nothing at $8M. What ran in that fortnight
were small names whose volume was crossing these floors as they rose (HEMI went from $1M to $16M a day while
gaining 71%), so a lower floor admits them sooner and a higher one later or not at all. That is one event, and
it cannot tell a better floor from a luckier one. At every floor the entry's total is above Bitcoin's −5.2% and
its worst fortnight inside Bitcoin's −20.7%; the ratios are not robust, and we do not quote them as evidence.

Both books still meet the terms of the pass rule. The claim that survives is the one about tails: the core's
worst fortnight is about half of Bitcoin's and its max drawdown about 60% of Bitcoin's, in-sample and here. The
claim about multiplying its return does not survive as we stated it. The core's +13% against −5% is a better
outcome, not a multiple, and on the fixed list the same book showed +23%.

The pool has a cost, and this is the kind of period that shows it. Against the rolling rule on the 35 pairs, the
entry's Sharpe over these windows falls from 2.16 to 1.92, and its rate of reaching the top 40% of the field in
rising fortnights falls from 73% to 45%. The top six of 65 are more volatile names than the top six of 35, the
volatility model sizes them smaller, and the book ran 62% invested against 72%. That is the exposure-for-tails
dial of §5.2 moved by the pool instead of the target. We did not raise the target to win it back, because that
would be a sweep on data already seen.

On the fixed list, the same window also produced a genuine surprise. A variant with equal weights and *no*
volatility target — the same signal at full exposure — returned +65% with a Sharpe of 1.56 and beat BTC in 62% of
fortnights. Those four months were volatile and rising, and volatility targeting cuts exposure exactly when
volatility rises, which in a volatile rally means missing upside. The vol target's advantage is therefore
**regime-dependent**, not universal. This is the evidence behind running a second, risk-on bot alongside the
core: the two win in different worlds.

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
| **Tokenised equities in the ranking pool** | Pre-registered and rejected for the entry. Two findings first. Every earlier test at 00:00 UTC had traded no stock at all, because our underlying-share history marks them stale outside US hours while Roostoo's tokens are live (§3). And the obvious fix, treating the carried-forward close as tradable, fails validation: on the same seven names over the same fourteen months it gives a Sharpe of 0.29 where the true 24/7 token prices give 1.19, so only the token panel is evidence. On that panel, adding the seven tokens to the entry lowers the top-40% rate in rising fortnights from 63% to 56% and in falling ones from 90% to 84%, Sharpe from 1.30 to 1.19 and total from +136% to +116%, while improving the worst fortnight from −23% to −16%. Stocks are a tail diversifier, not a return source at a 3–14-day momentum horizon; the entry was chosen for participation. |
| **Gold as a permanent sleeve** (idle cash held in PAXG, or PAXG as a fixed position inside the risk budget) | Pre-registered and rejected. Against the core it raised the median fortnight from +0.96% to +1.82% and every ratio (Sharpe 0.87 → 1.57), but made the worst fortnight worse (−15.8% → −19.3%, and −20.3% with gold's drift removed) and lost in the post-May-2026 period as gold fell 6% (p10 −3.1% → −6.2%). Two reasons. A cash sleeve is pro-cyclical: before a crash crypto is calm, the vol target leaves little idle cash, so there is little gold exactly when it is needed. And gold's correlation with crypto is near zero on average but not in a crash: in January 2026 it fell 8–10% alongside Bitcoin. Gold held *by rank* is there because gold is trending, whatever crypto is doing; the core with PAXG removed from the ranking is worse on every metric (worst −18.7%, total +71% against +103%, Sharpe 0.76). Conditional gold beats unconditional gold, which is the same lesson as volatility targeting beating gates. |
| **Downside-deviation targeting; an exposure floor** | Pre-registered to buy rally participation without paying in tails (§5.2). Downside targeting is a wash with the core on every column; a 70% floor leaves the book 77% invested and still outside the top 40% in most big rallies, at a cost of four points of worst fortnight. |
| **A BTC short against the long book** (the rules' "1x short") | Pre-registered and rejected. A short sized at 25–100% of the long notional was tested on both the vol-targeted core and the full-exposure twin, gross capped at 1x. In the harness the hedge is a dial that trades return for tails almost one-for-one: on the full-exposure leg it runs from the twin (worst fortnight −33%, total +263%) to −13% and +103% at a full hedge, with the median-window Sharpe flat at 0.83–0.87 until three-quarters hedged and collapsing to 0.4 beyond. No ratio met the rule. At three-quarters hedged the fortnight distribution is the core's (median +0.84% vs +0.96%, p10 −6.3% vs −6.7%, worst −15.2% vs −15.8%, Sharpe 0.83 vs 0.87); the larger multi-year total (+138% vs +103%) comes from a fatter right tail, and in rising fortnights the hedged book ranks no better against naive competitors than the core does. Volatility targeting delivers the same distribution without shorts, without unverified exchange mechanics, and without a gross-exposure guard (realised gross drifted to 1.2× between rebalances). A daily spike had suggested a large ratio gain from the hedge; the harness, with hourly decisions, fees and the drift band, did not confirm it, which is why the harness is the arbiter. |
| **A short leg on the ranking's losers** | Tested in the harness last, and the one rejected idea we expect to revisit. On its own the leg loses: −24% in-sample, −19% after May, worst fortnight −35%. As a quarter of gross exposure it changes the book: p10 from −10.3% to −7.0%, worst fortnight −23.3% to −18.3%, max drawdown −47% to −33%, fortnights below −10% from one in nine to one in twenty, total +176% to +222%. Losers carry negative alpha as well as beta, which is why this works where the BTC hedge did not. It fails our pre-registered rule on one line: the top-40% rate in rising fortnights falls from 52% to 44%, and a higher volatility target cannot win that back because the 1x cap on gross exposure binds. The robustness pass says the tail gain is real: smooth in the short share from 15% to 35%, stable across 4, 6 and 8 shorts, present at K=8, at the 12:00 selection hour and after May. The ratio gain is not yet trustworthy: +1.0 of Sharpe when selecting at 00:00 UTC, +0.1 at 12:00. It is not in the book because every number above assumes that a short is a sell beyond the holding, valued at price, with no borrow cost and a 1x cap on gross, and the exchange's API documents describe none of it. The test account decides. |
| **LLM-driven trading** | Cannot be backtested honestly — the model has already seen the history it would be tested on. Nondeterministic, and it costs money per decision. |
| **News and sentiment** | News moves prices, but the question is whether a sentiment measure carries information the price signal does not. The one sentiment series with a free multi-year daily history, the Crypto Fear & Greed index, has a rank correlation with BTC's forward return of +0.02 at one day and +0.07 at fourteen, indistinguishable from zero, and is 0.56 rank-correlated with the trailing 14-day return: it is price momentum with a survey attached (`scripts/sentiment_check.py`). Headline-level scoring by an LLM cannot be validated on history for the reason above, and its exploitable horizon is hours, where fees dominate. Post-news drift is what momentum trades by construction, and the EWMA volatility estimate already cuts exposure within hours of a shock. |
| **HAR volatility regression** | Won on mean squared error, lost on QLIKE at both horizons: it under-predicts volatility spikes, which is the one error a risk control cannot make (§5.1). |
| **Learned return models generally** | Our 32 assets carry an average pairwise correlation of 0.55, so they are worth about 1.8 independent series; at a weekly horizon that leaves roughly 180 effective independent observations. Measured on our own data, trailing returns predict next-day returns with an R² of 0.001, against 0.048 for volatility. There is not enough independent information to fit a return model, and we have already seen two six-parameter "improvements" cancel each other. |
| **Reinforcement learning** | Sample-hungry and regime-overfitting; 14 days cannot distinguish skill from luck in its output. |
| **Arbitrage / HFT / market making** | Explicitly banned by the rules. We also avoid anything resembling it, such as trading Roostoo's feed against a faster external one, or exploiting stale weekend prices. |

## 8. Known limitations

We would rather state these than have them found.

- **The universe was chosen with hindsight, and that was most of the measured edge.** We found this one
  ourselves, two weeks before the competition, and it changed every headline number in this paper. The 35-pair
  list was chosen on traded volume on 2026-09-14 and backtested over the two years before it. ZEC traded $1.9M a
  day when the sample began, below the floor, and is in the list because it then rose 36-fold. Our look-ahead
  checker cannot see this: it perturbs prices within a fixed set of columns, and the universe *is* the columns.
  `scripts/universe_bias_study.py` measured it on one panel against one field of competitors. With the same 35
  pairs admitted by a rolling rule that sees only past volume, the entry's composite falls from 1.05 to 0.75
  and the core's from 0.86 to 0.73, a tie with holding Bitcoin. The fix was to stop having a list: the $5M
  floor is now a rule inside the signal, applied hourly to every pair Roostoo lists, and the same code runs
  live. On that pool the composites are 0.94 and 0.81 and the tails are shallower (§6). The rule is still an
  optimistic bound. It cannot see coins Roostoo never listed or had delisted before our snapshot, and it uses
  Binance volume as a proxy for Roostoo's.
- **The liquidity floor is an arbitrary number, and the results move with it.** $5M was never derived. Tested
  against $2M, $3M, $8M and $12M with the reading committed first, the entry's in-sample composite runs from 0.75
  to 1.20 and its total from +87% to +146%, with no trend: the floor that scores best in-sample scores worst
  after May. $5M is the best of the five on in-sample tails and far the best after May, so its row flatters us,
  and the figure we stand behind is the mean of $3M, $5M and $8M (§6). Two lessons go beyond the floor. Books
  whose fortnight returns are 0.97 correlated differ by 0.2 of composite, so differences that size between any
  two variants in this paper are not findings. And the four months after May cannot rank anything: one August
  fortnight decides them. The tails against Bitcoin hold at every floor. We keep $5M because no other number is
  defensible either, and moving to the best cell is how a backtest gets overfitted.
- **The volume rule admits small names as they pump.** A coin's trailing seven-day dollar volume surges when its
  price does, so the rule lets a small name into the ranking during the very move that makes it rank well. In
  one fortnight of August 2026 HEMI went from $1M to $16M a day while gaining 71%. Part of the entry's rally
  return comes from this, and we have left it alone for three reasons. It is not look-ahead: the rule sees volume
  only to the decision hour and runs identically live. The failure it invites, a pump that reverses, does not
  show in the tails: a $2M floor admits 51 pairs on average against 35 at $12M, and the entry's worst fortnight
  is −19.7% against −19.0% and its max drawdown −40.0% against −40.7%. And we cannot validate a replacement, such
  as a longer window or one that ends before the momentum lookback begins, on data that cannot resolve the floor
  itself; the window's seven days, like the floor's $5M, was never derived. One cost is unmodelled. The simulator
  fills at the close with no spread, and on Roostoo the names near the floor quote 5 to 10 bps wide, so crossing
  costs 2 to 5 bps a side on top of the 10 bps fee. That comes from one calm 7.5-hour sample of the ticker, so
  it is a lower bound.
- **§5, §5.2 and §7 still quote the fixed list.** Their tables were run before the universe became a rule and
  have not been re-run. Each compares books on the same panel, so the direction of a comparison is likelier to
  hold than its level, and every level in them is flattered. The numbers we stand behind are in §1, §6 and
  this section.
- **The pool costs rally rank.** In the four months after May 2026 the entry on the pool reached the top 40%
  of the field in 45% of rising fortnights, against 73% for the rule on the 35 pairs, because it ran 62%
  invested against 72% (§6). In the 25 windows of that period where Bitcoin gained more than 5%, the entry
  reached the top 40% in a quarter and the core in none. We took the trade for six points of worst fortnight
  and eight of max drawdown, and because the alternative was a universe we could not defend.
- **The sample is small.** Two years of hourly data contains roughly 43 independent fortnights. Medians are
  trustworthy; extreme quantiles are indicative at best.
- **Part of the in-sample edge is timing luck.** We swept the selection hour across six values, on the fixed
  list. Tails and total return were robust everywhere (worst fortnight −15% to −17%, max drawdown −32% to −35%,
  total +61% to +111%), but the "better median and Sharpe than BTC" claim holds only at 00:00 and 12:00 UTC. We
  kept 00:00 because it is the daily-candle convention chosen before any comparison was run — not because it
  scored best — and we discount the headline numbers accordingly.
- **Small differences are noise.** A single tie-break in the simulator's fill order once compounded into an
  11-point difference in total return over 20 months. We fixed the non-determinism, and we treat any gap under
  about 10 points of total return as meaningless.
- **The strategy will lose in choppy and V-shaped markets.** It is late to every turn by construction. Over one
  14-day window the market path dominates; what momentum reliably does is reshape the distribution, not pick the
  outcome.
- **For Screen 2 the core is a selloff specialist.** Ranked each fortnight against 35 competitors who simply hold
  one liquid coin, it beats at least 60% of them in 91% of fortnights when Bitcoin falls and in 35% when Bitcoin
  rises; when Bitcoin gains more than 5% it reaches the top fifth of that field 6% of the time, and the entry
  11%. §5.2 gives the frontier this sits on, measured on the fixed list. How high the real bar sits depends on
  how many teams enter a region, which we do not know.
- **The entry was chosen after the holdout was opened.** The core passed a sealed test, with the qualifications
  of §6; the equal-weight book was found and chosen afterwards, on the frontier of §5.2, and its post-May figures
  are a consistency check. On the fixed list its ratio advantage over the core was about 0.1 of Sharpe and did
  not survive K=8. On the pool the gap is 0.18 in-sample, and the K=8 test has not been re-run, so we do not lean
  on it. Its rally participation is what it was chosen for.
- **The entry's tails are deeper by design.** One fortnight in thirteen loses more than 10%, against one in
  thirty-seven for the core, and its typical 14-day drawdown is 6.3% against 4.5%. Those losses did not cost rank
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
rather than risking a duplicate fill (`place_order` never retries), caps per-order size as a runaway guard, and
paces every API call at two seconds so that a full rebalance stays under the exchange's limit of thirty calls a
minute even with retries.

**Rule compliance is built in, not promised.** Every request and decision is journalled as JSON stamped with the
git commit that produced it, so the trade log maps to the code that made it. There is no manual-trading path: the
emergency stop is a `mode` field in a committed config file that the loop re-reads every cycle. An activity
tracker watches the 8-active-day requirement and forces a genuine rebalance if the pace falls behind, because
backtests showed calm fortnights producing as few as 6 trading days.

**Testing.** 272 tests, all offline and deterministic. A look-ahead checker perturbs prices after time *t* and
asserts that signals up to *t* are unchanged; it runs on every strategy before its results are reported. Because
no test API key was available before the competition, we wrote a local server implementing the documented Roostoo
API over real HTTP — signature validation over the exact bytes sent, the timestamp window, the documented error
envelopes, and injectable faults — and rehearsed the full engine against it.

## 10. Reproducing our results

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest                  # 272 tests
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
