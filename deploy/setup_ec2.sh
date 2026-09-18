#!/usr/bin/env bash
# One-shot setup of a fresh Linux host -- the organizers' Sydney EC2 instance or a personal VPS -- for one or more
# bots, each a systemd instance named after its config file.
#
#   sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git eqvt3
#   sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git paper-core paper-eqvt3 paper-ls25
#
# Target: Ubuntu Server 24.04 LTS (x86_64) on both the VPS and EC2, so the competition deployment repeats a procedure
# already run. Amazon Linux 2023, the EC2 wizard's default image, is handled too in case the organizers require it
# (untested: no such host was available when this was written).
#
# RUN_AS is the account the bots run under: `ubuntu` on Ubuntu, `ec2-user` on Amazon Linux, created if missing (a VPS
# that hands out only root). The test suite runs at the end of the install, so a Python the code does not support
# fails here rather than on the first cycle. Then put the keys in <app>/.env and start the bots:
#   sudo systemctl start qtrading@eqvt3 && journalctl -u qtrading@eqvt3 -f
# Re-running the script is safe: it pulls, reinstalls, re-tests and reloads the units.
set -euo pipefail

REPO="${1:?git URL of the repository}"
shift
BOTS=("$@")
[ ${#BOTS[@]} -gt 0 ] || BOTS=(eqvt3)
APP="${APP:-/opt/qtrading}"

if command -v apt-get >/dev/null 2>&1; then            # Ubuntu / Debian
    apt-get update -y
    apt-get install -y --no-install-recommends git python3 python3-venv python3-pip chrony
    PY=python3
    DEFAULT_USER=ubuntu
elif command -v dnf >/dev/null 2>&1; then              # Amazon Linux 2023 ships Python 3.9; the code needs 3.12
    dnf install -y git python3.12 python3.12-pip chrony
    PY=python3.12
    DEFAULT_USER=ec2-user
else
    echo "unsupported OS: this script knows apt (Ubuntu) and dnf (Amazon Linux 2023)" >&2
    exit 1
fi
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
    || { echo "$PY is $("$PY" --version); the bot needs Python 3.12 or newer" >&2; exit 1; }
RUN_AS="${RUN_AS:-$DEFAULT_USER}"

# signed requests must carry a timestamp within 60 s of Roostoo's clock
systemctl enable --now chronyd 2>/dev/null || systemctl enable --now chrony 2>/dev/null || true

id -u "$RUN_AS" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$RUN_AS"

# a small box needs swap: importing pandas in several bots at once is the memory peak (dd, not fallocate: XFS on
# Amazon Linux refuses swap files with unwritten extents)
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1900 ] && ! swapon --show | grep -q .; then
    dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
    chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [ -d "$APP/.git" ]; then
    sudo -u "$RUN_AS" git -C "$APP" pull --ff-only
else
    git clone "$REPO" "$APP"
    chown -R "$RUN_AS:$RUN_AS" "$APP"
fi

sudo -u "$RUN_AS" "$PY" -m venv "$APP/.venv"
sudo -u "$RUN_AS" "$APP/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$RUN_AS" "$APP/.venv/bin/pip" install --quiet -e "$APP[dev]"
sudo -u "$RUN_AS" mkdir -p "$APP/logs" "$APP/data/live" "$APP/data/paper"
echo "running the test suite on $("$APP/.venv/bin/python" --version)..."
(cd "$APP" && sudo -u "$RUN_AS" "$APP/.venv/bin/python" -m pytest -q)

if [ ! -f "$APP/.env" ]; then
    cp "$APP/.env.example" "$APP/.env"
    chown "$RUN_AS:$RUN_AS" "$APP/.env"
    chmod 600 "$APP/.env"
    echo "!! $APP/.env was created from the template: fill in the keys before starting the bots"
fi

sed -e "s#@RUN_AS@#$RUN_AS#g" -e "s#@APP@#$APP#g" "$APP/deploy/qtrading@.service" > /etc/systemd/system/qtrading@.service
systemctl daemon-reload
for bot in "${BOTS[@]}"; do
    [ -f "$APP/configs/$bot.toml" ] || { echo "no config configs/$bot.toml"; exit 1; }
    systemctl enable "qtrading@$bot"
done

# The journal stamps every record with the running commit, asked of git once at start-up. If the service user cannot
# ask -- a repo it does not own, a partial .git -- every record says "unknown" for as long as the bot runs. Check it
# here, as that user, and fail the install rather than find out from a judge. (Asked as root this line can also print
# an empty hash under Session Manager, where SUDO_UID is not the repo's owner.)
COMMIT="$(sudo -u "$RUN_AS" git -C "$APP" rev-parse --short HEAD)" || {
    echo "ERROR: $RUN_AS cannot read the git commit in $APP; the journal would stamp 'unknown' on every record."
    echo "       check ownership (chown -R $RUN_AS:$RUN_AS $APP) and that .git is complete, then re-run."
    exit 1
}

echo
echo "installed $APP at commit $COMMIT; enabled: ${BOTS[*]}"
echo "check one keyless cycle:  sudo -u $RUN_AS $APP/.venv/bin/python $APP/scripts/run_bot.py --config $APP/configs/paper-eqvt3.toml --once"
echo "start:                    sudo systemctl start ${BOTS[*]/#/qtrading@}"
echo "watch:                    journalctl -u 'qtrading@*' -f"
