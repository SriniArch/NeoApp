# Azure VM Deployment (API + Worker + Nginx + TLS)

## 1) Initial VM bootstrap
From repository root on the VM:

```bash
chmod +x scripts/azure/setup_vm.sh
./scripts/azure/setup_vm.sh <your-domain> <letsencrypt-email>
```

This installs:
- system packages (`python3-venv`, `nginx`, `certbot`)
- `neo-fastapi.service`
- `neo-worker.service`
- Nginx reverse proxy with HTTPS

## 2) Runtime environment file
Create:

- `/etc/neoapp2/neoapp.env`

Minimum required keys:

```env
WEB_API_TOKEN=<strong-token>
TRADING_ENABLED=false
WEB_POLL_SECONDS=5
WORKER_HEALTH_WINDOW_SECONDS=30

CONSUMER_KEY=...
MOBILE=...
UCC=...
MPIN=...
TOTP_SECRET=...
```

## 3) Deploy application release
Deployment is automated via:

- [.github/workflows/deploy-azure-vm.yml](.github/workflows/deploy-azure-vm.yml)

Required repository secrets:
- `AZURE_VM_HOST`
- `AZURE_VM_USER`
- `AZURE_VM_SSH_KEY`
- `AZURE_VM_PORT` (optional)
- `DEPLOY_PATH` (example: `/opt/neoapp2`)
- `AZURE_PUBLIC_URL` (example: `https://your-domain`)

## 4) Service control

```bash
sudo systemctl daemon-reload
sudo systemctl enable neo-worker.service neo-fastapi.service nginx
sudo systemctl restart neo-worker.service neo-fastapi.service nginx
sudo systemctl status neo-worker.service --no-pager
sudo systemctl status neo-fastapi.service --no-pager
```

## 5) Health verification

Local checks on VM:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/system/status -H "X-API-Key: <token>"
```

External checks:

```bash
curl -fsS https://<your-domain>/health
curl -fsS https://<your-domain>/api/system/status -H "X-API-Key: <token>"
```

TLS check:

```bash
sudo certbot certificates
```

## 6) Nginx config source
- [deploy/nginx/neoapp2.conf](deploy/nginx/neoapp2.conf)

## 7) Systemd unit sources
- [deploy/systemd/neo-fastapi.service](deploy/systemd/neo-fastapi.service)
- [deploy/systemd/neo-worker.service](deploy/systemd/neo-worker.service)
