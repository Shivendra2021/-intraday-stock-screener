#!/usr/bin/env bash
set -e
timedatectl set-timezone Asia/Kolkata
apt-get update -y
apt-get install -y python3 python3-pip python3-venv
if [ ! -d venv ]; then python3 -m venv venv; fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data logs output data/backups
cp deploy/screener-dashboard.service /etc/systemd/system/
cp deploy/screener-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable screener-dashboard
systemctl enable screener-bot
systemctl restart screener-dashboard
systemctl restart screener-bot
if command -v ufw > /dev/null; then ufw allow 5001/tcp || true; fi
echo Setup finished! Dashboard is active on port 5001.
