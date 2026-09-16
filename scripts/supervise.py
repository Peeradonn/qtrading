"""Keep a bot running on a machine with no service manager.

  .venv\\Scripts\\python.exe scripts\\supervise.py --config configs\\paper-core.toml

Runs scripts/run_bot.py, restarts it whenever it exits, and backs off exponentially if it keeps dying quickly.
Every restart is logged and sent to the operator channel, because a bot that quietly stops is the failure that
looks exactly like a quiet market. On EC2 this is systemd's job (Restart=always) and this script is unnecessary.
Exit code 2 from the bot means another instance holds the lock, so the supervisor stops rather than fighting it.
"""
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qtrading.engine.alerts import make_alerter  # noqa: E402
from qtrading.engine.supervise import next_delay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALREADY_RUNNING = 2
log = logging.getLogger("qtrading.supervisor")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--max-restarts", type=int, default=0, help="stop after this many restarts (0 = never stop)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "logs" / "supervisor.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_bot import load_dotenv
    load_dotenv(ROOT / ".env")
    alert = make_alerter(enabled=True)

    command = [sys.executable, str(ROOT / "scripts" / "run_bot.py"), "--config", str(Path(args.config).resolve())]
    delay, restarts = 0.0, 0
    while True:
        started = time.monotonic()
        log.info("starting bot: %s", " ".join(command[-3:]))
        code = subprocess.call(command, cwd=ROOT)
        ran_for = time.monotonic() - started

        if code == ALREADY_RUNNING:
            log.error("another instance holds the lock; supervisor exiting")
            return ALREADY_RUNNING

        restarts += 1
        delay = next_delay(ran_for, delay)
        message = (f"bot exited with code {code} after {ran_for / 60:.1f} min; "
                   f"restart #{restarts} in {delay:.0f}s")
        log.warning(message)
        alert(f"[supervisor] {message}")
        if args.max_restarts and restarts >= args.max_restarts:
            log.info("restart limit reached; supervisor exiting")
            return 0
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
