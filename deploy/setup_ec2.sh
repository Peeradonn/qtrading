#!/usr/bin/env bash
# One-shot setup of a fresh Ubuntu 24.04 host -- the organizers' Sydney EC2 instance or any Linux VPS -- for one or
# more bots, each a systemd instance named after its config file.
#
#   sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git eqvt3
#   sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git paper-core paper-eqvt3 paper-ls25
#
# RUN_AS (default: ubuntu) is the account the bots run under; it is created if missing, which is what a VPS that
# hands out only root needs. The test suite runs at the end of the install, so a Python the code does not support
# fails here rather than on the first cycle. Then put the keys in <app>/.env and start the bots:
#   sudo systemctl start qtrading@eqvt3 && journalctl -u qtrading@eqvt3 -f
# Re-running the script is safe: it pulls, reinstalls, re-tests and reloads the units.
set -euo pipefail

REPO="${1:?git URL of the repository}"
shift
BOTS=("$@")
[ ${#BOTS[@]} -gt 0 ] || BOTS=(eqvt3)
APP="${APP:-/opt/qtrading}"
RUN_AS="${RUN_AS:-ubuntu}"

apt-get update -y
apt-get install -y --no-install-recommends git python3 python3-venv python3-pip chrony
systemctl enable --now chrony || true   # signed requests must carry a timestamp within 60 s of Roostoo's clock

id -u "$RUN_AS" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$RUN_AS"

# a small box needs swap: importing pandas in three bots at once is the memory peak
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1900 ] && ! swapon --show | grep -q .; then
    fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [ -d "$APP/.git" ]; then
    sudo -u "$RUN_AS" git -C "$APP" pull --ff-only
else
    git clone "$REPO" "$APP"
    chown -R "$RUN_AS:$RUN_AS" "$APP"
fi

sudo -u "$RUN_AS" python3 -m venv "$APP/.venv"
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

echo
echo "installed $APP at commit $(git -C "$APP" rev-parse --short HEAD); enabled: ${BOTS[*]}"
echo "check one keyless cycle:  sudo -u $RUN_AS $APP/.venv/bin/python $APP/scripts/run_bot.py --config $APP/configs/paper-eqvt3.toml --once"
echo "start:                    sudo systemctl start ${BOTS[*]/#/qtrading@}"
echo "watch:                    journalctl -u 'qtrading@*' -f"
