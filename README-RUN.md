# NeoApp2 Run Guide

This guide explains how to run NeoApp2 in:
- Desktop mode (Tkinter app)
- Web mode (API + Web UI + background worker)

## 1) Prerequisites

- Python environment is created and activated.
- Dependencies are installed from:
  - requirements.txt
  - requirements-web.txt
- A valid .env file is present with broker credentials and web settings.

## 2) Desktop Mode (Tkinter)

Run the desktop app:

```bash
python run.py
```

What this starts:
- Tkinter trading UI
- Monitor updates and trading controls inside the desktop window

## 3) Web Mode (API + Worker)

Web mode needs two processes:
1. Worker (polls broker and writes snapshot state)
2. API server (serves REST API, WebSocket, and Web UI)

### Terminal A: Start Worker

```bash
python -m web.worker.main
```

### Terminal B: Start API Server

```bash
uvicorn web.backend.main:app --host 0.0.0.0 --port 8001
```

## 4) Open Web UI

In browser:

- http://127.0.0.1:8001/

## 5) API Authentication

API uses header token from .env:

- WEB_API_TOKEN=<your_token>

Send this header on protected endpoints:

- X-API-Key: <your_token>

Example status call:

```bash
curl -H "X-API-Key: <your_token>" http://127.0.0.1:8001/api/system/status
```

## 6) Important Web Environment Flags

Set in .env:

- WEB_API_TOKEN=...
- TRADING_ENABLED=false (recommended first)
- WEB_POLL_SECONDS=5
- WORKER_HEALTH_WINDOW_SECONDS=30

Optional local debug only:

- WEB_ALLOW_LOCAL_NOAUTH=true

## 7) Basic Health Checks

- API health: GET /health
- System status: GET /api/system/status
- Monitor snapshot: GET /api/monitor/snapshot
- WebSocket stream: /ws/monitor

## 8) Recommended Start Order

1. Start worker
2. Start API server
3. Open UI and verify status
4. Enable trading only after validations

## 9) File References

- Desktop entry: [run.py](run.py)
- API server: [web/backend/main.py](web/backend/main.py)
- Worker: [web/worker/main.py](web/worker/main.py)
- Web auth: [web/backend/auth.py](web/backend/auth.py)
- Detailed architecture: [Logic/PROJECT_LOGIC.md](Logic/PROJECT_LOGIC.md)
