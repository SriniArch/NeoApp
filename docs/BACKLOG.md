# NeoApp2 Backlog

Last updated: 2026-08-27

## Scope Basis
This backlog is based on the completed discussion and current project structure (desktop app + web stack).

---

## ✅ Implemented

### 1) Web foundation (Phase 0/1 base)
- FastAPI backend created with health/status/monitor/trade/symbol endpoints.
- WebSocket monitor stream added.
- Background worker loop added to poll broker data and build snapshots.
- Shared state persistence added via JSON snapshot file.

### 2) Hardening (P0)
- API key guard added for HTTP and WebSocket paths.
- Trading enable/disable gate added via environment flag.
- Snapshot health checks added (worker heartbeat window).
- Atomic snapshot writes added to avoid partial/corrupt reads.
- Request/response model validation added (Pydantic models).

### 3) Trading safety and risk controls (P1)
- Position-safe trade action flow implemented.
- Order completion verification/retry flow implemented.
- Buy-disable guardrails implemented:
  - progressive loss lockout,
  - cool-off handling,
  - consecutive-loss checks,
  - max-profit/max-loss style stops.
- Buy-disable state persistence integrated.

### 4) Rich monitor and helper features (P2)
- Rich monitor payload added (`indicator`, `position`, `risk`, `automation`).
- Weekly/day trade stats and PnL aggregation added.
- Symbol helper logic added (ATM/offset/CE-PE suggestion).
- Trade journal CSV persistence integrated.
- Server IP surfaced in API/UI status path.

### 5) Project documentation
- Comprehensive logic reference created at [Logic/PROJECT_LOGIC.md](Logic/PROJECT_LOGIC.md).
- Copilot instruction file created at [copilot-instructions.md](copilot-instructions.md).

---

## 🟡 Pending

### A) Deployment completion (P3)
Priority: High
- Finalize Azure VM deployment steps end-to-end.
- Complete service setup (systemd) for API + worker.
- Add reverse proxy/TLS (Nginx + HTTPS).
- Finalize and validate GitHub Actions deploy pipeline.

### B) Production operations
Priority: High
- Add log rotation/retention policy for runtime and CSV logs.
- Add backup/restore for state and trade history files.
- Add startup/recovery scripts for safe restart after host reboot.

### C) End-to-end validation
Priority: High
- Full dry-run and live-safe test checklist for:
  - order placement,
  - position sync,
  - lockout triggers/reset,
  - websocket monitor stability.
- Capture acceptance evidence for each critical flow.

### D) UI/UX polish (web)
Priority: Medium
- Improve dashboard visual hierarchy and status clarity.
- Better error surfacing for auth/trade failures.
- Add explicit disabled-state messaging for risk lockouts.

### E) Code cleanup and alignment
Priority: Medium
- Align instruction/docs references consistently (path naming and location).
- Remove stale legacy references where web replacement is canonical.
- Consolidate duplicated risk/monitor logic where practical.

### F) Test coverage
Priority: Medium
- Add unit tests for:
  - risk control decisions,
  - symbol parsing/ATM logic,
  - snapshot aggregation,
  - order action validation paths.
- Add smoke tests for core API endpoints.

---

## 🔵 Suggested Next Sprint Order
1. Deploy API + worker as services on Azure VM.
2. Add Nginx + TLS and verify external access health.
3. Run full E2E checklist and close high-priority defects.
4. Add minimal automated tests for risk + symbol helpers.
5. Apply UI clarity improvements for risk/automation state.

---

## Open Decisions
- Keep file-based state for production phase, or move to DB for stronger concurrency/audit requirements.
- Keep desktop and web logic duplicated in parts, or refactor into a shared service layer.
