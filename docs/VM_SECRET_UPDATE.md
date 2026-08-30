# VM Secret Update Steps

Use these steps to update runtime secrets on the Ubuntu VM.

## 1) Edit the runtime environment file

```bash
sudo nano /etc/neoapp2/neoapp.env
```

Update any required keys, for example:

- `CONSUMER_KEY=...`
- `CONSUMER_SECRET=...` (if used by your app)
- `MPIN=...`
- `TOTP_SECRET=...`
- `WEB_API_TOKEN=...`

Save and exit.

## 2) Restart services

```bash
sudo systemctl restart neo-worker.service neo-fastapi.service
sudo systemctl status neo-worker.service --no-pager
sudo systemctl status neo-fastapi.service --no-pager
```

## 3) (Optional) Update one key without opening editor

Example for `CONSUMER_KEY`:

```bash
sudo sed -i 's/^CONSUMER_KEY=.*/CONSUMER_KEY=new_value_here/' /etc/neoapp2/neoapp.env
sudo systemctl restart neo-worker.service neo-fastapi.service
```

## 4) Ensure file permissions stay strict

```bash
sudo chown root:neoapp /etc/neoapp2/neoapp.env
sudo chmod 640 /etc/neoapp2/neoapp.env
```

## 5) Verify API health

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS https://172-198-74-162.sslip.io/health
```
