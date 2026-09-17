#!/usr/bin/env bash
# One-shot setup of a fresh Ubuntu EC2 host (the organizers' Sydney instance) for the competition bot.
#
#   sudo bash deploy/setup_ec2.sh https://github.com/<you>/qtrading.git [configs/eqvt3.toml]
#
# Afterwards put the real keys in /opt/qtrading/.env, verify one keyless cycle, then start the service:
#   sudo -u ubuntu /opt/qtrading/.venv/bin/python /opt/qtrading/scripts/run_bot.py --config /opt/qtrading/configs/paper-eqvt3.toml --once
#   sudo systemctl start qtrading && journalctl -u qtrading -f
# Re-running the script is safe: it pulls, reinstalls and reloads the unit.
set -euo pipefail

REPO="${1:?git URL of the repository}"
CONFIG="${2:-configs/eqvt3.toml}"
APP=/opt/qtrading
RUN_AS=ubuntu

apt-get update -y
apt-get install -y --no-install-recommends git python3 python3-venv python3-pip chrony
timedatectl set-ntp true                       # signed requests must carry a timestamp within 60 s of Roostoo's clock

if [ -d "$APP/.git" ]; then
    git -C "$APP" pull --ff-only
else
    git clone "$REPO" "$APP"
fi
chown -R "$RUN_AS:$RUN_AS" "$APP"

sudo -u "$RUN_AS" python3 -m venv "$APP/.venv"
sudo -u "$RUN_AS" "$APP/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$RUN_AS" "$APP/.venv/bin/pip" install --quiet -e "$APP"
sudo -u "$RUN_AS" mkdir -p "$APP/logs" "$APP/data/live" "$APP/data/paper"

if [ ! -f "$APP/.env" ]; then
    cp "$APP/.env.example" "$APP/.env"
    chown "$RUN_AS:$RUN_AS" "$APP/.env"
    chmod 600 "$APP/.env"
    echo "!! $APP/.env was created from the template: fill in the keys before starting the service"
fi

sed "s#configs/eqvt3.toml#$CONFIG#" "$APP/deploy/qtrading.service" > /etc/systemd/system/qtrading.service
systemctl daemon-reload
systemctl enable qtrading

echo
echo "installed $APP at commit $(git -C "$APP" rev-parse --short HEAD), service 'qtrading' enabled with $CONFIG"
echo "verify one keyless cycle:  sudo -u $RUN_AS $APP/.venv/bin/python $APP/scripts/run_bot.py --config $APP/configs/paper-eqvt3.toml --once"
echo "start trading:             sudo systemctl start qtrading && journalctl -u qtrading -f"
