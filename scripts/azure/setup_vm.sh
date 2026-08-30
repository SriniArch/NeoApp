#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <domain> <letsencrypt_email>"
  exit 1
fi

DOMAIN="$1"
LE_EMAIL="$2"
APP_USER="neoapp"
APP_DIR="/opt/neoapp2"
ENV_DIR="/etc/neoapp2"

echo "[1/8] Installing OS packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx curl

echo "[2/8] Creating app user and directories"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd -m -s /bin/bash "$APP_USER"
fi
sudo mkdir -p "$APP_DIR"/releases "$APP_DIR"/incoming "$ENV_DIR"
sudo chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "[3/8] Creating venv"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR"/venv

echo "[4/8] Installing systemd unit files"
sudo cp deploy/systemd/neo-fastapi.service /etc/systemd/system/neo-fastapi.service
sudo cp deploy/systemd/neo-worker.service /etc/systemd/system/neo-worker.service

echo "[5/8] Installing Nginx site config"
sudo sed "s/__SERVER_NAME__/$DOMAIN/g" deploy/nginx/neoapp2.conf | sudo tee /etc/nginx/sites-available/neoapp2 >/dev/null
sudo ln -sfn /etc/nginx/sites-available/neoapp2 /etc/nginx/sites-enabled/neoapp2
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "[6/8] Requesting TLS certificate"
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$LE_EMAIL" --redirect

echo "[7/8] Enabling services"
sudo systemctl daemon-reload
sudo systemctl enable neo-fastapi.service neo-worker.service nginx

echo "[8/8] Done"
echo "Create runtime environment file at: $ENV_DIR/neoapp.env"
echo "Then deploy app release and restart services:"
echo "  sudo systemctl restart neo-worker.service neo-fastapi.service"
echo "Verification:"
echo "  curl -fsS http://127.0.0.1:8000/health"
echo "  curl -fsS https://$DOMAIN/health"
