"""Run the pre-registered limit-order check: ONE order, on the TEST account, judged by a rule written beforehand.

  .venv\\Scripts\\python.exe scripts\\limit_order_check.py            # dry run: shows the order, sends nothing signed
  .venv\\Scripts\\python.exe scripts\\limit_order_check.py --place    # places it, journals what happened, prints the verdict

The question, the order and the adopt rule are in src/qtrading/roostoo/limit_check.py, and docs/runbook.md says
what each outcome means for the entry. Keys come from .env as ROOSTOO_API_KEY_TEST / ROOSTOO_SECRET_KEY_TEST. The
unsuffixed names are the competition account's and this script refuses them: a hand-placed order there is the
manual trading the rules prohibit. Rehearse against the local mock with --key-suffix _MOCK --base-url
http://127.0.0.1:8787 (the mock rests every limit order, so the rehearsal ends in "keep market orders").

The observation is appended to logs/limit-check_test.jsonl, stamped with the commit, so the decision has a record
(a rehearsal writes to its own file, named for its key suffix, and never into that one).
"""
import argparse
import os
import sys
from pathlib import Path

from qtrading.engine.journal import Journal, commit_warning, current_commit
from qtrading.execution import floor_to
from qtrading.roostoo.client import DEFAULT_BASE_URL, RoostooClient
from qtrading.roostoo.limit_check import observe, touch_price, verdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_bot import load_dotenv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", action="store_true", help="send the order; without this nothing signed is sent")
    ap.add_argument("--pair", default="BTC/USD")
    ap.add_argument("--notional", type=float, default=100.0)
    ap.add_argument("--key-suffix", default="_TEST")
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    if not args.key_suffix:
        print("refusing: the unsuffixed keys are the competition account's, and this check never touches it")
        return 2
    base_url = args.base_url or os.environ.get("ROOSTOO_BASE_URL", DEFAULT_BASE_URL)

    if not args.place:
        public = RoostooClient(api_key="", secret_key="", base_url=base_url)
        rules, ticker = public.exchange_info()[args.pair], public.ticker()[args.pair]
        price = touch_price(ticker.ask, rules.price_precision)
        qty = floor_to(args.notional / price, rules.amount_precision)
        print(f"dry run against {base_url}: would place LIMIT BUY {qty:.{rules.amount_precision}f} {args.pair} "
              f"at {price:.{rules.price_precision}f} (bid {ticker.bid:g}, ask {ticker.ask:g}, "
              f"about ${qty * price:,.2f}). Add --place to send it.")
        return 0

    try:
        key = os.environ[f"ROOSTOO_API_KEY{args.key_suffix}"]
        secret = os.environ[f"ROOSTOO_SECRET_KEY{args.key_suffix}"]
    except KeyError as e:
        print(f"refusing: {e.args[0]} is not set in .env")
        return 2

    commit = current_commit(ROOT)
    if commit_warning("limit-check", commit):
        print(commit_warning("limit-check", commit))
    journal = Journal(ROOT / "logs" / f"limit-check{args.key_suffix.lower()}.jsonl", commit)

    obs = observe(RoostooClient(key, secret, base_url=base_url), args.pair, args.notional)
    adopt, lines = verdict(obs)
    journal.record("limit_check", base_url=base_url, key_suffix=args.key_suffix, adopt=adopt, lines=lines,
                   **obs.to_record())

    print(f"\nLIMIT BUY {obs.quantity:g} {obs.pair} at {obs.limit_price:g} (bid {obs.bid:g}, ask {obs.ask:g}) "
          f"-> order {obs.placed.order_id}")
    print("\n".join("  " + line for line in lines))
    if adopt:
        print("\nVERDICT: ADOPT. A limit order at the touch is a market order at half the fee. Next: docs/runbook.md,"
              "\n'Limit orders (only if adopted)'. The account now holds the coin this order bought.")
    else:
        print("\nVERDICT: KEEP MARKET ORDERS. The rule was written before the run; there is no second order.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
