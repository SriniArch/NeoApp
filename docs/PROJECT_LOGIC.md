# NeoApp2: Comprehensive Project Logic Reference

**Created**: Auto-generated for quick reference on file purposes and core logic  
**Last Updated**: Session analysis  
**Purpose**: Enable rapid context-loading for future requests without full repo scans

---

## 1. Project Overview

### Architecture Summary
- **Mode**: Desktop (Tkinter) + Web (FastAPI + Worker)
- **Broker**: Neo API (Kotak Securities) - v2.0.1
- **Deployment**: Local + Azure VM ready
- **State Management**: File-based (JSON snapshots, CSV logs)
- **Threading**: Background monitor loop + WebSocket streams

### Tech Stack
- **Web**: FastAPI 0.116.1, uvicorn, Starlette WebSocket
- **Data**: Pandas, NumPy (PnL, indicators), Python 3.14.2 venv
- **Auth**: API token (header) + local dev bypass
- **CI/CD**: GitHub Actions (scaffolded, not finalized)

### Data Flow
```
Broker (Neo API)
  ↓ [order_report(), positions(), quotes()]
Worker (web/worker/main.py)
  ↓ [poll every 5s, rebuild PnL engine]
State Store (logs/web_monitor_state.json)
  ↓ [atomic JSON writes]
FastAPI (web/backend/main.py)
  ↓ [HTTP/WebSocket endpoints]
Frontend (static/index.html)
  ↓ [real-time dashboard]
Desktop (scalper/neoscalper.py)
  ↓ [Tkinter UI, manual + auto trading]
Telegram Alerts (common/utils.py)
```

---

## 2. Entry Points

### [run.py](run.py)
**Purpose**: Desktop application launcher  
**Execution**: `python run.py`  
**Core Logic**:
```python
import scalper.neoscalper  # Side-effect: Tkinter root window + event loop
```
**Key Flow**:
1. Imports neoscalper module (global state init)
2. Tkinter `mainloop()` blocks and runs UI
3. Background `update_monitor_ui()` runs every 1s in worker thread
4. User clicks BUY/EXIT, which triggers global state updates
5. Monitors poll broker every 1s, update PnL, check auto conditions

**Dependencies**: scalper.neoscalper, sys, os  
**Alternative Entry**: `uvicorn web.backend.main:app --host 0.0.0.0 --port 8000` (web mode)

---

## 3. Web Backend (FastAPI)

### [web/backend/main.py](web/backend/main.py)
**Purpose**: REST API + WebSocket endpoint for web-based trading  
**Execution**: `uvicorn web.backend.main:app --host 0.0.0.0 --port 8000`  
**Runtime Dependencies**: 
- `web/worker/main.py` (worker polling in separate process/thread)
- `logs/web_monitor_state.json` (state file written by worker)

**Key Endpoints**:

#### `GET /health`
- Returns `{"status": "ok"}`
- Liveness probe for K8s/Docker/monitoring

#### `GET /api/system/status` (Protected: `X-API-Key`)
- Returns full system state: `SystemStatusResponse`
- Fields:
  - `ok`: bool
  - `service`: "NeoApp2-Web"
  - `server_ip`: detected IP (via socket)
  - `trading_enabled`: from env `TRADING_ENABLED`
  - `auth_mode`: "header" (X-API-Key)
  - `worker_snapshot_present`: JSON file exists?
  - `worker_healthy`: snapshot age < `WORKER_HEALTH_WINDOW_SECONDS` (30s)
  - `last_worker_update`: ISO timestamp from state file

**Core Logic**:
```python
def startup_event():
    # Detect server IP on startup
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 80))  # Google DNS
    server_ip = sock.getsockname()[0]
    sock.close()
```

#### `GET /api/monitor/snapshot` (Protected)
- Returns rich trading snapshot: `MonitorSnapshotResponse`
- Fields:
  - `timestamp`: ISO
  - `period`: "week" | "day"
  - `trade_stats`: {trades, wins, losses, win_rate, avg_per_trade, largest_win, largest_loss}
  - `pnl`: {gross, net, charges, percentage}
  - `recent_trades`: last 3 completed trades with full details
  - `indicator`: {signal, rsi, momentum, ema, roc, bb_width, sr, sideways, exhausted}
  - `position`: {symbol, quantity, entry_price, current_ltp, unrealized_pnl}
  - `risk`: {buy_disabled, reason, disabled_until, consecutive_losses, cool_off_active}
  - `automation`: {auto_buy_enabled, auto_sell_enabled, last_signal, signal_strength}
  - `source`: "worker" | "error"

**Core Logic**:
```python
# Load snapshot from disk (written by worker)
snapshot = read_snapshot()  # from web/shared/state_store.py
# Verify worker is healthy (snapshot age < 30s)
if snapshot.get('timestamp'):
    age = (now - iso_parse(snapshot['timestamp'])).total_seconds()
    worker_healthy = age < WORKER_HEALTH_WINDOW_SECONDS
```

#### `POST /api/trade/action` (Protected)
- **Request**: `TradeActionRequest` (trading_symbol, lots, action: BUY|EXIT)
- **Response**: `TradeActionResponse` (ok, action, lots, broker_response)
- **Flow**:
  1. Validate auth + trading enabled
  2. Validate request (symbol, lots > 0, action in BUY|EXIT)
  3. Call `execute_market_action()` from web/shared/trading_actions.py
  4. Return broker order response

**Core Logic**:
```python
if not is_trading_enabled():
    return {"ok": False, "error": "Trading disabled"}

result = execute_market_action(
    trading_symbol=req.trading_symbol,
    lots=req.lots,
    action=req.action
)
return TradeActionResponse(ok=result['ok'], broker_response=result)
```

#### `POST /api/symbol/suggest` (Protected)
- **Request**: `SymbolSuggestRequest` (index_name, offset, option_type: CE|PE)
- **Response**: `SymbolSuggestResponse` (suggested_symbol, atm_strike, offset_strike)
- **Flow**:
  1. Fetch live LTP of index (e.g., NIFTY 50)
  2. Calculate ATM strike (round to nearest step: 50 for NIFTY, 100 for BANKNIFTY)
  3. Apply offset (e.g., +0, -1, +1 strikes)
  4. Construct full option symbol (e.g., NIFTY2623750CE)
  5. Return suggestion

**Core Logic**: Delegates to `web/shared/symbol_helpers.py`  
**Key Function**: `suggest_symbol_for_index(index_name, offset, opt_type)`

#### `WS /ws/monitor` (Protected WebSocket)
- **Auth**: Query param `?token=<X-API-Key>`
- **Flow**:
  1. Validate token via `require_ws_token()` dependency
  2. Enter accept loop
  3. Every 2s: read snapshot from disk, send JSON to client
  4. On client disconnect: break loop
- **Message Format**: Same as `GET /api/monitor/snapshot` response
- **Purpose**: Real-time dashboard feed (client refreshes dashboard every 2s)

**Core Logic**:
```python
@app.websocket("/ws/monitor")
async def websocket_monitor(ws: WebSocket, token: str = Depends(require_ws_token)):
    await ws.accept()
    while True:
        snapshot = read_snapshot()
        await ws.send_json(snapshot or {"error": "no snapshot"})
        await asyncio.sleep(2)
```

**Key Functions**:
- `startup_event()` – Detects server IP, logs
- `get_server_ip()` – Socket-based IP detection
- All endpoints use `require_api_key` dependency guard

**Dependencies**: auth.py, models.py, state_store.py, monitor_snapshot.py, trading_actions.py, symbol_helpers.py, common modules

---

### [web/backend/auth.py](web/backend/auth.py)
**Purpose**: API key validation for HTTP headers and WebSocket tokens  
**Config Source**: Environment variable `WEB_API_TOKEN`

**Key Functions**:

#### `get_configured_api_token() → str`
- Reads `WEB_API_TOKEN` from env
- Returns empty string if not set
- No fallback (if empty, raises 503 in require_api_key)

#### `is_local_auth_bypass_enabled() → bool`
- Checks `WEB_ALLOW_LOCAL_NOAUTH` env var
- True if value is "1", "true", "yes", "on" (case-insensitive)
- **DEV ONLY**: Bypasses auth for local testing on 127.0.0.1
- **PRODUCTION**: Must be false or unset

#### `is_trading_enabled() → bool`
- Checks `TRADING_ENABLED` env var
- False by default (safe mode: no live orders)
- True only if explicitly set to "1", "true", "yes", "on"
- If False: `/api/trade/action` returns error immediately

#### `require_api_key(x_api_key: str = Header(...)) → None`
- FastAPI dependency for HTTP endpoints
- Raises 401 if token mismatch
- Raises 503 if token not configured and no bypass
- No return value (raises on failure)

#### `require_ws_token(token: str = Query(...)) → None`
- FastAPI dependency for WebSocket endpoints
- Same logic as `require_api_key` but from query param `?token=`
- Raises 401/503 on invalid/missing token

**Usage Pattern**:
```python
@app.get("/api/system/status", dependencies=[Depends(require_api_key)])
async def system_status():
    # If we reach here, auth passed
```

**Dependencies**: os (env vars), fastapi (Header, Query, HTTPException)

---

### [web/backend/models.py](web/backend/models.py)
**Purpose**: Pydantic request/response data models for type safety and documentation  
**Pattern**: All use `BaseModel` from pydantic

**Key Models**:

#### `TradeActionRequest`
```python
class TradeActionRequest(BaseModel):
    trading_symbol: str       # e.g., "NIFTY2623750CE"
    lots: int                 # >= 1
    action: Literal["BUY", "EXIT"]
```

#### `TradeActionResponse`
```python
class TradeActionResponse(BaseModel):
    ok: bool
    action: str
    trading_symbol: str
    lots: int
    broker_response: dict
    error: Optional[str] = None
```

#### `SystemStatusResponse`
```python
class SystemStatusResponse(BaseModel):
    ok: bool
    service: str                    # "NeoApp2-Web"
    server_ip: str                  # Detected via socket
    trading_enabled: bool
    auth_mode: str                  # "header"
    worker_snapshot_present: bool
    worker_healthy: bool
    last_worker_update: Optional[str]  # ISO datetime
```

#### `SymbolSuggestRequest`
```python
class SymbolSuggestRequest(BaseModel):
    index_name: str             # "NIFTY", "BANKNIFTY", etc.
    offset: int = 0             # Strike offset (-1, 0, +1, etc.)
    option_type: Literal["CE", "PE"] = "CE"
```

#### `SymbolSuggestResponse`
```python
class SymbolSuggestResponse(BaseModel):
    suggested_symbol: str       # e.g., "NIFTY2623750CE"
    atm_strike: int
    offset_strike: int
```

#### `MonitorSnapshotResponse`
```python
class MonitorSnapshotResponse(BaseModel):
    ok: bool
    timestamp: str              # ISO
    period: str                 # "week" | "day"
    trade_stats: Dict
    pnl: Dict
    recent_trades: List[Dict]
    indicator: Dict
    position: Dict
    risk: Dict
    automation: Dict
    source: str
    error: Optional[str] = None
```

**Dependencies**: pydantic, typing (Literal, Optional, List, Dict)

---

### [web/backend/static/index.html](web/backend/static/index.html)
**Purpose**: Single-page app dashboard (React-like, vanilla JS)  
**Delivery**: Served at `GET /` by FastAPI

**Key Sections**:
1. **Header**: Title "NEOAPP2 WEB" + Server IP display
2. **Status Panel**: Trading enabled, worker healthy, last update time
3. **Monitor Panel**: Live PnL, trade stats, week/day filter
4. **Recent Trades**: Table of last 3 completed trades
5. **Indicator Panel**: RSI, momentum, signal status
6. **Quick Trade Buttons**: BUY / EXIT (requires symbol, lots inputs)
7. **Symbol Suggest**: Auto-fill ATM strike for given index + offset
8. **WebSocket Stream**: Real-time refresh every 2s (ws://localhost:8001/ws/monitor?token=...)

**Data Flow**:
```
Load page → Fetch /api/system/status → Display header/status
         → Connect WebSocket /ws/monitor → Auto-refresh every 2s
         → User clicks BUY → POST /api/trade/action
         → Response updates UI
```

**Dependencies**: Vanilla JavaScript, WebSocket API (no framework)

---

## 4. Web Worker (Background Polling)

### [web/worker/main.py](web/worker/main.py)
**Purpose**: Daemon that polls broker, calculates PnL, builds rich monitor snapshot, enforces risk rules  
**Execution**: `python -m web.worker.main` (runs forever until SIGTERM)  
**Runtime**: Runs in separate process from API (can be on same or different machine)

**Main Loop Logic**:
```python
while True:
    try:
        # 1. Login to broker (if needed)
        client = ensure_login()
        
        # 2. Poll broker every 5 seconds (configurable: WEB_POLL_SECONDS)
        response = client.order_report()
        
        # 3. Rebuild PnL engine from scratch (broker = source of truth)
        engine = PositionPnLEngine(initial_capital)
        trades = parse_api_orders(response)
        for t in trades:
            engine.add_trade(t)
        
        # 4. Build rich monitor snapshot
        snapshot = build_monitor_snapshot(engine.completed_trades)
        
        # 5. Add indicator data
        indicator = scalp_manager.get_signal()
        snapshot['indicator'] = indicator
        
        # 6. Check risk conditions (progressive loss, cool-off, etc.)
        if not is_buy_allowed(engine, config):
            snapshot['risk']['buy_disabled'] = True
            snapshot['risk']['reason'] = get_buy_disable_reason()
        
        # 7. Write snapshot atomically
        write_snapshot(snapshot)
        
        # 8. Sleep 5s
        time.sleep(5)
    except Exception as e:
        log(f"Worker error: {e}")
        time.sleep(5)
```

**Key Components**:

#### 1. **Login Retry Loop**
- Calls `get_neo_client()` from common/neo_login.py
- On auth failure: waits 5s, retries
- On success: reuses client for next poll cycle (broker doesn't require constant login)

#### 2. **Order Report Polling**
- Calls `client.order_report()` every 5s (WEB_POLL_SECONDS env var)
- Response format: `{"data": [...list of orders...]}`
- Handles both list and dict-with-data formats

#### 3. **PnL Engine Rebuild**
- Creates fresh `PositionPnLEngine()` every cycle
- Parses all orders via `parse_api_orders()` (from monitor/pnl_engine.py)
- Sorts trades by time
- Adds each trade to engine (FIFO matching for PnL)
- Result: `engine.completed_trades` (closed trades) + `engine.open_trades` (open positions)

#### 4. **Rich Snapshot Building**
- Calls `build_monitor_snapshot(completed_trades)` from web/shared/monitor_snapshot.py
- Aggregates weekly/daily PnL, trade stats, recent trades
- Adds enriched fields:
  - `indicator`: RSI, momentum, signal from scalp_manager
  - `position`: current open position (symbol, qty, entry price, LTP, unrealized PnL)
  - `risk`: buy-disable status, reason, cool-off info
  - `automation`: auto-buy/sell state, last signal, signal strength

#### 5. **Risk State Computation**
- Checks `is_buy_allowed()` from web/shared/risk_controls.py
- Evaluates:
  - Progressive loss lockouts (multiple tiers)
  - Consecutive loss count (3+ losses → cool-off)
  - Max-profit disable (profit target hit)
  - Cool-off period (after exit)
  - Hard stops (daily loss limit)
- Sets `snapshot['risk']` with status, reason, disabled_until timestamp

#### 6. **Atomic State Write**
- Calls `write_snapshot(snapshot)` from web/shared/state_store.py
- Writes to temp file with JSON serialization
- Calls `os.fsync()` to ensure disk flush
- Atomically replaces `logs/web_monitor_state.json` via `os.replace()`
- Guarantees API never reads partial/corrupt state

#### 7. **Error Handling**
- Catches all exceptions in main loop
- Logs error message
- Sleeps 5s
- **Note**: Worker never crashes (infinite loop with broad exception handler)
- API detects worker unhealthy when snapshot age > 30s

**Key Functions Called**:
- `common.neo_login.get_neo_client()` – broker authentication
- `monitor.pnl_engine.parse_api_orders()` – order parsing
- `monitor.pnl_engine.PositionPnLEngine.add_trade()` – FIFO matching
- `indicator.scalping_indicator.LiveScalpingManager.get_signal()` – technical indicators
- `web.shared.monitor_snapshot.build_monitor_snapshot()` – rich data aggregation
- `web.shared.risk_controls.is_buy_allowed()` – lockout evaluation
- `web.shared.state_store.write_snapshot()` – atomic persistence

**Dependencies**: common modules, monitor modules, indicator, web/shared modules, time, logging

**Config Variables**:
- `WEB_POLL_SECONDS` (default 5) – polling cadence
- `WORKER_HEALTH_WINDOW_SECONDS` (default 30) – max snapshot age before unhealthy
- All from `common.config.py`

---

## 5. Web Shared Services

### [web/shared/state_store.py](web/shared/state_store.py)
**Purpose**: Atomic JSON read/write with file locking for multi-process safety

**Key Functions**:

#### `read_snapshot() → dict`
**Flow**:
1. Check env override: `WEB_SNAPSHOT_FILE` (default: `logs/web_monitor_state.json`)
2. Read JSON from file
3. If file missing/corrupt: return empty dict
4. Return parsed JSON

**Exception Handling**:
- File not found → return `{}`
- JSON decode error → log warning, return `{}`
- Permission error → log error, return `{}`

#### `write_snapshot(snapshot: dict) → None`
**Flow**:
1. Get snapshot file path from env (default: `logs/web_monitor_state.json`)
2. Create temp file in same directory (atomicity requires same filesystem)
3. Write snapshot as JSON (with indent=2 for readability)
4. **Critical**: Call `os.fsync()` on temp file descriptor to force disk write
5. Close temp file
6. **Atomic**: `os.replace(temp_path, snapshot_path)` (atomic rename on Unix)

**Pseudocode**:
```python
def write_snapshot(snapshot: dict):
    snapshot_file = os.getenv("WEB_SNAPSHOT_FILE", "logs/web_monitor_state.json")
    snapshot_dir = os.path.dirname(snapshot_file)
    
    # Create temp file in same dir (atomicity)
    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=snapshot_dir,
        delete=False,
        suffix='.json'
    ) as f:
        json.dump(snapshot, f, indent=2)
        os.fsync(f.fileno())  # Force disk write
        temp_path = f.name
    
    # Atomic replace
    os.replace(temp_path, snapshot_file)
```

**Why This Approach**:
- **No locks**: Avoids file locks (work across network filesystems)
- **Atomic**: Rename is atomic on POSIX systems (no partial state visible)
- **Crash-safe**: If process dies mid-write, old state remains intact
- **Multi-process**: API can read stale file while worker writes new one

**Dependencies**: json, os, tempfile, logging

---

### [web/shared/monitor_snapshot.py](web/shared/monitor_snapshot.py)
**Purpose**: Build weekly/day PnL summaries and trade statistics from completed trades

**Key Function**: `build_monitor_snapshot(completed_trades: List[dict]) → dict`

**Flow**:
1. Determine current week window (Monday = start, Friday = end)
2. Filter trades in current week
3. Aggregate stats:
   - Total trades, wins, losses, win rate
   - Average trade PnL, largest win, largest loss
   - Gross/net/charges breakdown
   - Recent 3 trades with full details
4. Return rich snapshot dict

**Week Window Logic**:
```python
def _current_week_window():
    today = datetime.now()
    # If today is Saturday/Sunday, use previous week
    if today.weekday() >= 5:
        days_back = today.weekday() - 4
    else:
        days_back = today.weekday()
    
    week_start = today - timedelta(days=days_back)
    week_end = today
    return week_start, week_end
```

**Trade Filtering**:
```python
def _filter_weekday_trades(trades):
    week_start, week_end = _current_week_window()
    # Filter trades with trade_date >= week_start
    return [t for t in trades if t.get('trade_date') >= week_start]
```

**Output Schema**:
```python
{
    'timestamp': '2026-02-27T14:30:00Z',
    'period': 'week',
    'trade_stats': {
        'total_trades': 12,
        'wins': 8,
        'losses': 4,
        'win_rate': 66.7,
        'avg_per_trade': 125.5,
        'largest_win': 500.0,
        'largest_loss': -300.0
    },
    'pnl': {
        'gross': 1506.0,
        'net': 1200.0,
        'charges': 306.0,
        'percentage': 5.2
    },
    'recent_trades': [
        {
            'symbol': 'NIFTY2623750CE',
            'quantity': 1,
            'buy_price': 120.0,
            'sell_price': 125.5,
            'buy_time': '14:15:00',
            'sell_time': '14:20:00',
            'net_pnl': 500.0,
            'charges': 50.0
        },
        ...
    ]
}
```

**Dependencies**: datetime, List, Dict, typing

---

### [web/shared/trading_actions.py](web/shared/trading_actions.py)
**Purpose**: Execute market orders (BUY/SELL) with position-safe checks and completion verification

**Key Function**: `execute_market_action(trading_symbol: str, lots: int, action: str) → dict`

**Flow**:
1. **Validation**:
   - Symbol exists (lookup via scrip_master)
   - Lots > 0
   - Action in BUY|EXIT

2. **Position Check** (if action == BUY):
   - Fetch current positions via `client.positions()`
   - Check if any open F&O position exists
   - If yes: return error "Position already open"
   - If no: proceed

3. **Token Lookup**:
   - Call `find_token_for_trading_symbol(trading_symbol)` from common/scrip_master.py
   - Get broker instrument token (cached, O(1) lookup)

4. **Place Order**:
   - Determine side: action == "BUY" → "BUY", action == "EXIT" → "SELL"
   - Call `place_market_order(token, lots, side, trading_symbol)` from common/orders.py
   - Receive response: `{"nOrdNo": "order_id", ...}` or error dict

5. **Completion Verification** (Retry Loop):
   - Loop up to 10 times:
     - Sleep 1s
     - Fetch order report via `client.order_report()`
     - Parse trades via `parse_api_orders()`
     - Check if any trade has:
       - `symbol == trading_symbol`
       - `qty == lots`
       - `status == "COMPLETE"` or similar terminal state
     - If found: return success
   - After 10 retries (10s timeout): return error "Order not confirmed in time"

6. **Return Response**:
   ```python
   {
       "ok": True|False,
       "action": "BUY"|"EXIT",
       "trading_symbol": "NIFTY2623750CE",
       "lots": 1,
       "broker_response": {...},
       "error": "..." (if not ok)
   }
   ```

**Why Position-Safe**:
- Guard prevents multiple open positions
- Broker API doesn't auto-close old positions on new BUY
- Manual check ensures only 1 derivative position at a time

**Why Completion Verification**:
- Order response doesn't guarantee execution
- Need to verify order actually filled
- Retry loop with timeout prevents hanging

**Dependencies**: common/orders, common/scrip_master, monitor/pnl_engine

---

### [web/shared/symbol_helpers.py](web/shared/symbol_helpers.py)
**Purpose**: Parse option symbols, calculate ATM strikes, suggest option symbols

**Key Functions**:

#### `parse_symbol_parts(symbol: str) → dict`
**Purpose**: Extract components from option symbol string  
**Format Supported**: `NIFTY26217{STRIKE}CE` or similar

**Regex Pattern**:
```regex
^([A-Z]+)(\d{2})(\d{2})(\d+)(CE|PE)$
```

**Groups**:
1. Index name (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, etc.)
2. Year (26 = 2026)
3. Expiry (17 = 17th, first digit of day, second digit is month shorthand)
4. Strike price (numerical)
5. Option type (CE or PE)

**Fallback**: Try to detect 5-digit and 6-digit expiry formats if standard fails

**Return**:
```python
{
    'index_name': 'NIFTY',
    'expiry': '2026-02-17',  # Parsed and formatted
    'strike': 22750,
    'option_type': 'CE'
}
```

#### `get_atm_strike(index_ltp: float, strike_step: int) → int`
**Purpose**: Round live index price to nearest strike  
**Logic**:
```python
# Round to nearest strike_step (e.g., 50 for NIFTY, 100 for BANKNIFTY)
atm_strike = round(index_ltp / strike_step) * strike_step
return atm_strike
```

**Example**:
- Index LTP: 23,487.5, Strike step: 50
- ATM: 23,500

#### `suggest_symbol_for_index(index_name: str, offset: int, opt_type: str) → str`
**Purpose**: Build full option symbol (ATM + offset)  
**Flow**:
1. Fetch live LTP of index (e.g., NIFTY via quotes API)
2. Get strike step for index (50 for NIFTY, 100 for BANKNIFTY, etc.)
3. Calculate ATM: `get_atm_strike(ltp, step)`
4. Apply offset: `strike = atm + (offset * step)`
5. Get next expiry date from config
6. Construct symbol: `{index}{expiry}{strike}{opt_type}`
7. Return symbol string

**Example**:
- Index: NIFTY, LTP: 23,487.5, offset: +1, opt_type: CE
- ATM: 23,500
- Offset strike: 23,550 (23,500 + 1×50)
- Expiry: 2026-02-17 (next Thursday)
- Result: `NIFTY2621755CE`

**Dependencies**: re (regex), common/config (expiry, strike step), common/orders (exchange detection)

---

### [web/shared/risk_controls.py](web/shared/risk_controls.py)
**Purpose**: Enforce buy-disable lockouts (progressive loss, cool-off, consecutive losses, max-profit)  
**State File**: `buy_disabled.json`

**Key Function**: `is_buy_allowed(pnl_engine: PositionPnLEngine, config) → bool`

**Lockout Conditions** (ALL must pass for BUY):

#### 1. **Progressive Loss Lockout**
**Logic**:
```python
cumulative_loss = abs(min(pnl_engine.get_current_capital() - initial_capital, 0))

# Check each tier in PROGRESSIVE_LOSS_CONFIG
for tier in config.PROGRESSIVE_LOSS_CONFIG:
    if cumulative_loss >= tier['loss_threshold']:
        disabled_minutes = tier['disabled_minutes']
        # Check if lockout expired
        if not has_lockout_expired(disabled_minutes):
            return False, f"Progressive loss: {cumulative_loss} >= {tier['loss_threshold']}"
```

**Config Example** (from common/config.py):
```python
PROGRESSIVE_LOSS_CONFIG = [
    {"loss_threshold": 500, "disabled_minutes": 5},
    {"loss_threshold": 1000, "disabled_minutes": 10},
    {"loss_threshold": 2500, "disabled_minutes": 240}  # Hard stop for rest of day
]
```

#### 2. **Cool-Off Period**
**Logic**:
```python
if last_exit_time > 0:
    time_since_exit = time.time() - last_exit_time
    if time_since_exit < config.COOL_OFF_PERIOD:  # e.g., 10 seconds
        return False, f"Cool-off active: {remaining_seconds}s remaining"
```

#### 3. **Consecutive Loss Count**
**Logic**:
```python
consecutive_losses = count_recent_losses(completed_trades, window=3)
if consecutive_losses >= 3:
    # Enable cool-off period (usually 10 minutes)
    return False, f"3 consecutive losses: disabled for cool-off"
```

#### 4. **Max-Profit Disable**
**Logic**:
```python
# If daily profit >= MAX_PROFIT_DISABLE_THRESHOLD, block buys
if pnl_engine.get_current_capital() - initial_capital >= config.BUY_DISABLE_MAX_PROFIT:
    return False, "Profit target reached: max profit disable"
```

#### 5. **Hard Stop (Daily Loss Limit)**
**Logic**:
```python
# Count losses in last 24 hours
daily_losses = count_losses_since(completed_trades, hours=24)
if daily_losses >= config.BUY_DISABLE_DAILY_LOSS_LIMIT:  # e.g., 50 losses
    return False, "Hard stop: daily loss limit exceeded"
```

**State File** (`buy_disabled.json`):
```json
{
    "disabled_until": "2026-02-27T14:35:30Z",
    "last_trade_id": "123456",
    "date": "2026-02-27",
    "highest_threshold": 1000,
    "reason": "Progressive loss: 1250 >= 1000"
}
```

**State Persistence**:
- Written by `apply_lockout()` when lockout triggered
- Read by API/desktop on each buy attempt
- Cleared when `last_trade_id` improves (loss recovery)

**Recovery Logic**:
```python
def check_recovery():
    lockout = read_lockout()
    if not lockout:
        return True  # No lockout, proceed
    
    # Check if we've recovered (PnL improved since lockout)
    last_trade_pnl = get_trade_pnl_by_id(lockout['last_trade_id'])
    if last_trade_pnl > 0:
        clear_lockout()  # Clear and allow buys
        return True
    
    return False
```

**Dependencies**: common/config (thresholds, periods), json (state I/O), time, datetime

---

## 6. Common Modules (Shared Desktop & Web)

### [common/config.py](common/config.py)
**Purpose**: Load env vars, define risk thresholds, trading defaults, technical indicator parameters

**Key Configuration Categories**:

#### **Broker Authentication** (from .env)
```python
CONSUMER_KEY = os.getenv("CONSUMER_KEY", "")
MOBILE = os.getenv("MOBILE", "")
UCC = os.getenv("UCC", "")
MPIN = os.getenv("MPIN", "")
TOTP_SECRET = os.getenv("TOTP_SECRET", "")
```

#### **Trading Parameters**
```python
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "50000"))
CAPITAL_TOPUP = float(os.getenv("CAPITAL_TOPUP", "0"))
PNL_RESET_DATE = os.getenv("PNL_RESET_DATE", "2024-01-01")  # Reset capital tracking
COOL_OFF_PERIOD = int(os.getenv("COOL_OFF_PERIOD", "10"))   # Seconds between trades
```

#### **Risk Controls** (Buy-Disable Lockouts)
```python
# Progressive loss config (JSON, can be remote)
PROGRESSIVE_LOSS_CONFIG = fetch_remote_json(
    os.getenv("REMOTE_PROGRESSIVE_LOSS_URL", ""),
    [
        {"loss_threshold": 500, "disabled_minutes": 5},
        {"loss_threshold": 1000, "disabled_minutes": 10},
        {"loss_threshold": 2500, "disabled_minutes": 240}
    ]
)

BUY_DISABLE_MAX_LOSS = fetch_remote_config(
    os.getenv("REMOTE_MAX_LOSS_URL", ""),
    2500  # Hard stop at 2500 cumulative loss
)
BUY_DISABLE_MAX_PROFIT = 5000  # Stop after 5000 profit
BUY_DISABLE_DAILY_LOSS_LIMIT = 50  # Max 50 losses per day
```

#### **Scalping Strategy** (Technical Indicators)
```python
# RSI Scalping thresholds
RSIM_RSI_UP = 70           # Bullish signal: RSI > 70
RSIM_RSI_DOWN = 30         # Bearish signal: RSI < 30
RSIM_SUSTAIN_TICKS = 5     # Confirm signal for 5 ticks

# Bollinger Band width (consolidation detection)
BB_EXPANSION_THRESHOLD = 0.02  # 2% width increase = expansion pulse
BB_CONTRACTION_THRESHOLD = 0.005  # 0.5% = consolidation (sideways)
```

#### **Web/Remote Configuration**
```python
# Dynamic config URLs (updated every 5 mins)
REMOTE_CONFIG_URL = os.getenv("REMOTE_CONFIG_URL", "")
REMOTE_PROGRESSIVE_LOSS_URL = os.getenv("REMOTE_PROGRESSIVE_LOSS_URL", "")
WEB_POLL_SECONDS = int(os.getenv("WEB_POLL_SECONDS", "5"))
WORKER_HEALTH_WINDOW_SECONDS = int(os.getenv("WORKER_HEALTH_WINDOW_SECONDS", "30"))
```

#### **Telegram Alerts** (Optional)
```python
TELEGRAM_BOTS = {}  # Populated by fetch_remote_json if URL set
# Format: {"bot_id": {"token": "...", "chat_ids": [...]}}
```

**Key Functions**:

#### `get_next_expiry() → str`
- Returns next Thursday's date (NIFTY/BANKNIFTY expiry)
- Format: "2026-02-17"
- Used for symbol construction

#### `detect_strike_step(symbol) → int`
- Returns step size for symbol's strike
- 50 for NIFTY, 100 for BANKNIFTY, 5 for FINNIFTY, etc.
- Used for ATM calculation

**Dependencies**: os, json, dotenv, common/utils (fetch_remote_*)

---

### [common/neo_login.py](common/neo_login.py)
**Purpose**: Authenticate to Neo API using TOTP + MPIN, return authenticated client  
**Singleton Pattern**: Single active client across app lifetime

**Key Function**: `get_neo_client() → NeoAPI`

**Authentication Flow**:
1. Read broker credentials from env: CONSUMER_KEY, MOBILE, UCC, MPIN, TOTP_SECRET
2. Create NeoAPI client instance
3. Call `client.login()` with credentials:
   - `consumer_key`, `mobile`, `mpin`
   - TOTP token generated from `TOTP_SECRET` (time-based)
4. Check response:
   - If `response.get("error")` or `response.get("status") == "error"`: raise Exception
   - If successful: return client
5. **Caching**: Store client in module-level variable, return same instance on subsequent calls
6. **Retry Logic**: Raise exception on auth failure (caller handles retry)

**Error Handling**:
```python
def get_neo_client():
    global _client_instance
    
    if _client_instance:
        return _client_instance
    
    try:
        client = NeoAPI(...)
        resp = client.login(...)
        
        if resp.get("error"):
            raise Exception(f"Login error: {resp['error']}")
        if resp.get("status") == "error":
            raise Exception(f"Login failed: {resp.get('message')}")
        
        _client_instance = client
        return client
    except Exception as e:
        raise Exception(f"Neo login failed: {e}")
```

**TOTP Generation**:
```python
import pyotp
totp = pyotp.TOTP(os.getenv("TOTP_SECRET"))
totp_token = totp.now()  # 6-digit time-based code
```

**Note**: `access_token` may not be returned in response (Neo API stores internally). This is normal; client object is sufficient for subsequent API calls.

**Dependencies**: neo_api_client.NeoAPI, pyotp, os, dotenv, logging

---

### [common/orders.py](common/orders.py)
**Purpose**: Execute market orders, detect exchange/symbol metadata, manage broker client singleton

**Key Functions**:

#### `get_client() → NeoAPI`
- Returns cached broker client (from neo_login.py)
- If not cached: calls `ensure_login()` to initialize

#### `ensure_login() → NeoAPI`
- Calls `get_neo_client()` from neo_login.py
- Returns authenticated client or raises exception

#### `detect_exchange_segment(trading_symbol: str) → str`
**Purpose**: Determine broker exchange code  
**Logic**:
```python
# Check if symbol in NSE F&O master CSV
if trading_symbol in nse_fo_master:
    return "nse_fo"

# Check if symbol in BSE F&O master CSV
if trading_symbol in bse_fo_master:
    return "bse_fo"

# Fallback (should not happen if CSVs up-to-date)
raise Exception(f"Symbol {trading_symbol} not found in masters")
```

**Return Values**: `"nse_fo"` or `"bse_fo"` (lowercase, broker-specific codes)

#### `detect_strike_step(trading_symbol: str) → int`
**Purpose**: Get step size for ATM calculation  
**Logic**:
```python
# Extract index name from symbol (e.g., NIFTY from NIFTY2623750CE)
index_name = parse_index_from_symbol(trading_symbol)

# Return step based on index
steps = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 5,
    "MIDCPNIFTY": 5,
    "SENSEX": 100,
    "BANKEX": 100
}
return steps.get(index_name, 50)  # Default 50
```

#### `place_market_order(token: int, lots: int, side: str, trading_symbol: str) → dict`
**Purpose**: Execute market order via broker API  
**Parameters**:
- `token`: Broker instrument token (from scrip_master)
- `lots`: Number of lots to trade
- `side`: "BUY" or "SELL"
- `trading_symbol`: Human-readable symbol (for logging)

**Flow**:
1. Get broker client
2. Determine lot size from scrip_master
3. Calculate quantity: `quantity = lots * lot_size`
4. Determine exchange from `detect_exchange_segment()`
5. Call `client.place_order()` with mapped parameters:
   ```python
   response = client.place_order(
       instrument_token=token,
       order_type="MARKET",
       quantity=quantity,
       side=side,  # "BUY" or "SELL"
       exchange_segment=exchange_segment,  # "nse_fo" or "bse_fo"
       order_validity="IOC"  # Immediate-or-Cancel
   )
   ```
6. Return response dict: `{"nOrdNo": "order_id", ...}` or `{"error": "..."}`

**Error Handling**:
- Retries token lookup if not found (waits 2s, tries again)
- Raises exception if order placement fails
- Returns broker response (caller responsible for validation)

**Dependencies**: common/scrip_master, common/config, common/utils, neo_api_client

---

### [common/scrip_master.py](common/scrip_master.py)
**Purpose**: Load and cache scrip master CSV files (NSE/BSE), provide fast token lookup

**Key Data**:
- `nse_fo.csv` – NSE F&O symbol → token mapping
- `bse_fo.csv` – BSE F&O symbol → token mapping
- Columns: `TradingSymbol`, `Token`, `LotSize`, `TickSize`, ...

**Key Functions**:

#### `load_scrip_master_csv()`
**Flow**:
1. Check if CSVs exist locally
2. If stale (> 7 days old): download from broker via `client.scrip_master()`
3. Load CSV via pandas
4. Build token cache: `{symbol: token}` (O(1) lookup)
5. Cache in module-level `_token_cache` and `_scrip_master_df`

**Caching**:
```python
_token_cache = {}  # {symbol: token}
_scrip_master_df = None  # Full dataframe

def load_scrip_master_csv():
    global _token_cache, _scrip_master_df
    
    # Load NSE + BSE CSVs
    nse_df = pd.read_csv("nse_fo.csv")
    bse_df = pd.read_csv("bse_fo.csv")
    
    # Merge
    _scrip_master_df = pd.concat([nse_df, bse_df])
    
    # Build token cache
    for _, row in _scrip_master_df.iterrows():
        symbol = row['TradingSymbol'].upper()
        token = int(row['Token'])
        _token_cache[symbol] = token
```

#### `find_token_for_trading_symbol(trading_symbol: str) → int`
**Purpose**: O(1) lookup of broker token  
**Flow**:
1. Ensure scrip master loaded
2. Lookup `_token_cache[symbol]` (case-insensitive)
3. If not found: raise exception
4. Return token

#### `get_lot_size_from_scrip_master(trading_symbol: str) → int`
**Purpose**: Get lot size for position sizing  
**Flow**:
1. Lookup symbol in scrip master dataframe
2. Return `LotSize` column value
3. If not found: raise exception

**Auto-Download**:
```python
def refresh_scrip_master_if_stale():
    csv_path = "nse_fo.csv"
    if os.path.exists(csv_path):
        age_days = (time.time() - os.path.getmtime(csv_path)) / 86400
        if age_days < 7:
            return  # Fresh
    
    # Download from broker
    client = get_neo_client()
    master_data = client.scrip_master()
    # Parse and save to CSV
```

**Dependencies**: pandas, os, requests, common/neo_login, common/utils

---

### [common/utils.py](common/utils.py)
**Purpose**: Logging, Telegram notifications, remote config fetches, cross-platform paths

**Key Functions**:

#### `run_bg(fn, *args, **kw)`
**Purpose**: Run function in background daemon thread  
**Flow**:
```python
def run_bg(fn, *args, **kw):
    thread = threading.Thread(target=fn, args=args, kwargs=kw, daemon=True)
    thread.start()
    return thread
```

#### `log_with_callback(log_cb, msg: str)`
**Purpose**: Log message to callback (UI or console)  
**Usage**:
```python
def my_log_callback(msg):
    print(f"[LOG] {msg}")
    log_box.insert(tk.END, msg + "\n")

log_with_callback(my_log_callback, "Trade executed")
```

**If callback is None**: Uses `print(msg)`

#### `fetch_remote_config(url: str, default) → int`
**Purpose**: Fetch single integer value from remote URL with fallback  
**Flow**:
1. GET request to `url` with 5s timeout
2. Parse response as JSON
3. Extract `.get("value")` or use whole response as int
4. Return int, or `default` if error

**Example**:
```python
max_loss = fetch_remote_config("https://config.example.com/max_loss", 2500)
# Returns 2500 if config unavailable
```

#### `fetch_remote_json(url: str, default: dict) → dict`
**Purpose**: Fetch JSON object from remote URL with fallback  
**Flow**:
1. GET request with 5s timeout
2. Parse response as JSON dict
3. Return dict, or `default` if error

#### `send_telegram_msg(message: str)`
**Purpose**: Broadcast message to all configured Telegram bots  
**Flow**:
1. Load bot list from config (or remote)
2. For each bot:
   - POST to Telegram API: `sendMessage` endpoint
   - Send message to all chat IDs
3. Log success/failure
4. **Web Mode**: Skipped (no Telegram in web)

**Bot Config Format**:
```json
{
    "bot_token_1": {
        "token": "123456:ABC...",
        "chat_ids": ["-123456789", "-987654321"]
    }
}
```

#### `get_resource_path(relative_path: str) → str`
**Purpose**: PyInstaller-compatible path resolution  
**Flow**:
1. Check if running as PyInstaller bundle (sys._MEIPASS)
2. If yes: return path relative to bundle root
3. If no: return path relative to script directory

**Usage**:
```python
icon_path = get_resource_path("assets/scalper2.png")
# Returns "/path/to/app.dist/assets/scalper2.png" in executable
# Returns "assets/scalper2.png" in development
```

**Dependencies**: threading, urllib, json, os, sys, logging

---

## 7. Monitor & PnL Engine

### [monitor/pnl_engine.py](monitor/pnl_engine.py)
**Purpose**: FIFO trade matching, PnL calculation with realistic Indian charges

**Key Classes**:

#### `Trade` (dataclass)
```python
@dataclass
class Trade:
    symbol: str         # e.g., NIFTY2623750CE
    side: str          # "B" (buy) or "S" (sell)
    qty: int           # Quantity
    price: float       # Execution price
    time: datetime     # Execution time
    product: str       # "MIS" or "CNC" or other
    segment: str       # "nse_fo" or "bse_fo"
    order_id: str      # Broker order ID
```

#### `ChargesCalculator`
**Purpose**: Calculate realistic Indian trading charges  
**Charge Components**:
1. **Brokerage**: 0.02% (20 paise per 100)
2. **Exchange Fee**: 0.00167% (varies by segment)
3. **SEBI Charge**: 0.000001% (regulatory fee)
4. **GST**: 18% on (brokerage + exchange fee)
5. **STT** (Securities Transaction Tax):
   - Seller side: 0.01% (buy-back: 0.0001%)
6. **Stamp Duty**: Rare, ~0.003%

**Method**: `calculate(buy_price, sell_price, qty) → dict`
```python
def calculate(self, buy_price, sell_price, qty):
    buy_value = buy_price * qty
    sell_value = sell_price * qty
    
    # Broker charges (simplified: 0.02% each side)
    broker_buy = buy_value * 0.0002
    broker_sell = sell_value * 0.0002
    
    # STT (0.01% on sell)
    stt = sell_value * 0.0001
    
    # Exchange + SEBI + GST
    exchange = (buy_value + sell_value) * 0.0000167
    sebi = (buy_value + sell_value) * 0.000001
    gst = (broker_buy + broker_sell + exchange) * 0.18
    
    total_charges = broker_buy + broker_sell + stt + exchange + sebi + gst
    
    return {
        "broker": broker_buy + broker_sell,
        "stt": stt,
        "exchange": exchange,
        "sebi": sebi,
        "gst": gst,
        "total": total_charges
    }
```

#### `PositionPnLEngine`
**Purpose**: Track open positions and completed trades (FIFO matching)  
**State**:
```python
class PositionPnLEngine:
    open_trades: Dict[str, deque]        # {symbol: deque of buy orders}
    completed_trades: List[dict]         # Closed trades with PnL
    initial_capital: float
    charges_calculator: ChargesCalculator
```

**Key Methods**:

##### `add_trade(trade: Trade) → None`
**Flow**:
1. If `trade.side == "B"` (buy):
   - Append to `open_trades[symbol]` deque
2. If `trade.side == "S"` (sell):
   - Dequeue buy order from front (FIFO)
   - Calculate PnL: `(sell_price - buy_price) * qty - charges`
   - Calculate charges via `ChargesCalculator.calculate()`
   - Append to `completed_trades` with:
     - `symbol`, `qty`, `buy_price`, `sell_price`, `gross_pnl`, `charges`, `net_pnl`
     - `buy_time`, `sell_time`, `trade_date`
     - Enriched fields from desktop: `entry_sig`, `exit_reason`, `rsi`, `momentum`, etc.

**Example**:
```
Buy NIFTY @ 120.0, qty 1
Open trades: {NIFTY: [120.0]}

Sell NIFTY @ 125.0, qty 1
Charges: 50.0
Gross PnL: (125.0 - 120.0) * 1 = 5.0
Net PnL: 5.0 - 50.0 = -45.0 (net loss due to charges)

Completed trades: [{symbol: NIFTY, buy_price: 120, sell_price: 125, net_pnl: -45, ...}]
```

##### `get_current_capital() → float`
- Returns: `initial_capital + sum(completed_trades[*].net_pnl)`
- Represents total capital after all completed trades

##### `get_pnl_percentage() → float`
- Returns: `(get_current_capital() - initial_capital) / initial_capital * 100`
- Daily % return

##### `get_open_position_pnl(symbol, current_ltp) → dict`
- Calculates unrealized PnL for open position
- Used for "position monitor" display

#### `parse_api_orders(response: dict) → List[Trade]`
**Purpose**: Parse broker order report into Trade objects  
**Input Format** (Neo API):
```python
{
    "data": [
        {
            "nOrdNo": "123456",
            "trdSym": "NIFTY2623750CE",
            "side": "BUY",  # or "SELL"
            "qty": 1,
            "flQtyRem": 0,  # Filled qty remaining (0 = fully filled)
            "exch": "NSE_FO",
            "prcType": "MKT",
            "ordStatus": "COMPLETE",
            "executionPrice": 120.5,
            "executionQty": 1,
            "executionTime": "2026-02-27 14:15:30",
            ...
        }
    ]
}
```

**Parsing Logic**:
1. Filter orders where `flQtyRem == 0` (fully filled)
2. Map each order to Trade object:
   - `symbol = trdSym.upper()`
   - `side = "B"` if order.side == "BUY" else "S"`
   - `qty = executionQty`
   - `price = executionPrice`
   - `time = parse_datetime(executionTime)`
3. Return list sorted by time

**Field Variations** (handles both NSE/BSE):
- Price: `executionPrice`, `prc`, `lastRate`
- Qty: `executionQty`, `qty`, `filledQty`
- Time: `executionTime`, `time`, `transactionTime`

**Dependencies**: datetime, dataclasses, typing, collections

---

### [monitor/neomonitor.py](monitor/neomonitor.py)
**Purpose**: Legacy standalone monitor loop (still functional, retained for reference)

**Main Loop** (Runs forever):
```python
while True:
    # 1. Fetch latest orders from broker
    response = client.order_report()
    
    # 2. Rebuild PnL engine fresh (broker = source of truth)
    engine = PositionPnLEngine(initial_capital=INITIAL_CAPITAL)
    trades = parse_api_orders(response["data"])
    trades.sort(key=lambda x: x.time)
    for trade in trades:
        engine.add_trade(trade)
    
    # 3. Filter to current week (Mon-Fri)
    weekly_trades = filter_current_week_trades(engine.completed_trades)
    
    # 4. Calculate stats
    gross_pnl = sum(t['gross_pnl'] for t in weekly_trades)
    net_pnl = sum(t['net_pnl'] for t in weekly_trades)
    wins = len([t for t in weekly_trades if t['net_pnl'] > 0])
    losses = len([t for t in weekly_trades if t['net_pnl'] < 0])
    
    # 5. Print to terminal (formatted table)
    print_monitor_stats(engine, weekly_trades)
    
    # 6. Refresh remote config (every 5 mins)
    # ...
    
    # 7. Sleep 10s
    time.sleep(10)
```

**Key Output Functions**:
- `print_last_5_trades_inline()` – Recent trades in tabular format
- `trade_statistics()` – Win/loss summary
- `color_pnl()` – ANSI color codes for terminal

**Note**: Superseded by web worker (web/worker/main.py), which has same logic but persists state to JSON for API consumption.

**Dependencies**: common modules, monitor.pnl_engine, time, json, sys

---

## 8. Technical Indicators & Strategy Engine

### [indicator/scalping_indicator.py](indicator/scalping_indicator.py)
**Purpose**: Technical indicators (RSI, ROC, EMA, Bollinger Bands) and strategy signal generators

**Key Classes**:

#### `ScalpingIndicator` (Static Methods)
Utility class for computing indicators from price series

##### `calculate_rsi(prices: List, period=14) → float`
**Formula**: RSI = 100 - (100 / (1 + RS)), where RS = avg_gain / avg_loss
**Range**: 0-100
**Interpretation**:
- RSI > 70 → Overbought (potential bearish reversal)
- RSI < 30 → Oversold (potential bullish reversal)

##### `calculate_roc(prices: List, period=12) → float`
**Formula**: ROC = ((Close - Close[12 periods ago]) / Close[12 periods ago]) * 100
**Interpretation**:
- ROC > 0 → Uptrend (momentum positive)
- ROC < 0 → Downtrend (momentum negative)
- ROC magnitude → Momentum strength

##### `calculate_ema(prices: List, period=20) → float`
**Formula**: EMA = Price × multiplier + EMA[prev] × (1 - multiplier)
- multiplier = 2 / (period + 1)
**Interpretation**:
- Price > EMA → Uptrend
- Price < EMA → Downtrend

##### `calculate_bollinger_bands(prices: List, period=20, std_dev=2) → dict`
**Formula**:
- Middle: SMA(20)
- Upper: Middle + 2×StdDev
- Lower: Middle - 2×StdDev
**Interpretation**:
- Price at upper band → Overbought
- Price at lower band → Oversold
- Band width → Volatility (narrow = low, wide = high)

##### `calculate_support_resistance(prices: List, window=20) → dict`
**Purpose**: Detect recent support (local minima) and resistance (local maxima)  
**Logic**:
- Find lowest price in last 20 candles → Support
- Find highest price in last 20 candles → Resistance

#### `BaseStrategy` (Abstract)
```python
class BaseStrategy(ABC):
    @abstractmethod
    def get_signal(self) -> dict:
        """
        Return: {
            'signal': 'BULLISH'|'BEARISH'|'NEUTRAL'|'EXHAUSTED'|'SIDEWAYS',
            'rsi': float,
            'momentum': float,
            'ema': float,
            'roc': float,
            'bb_width': float,
            'sr': dict,
            'strength': float (0-100)
        }
        """
```

#### `ScalpingStrategyV1(BaseStrategy)`
**Signals**:
- **BULLISH**: Price > EMA20, ROC > 0, uptrend confirmed, + BB expansion pulse
- **BEARISH**: Price < EMA20, ROC < 0, downtrend confirmed
- **EXHAUSTED**: |ROC| exceeds ceiling (no trade signal)
- **SIDEWAYS**: BB width < floor (consolidation, low volatility)
- **NEUTRAL**: None of above

**Pulse Detection** (BB Expansion):
```python
# Calculate band width: (upper - lower) / middle
bb_width = (upper - lower) / middle

# Check if width expanding (vs previous)
if bb_width > prev_bb_width * 1.02:  # 2% expansion
    pulse = True  # Strong directional move
```

**Example Signal**:
```python
{
    'signal': 'BULLISH',
    'rsi': 72.5,
    'momentum': 2.3,  # +2.3% ROC
    'ema': 23400.0,
    'roc': 2.3,
    'bb_width': 0.045,
    'sr': {'support': 23350, 'resistance': 23500},
    'strength': 85  # Confidence %
}
```

#### `RSIMomentumStrategy(BaseStrategy)`
**Purpose**: Trade on RSI + Momentum sustain  
**Entry Logic**:
- RSI crosses above 70 → Bullish signal
- RSI crosses below 30 → Bearish signal
- Momentum > 5% sustained for N ticks → Confirmation
- Result: Return signal + strength

**Sustain Tick Logic**:
```python
if rsi > 70 and not was_overbought:
    sustain_ticks = 0
if rsi > 70:
    sustain_ticks += 1
    if sustain_ticks >= RSIM_SUSTAIN_TICKS:
        return signal='BULLISH'
```

#### `LiveScalpingManager`
**Purpose**: Accumulate LTP data, call strategy on each new candle

**Key Methods**:

##### `add_ltp(price: float, symbol: str)`
- Append price to price series
- Track timestamp
- If 1-minute candle closed: call strategy, save to CSV

##### `get_signal() → dict`
- Returns latest signal from strategy
- Calculates indicators on current 20-candle window

**State Persistence**:
- Saves signals to `logs/{symbol}_{date}_indicators.csv`
- Columns: timestamp, close, rsi, roc, ema, signal, strength

**Dependencies**: pandas, numpy, common/config (indicator params), csv, datetime

---

## 9. Desktop Scalper UI (Tkinter)

### [scalper/neoscalper.py](scalper/neoscalper.py)
**Purpose**: Main Tkinter UI application with manual/auto trading, live monitor, strategy display  
**Size**: ~2200 lines of integrated UI + trading logic  
**Execution**: `python run.py`

**Global State**:
```python
buy_active = False              # ✅ Position open
buy_pending = False             # ⏳ BUY order being placed
exit_pending = False            # ⌛ EXIT order being placed
active_symbol = ""              # Which symbol we bought
last_buy_price = 0.0           # Entry price
max_price_seen = 0.0           # Peak price for trailing SL
active_trade_metadata = {}     # Indicators at entry/exit
last_exit_time = 0             # Cooldown tracking
last_exit_reason = ""
last_mom_alert_time = 0
buy_disabled = False           # Lockout status
auto_buy = False               # Auto entry enabled
auto_sell = False              # Auto exit enabled
scalp_manager = LiveScalpingManager()
pnl_engine = PositionPnLEngine()
```

**UI Layout**:
- **Left Panel** (Trading Controls):
  - Log box (scrollable text)
  - Symbol entry / history dropdown
  - Strike ±/auto buttons
  - CE/PE toggle
  - Lot dropdown
  - BUY / EXIT buttons
  - AUTO BUY / AUTO SELL toggles
  - Status labels (position, lockout, momentum)

- **Right Panel** (Monitor):
  - PnL stats (week/day, trades, W/L, PnL, charges)
  - Recent trades (last 5 with entry/exit times, prices)
  - Indicator display (RSI, momentum, signal, EMA, ROC, BB)
  - Strategy status (bullish/bearish/sideways)

**Background Loop** (`update_monitor_ui()`):
Runs every 1s in daemon thread
```python
def update_monitor_ui():
    # 1. Fetch positions (check if buy_active is real)
    positions = client.positions()
    has_open_pos = any(...)
    
    # 2. Fetch orders (rebuild PnL engine)
    orders = client.order_report()
    engine.add_trade(trade) for each order
    
    # 3. Calculate indicators
    indicator_data = scalp_manager.get_signal()
    sig = indicator_data['signal']
    
    # 4. Check auto-buy condition
    if auto_buy and not buy_active and sig == 'BULLISH':
        if is_buy_allowed():
            do_buy(trade_type="Auto")
    
    # 5. Check auto-exit condition
    if auto_sell and buy_active:
        if cur_price >= target_price:
            do_exit(reason="Target")
        elif cur_price <= sl_price:
            do_exit(reason="SL")
        elif cur_price <= max_price_seen - trailing_sl:
            do_exit(reason="Trailing SL")
    
    # 6. Render monitor UI
    root.after(0, lambda: render_monitor_display(...))
    
    # 7. Schedule next update
    root.after(1000, update_monitor_ui)
```

**Key Functions**:

#### `do_buy(trade_type="Manual")`
**Flow**:
1. **Validation**:
   - Check `is_buy_disabled()` → if yes, error + return
   - Check symbol entered
   - Check position not already open (buy_active == False)

2. **Pre-Order**:
   - Fetch live LTP of symbol (ltp_var)
   - Set `buy_pending = True` (block re-entry)
   - Disable BUY button

3. **Place Order**:
   - Get token from scrip_master
   - Call `place_market_order(token, lots, "BUY", symbol)`
   - Parse response: check for `nOrdNo` (order ID)

4. **Verify Completion** (Retry Loop):
   - Loop 10 times (10 second timeout):
     - Sleep 1s
     - Fetch `order_report()` or `positions()`
     - Check if trade appears with qty == lots
     - If found: set `buy_active = True`, break

5. **Capture Entry Metadata**:
   - Call `scalp_manager.get_signal()` to capture indicators
   - Store in `active_trade_metadata`: entry_sig, entry_ema, entry_roc, entry_bbw, entry_time

6. **Set Exit Parameters**:
   - Read from UI: target_pts, sl_pts, trailing_sl_step
   - Calculate: `target_price = last_buy_price + target_pts`
   - Calculate: `sl_price = last_buy_price - sl_pts`
   - Set `max_price_seen = ltp` (for trailing SL)

7. **Update UI**:
   - Enable EXIT button
   - Show position label: "● POSITION OPEN" (red)
   - Disable auto-buy toggle

**Error Handling**:
- If order not found in report: log error, set `buy_active = False`, return
- If order fails: catch exception, reset state, return

#### `do_exit(reason="Manual")`
**Flow**:
1. **Validation**:
   - Check `exit_pending == False` (block re-exit)
   - Check `active_symbol` is set

2. **Capture Exit Metadata**:
   - Call `scalp_manager.get_signal()`
   - Append to `active_trade_metadata`: exit_sig, exit_ema, exit_roc, exit_bbw, exit_reason

3. **Place Sell Order**:
   - Get token for `active_symbol`
   - Call `place_market_order(token, lots, "SELL", active_symbol)`
   - Set `exit_pending = True`

4. **Verify Completion** (Retry Loop):
   - Same as BUY: poll order report, check SELL qty

5. **Calculate PnL**:
   - Once verified: `pnl_engine.add_trade(sell_trade)`
   - Result: completed trade in engine

6. **Save to CSV**:
   - Append to `logs/trades_YYYY-MM-DD.csv`:
     - Timestamp, symbol, qty, buy_price, sell_price, gross_pnl, charges, net_pnl, entry_sig, exit_reason, rsi, momentum, etc.

7. **Update UI**:
   - Show position label: "● NO POSITION"
   - Disable EXIT button
   - Reset `buy_active`, `active_symbol`, `last_buy_price`
   - Show exit reason in status

8. **Start Cool-Off**:
   - Set `last_exit_time = time.time()`
   - Block new BUYs for COOL_OFF_PERIOD (e.g., 10s)

#### `is_buy_disabled() → bool`
**Checks** (all conditions evaluated):
1. **Progressive Loss Lockout**:
   - Read `buy_disabled.json` (if exists)
   - Check `disabled_until > now`
   - If yes: return True

2. **Cool-Off Period**:
   - Check `last_exit_time` + COOL_OFF_PERIOD > now
   - If yes: return True

3. **Consecutive Loss Count**:
   - Count recent losses (last 3 trades)
   - If 3 losses: return True (trigger cool-off)

4. **Max-Profit Disable**:
   - Check if daily profit >= BUY_DISABLE_MAX_PROFIT
   - If yes: return True

5. **Hard Stop**:
   - Count daily losses (last 24h)
   - If >= BUY_DISABLE_DAILY_LOSS_LIMIT: return True

**Return**: True if ANY condition met (buy blocked)

#### `process_buy_disable_logic(engine)`
**Purpose**: Apply or clear lockouts based on PnL thresholds

**Flow**:
1. Get cumulative loss (negative capital delta)
2. Iterate through PROGRESSIVE_LOSS_CONFIG tiers
3. If loss >= tier threshold:
   - Check if lockout already applied for this tier
   - If not: write `buy_disabled.json` with:
     - `disabled_until`: now + tier.disabled_minutes
     - `last_trade_id`: last completed trade ID
     - `highest_threshold`: this tier's threshold
4. If PnL improved (current > last_trade PnL):
   - Clear lockout (delete file or mark expired)

**Lockout File** (`buy_disabled.json`):
```json
{
    "disabled_until": "2026-02-27T14:35:30Z",
    "last_trade_id": "123456",
    "date": "2026-02-27",
    "highest_threshold": 1000,
    "reason": "Progressive loss: 1250 >= 1000"
}
```

#### `update_monitor_ui()`
**Comprehensive Monitor Loop**:
- **Every 1s** (runs in background thread via `run_bg()`)
- Polls broker order report, fetches quotes, calculates indicators
- Updates PnL display, recent trades, status labels
- Checks auto-buy/auto-sell conditions
- Handles UI updates via `root.after(0, ...)`

**Key Sub-Flows**:
1. **Position Sync**:
   - Fetch positions API
   - Check for open F&O positions (exclude equity)
   - If open but `buy_active == False`: recover state from API
   - If closed but `buy_active == True`: detect exit (emergency recovery)

2. **Order Processing**:
   - Fetch order report, rebuild engine
   - Enrich trades with metadata (entry_sig, exit_reason, indicators)
   - Calculate weekly/daily PnL

3. **Indicator Calculation**:
   - Feed LTP to `scalp_manager`
   - Get signal + technical data (RSI, momentum, EMA, etc.)
   - Update strategy status labels

4. **Auto-Buy Logic**:
   - If `auto_buy == True` and `not buy_active` and `sig == 'BULLISH'`
   - Check `is_buy_allowed()`
   - Call `do_buy(trade_type="Auto")`
   - Log auto-entry metadata

5. **Auto-Exit Logic**:
   - If `auto_sell == True` and `buy_active`
   - Check exit conditions:
     - `cur_price >= target_price` → `do_exit("Target")`
     - `cur_price <= sl_price` → `do_exit("SL")`
     - `cur_price <= max_price_seen - trailing_sl_step` → `do_exit("Trailing SL")`
     - Time-stop (if entry_time + max_hold_time > now) → `do_exit("TimeStop")`

6. **Symbol Mismatch Detection**:
   - If auto is enabled but CE/PE doesn't match signal:
     - Log warning, optionally toggle automatically
     - Prevents bearish buy signal on CE (wrong side)

7. **UI Rendering**:
   - Calculate PnL stats
   - Format lines for monitor display
   - Update labels, text box via `root.after(0, ...)`

8. **Remote Config Refresh** (Every 5 mins):
   - Fetch updated PROGRESSIVE_LOSS_CONFIG
   - Fetch updated BUY_DISABLE_MAX_LOSS
   - Update global variables

#### `startup_sequence()`
**Initialization on App Start**:
1. Login to broker (auto-login, no user interaction)
2. Load scrip master CSV (token cache)
3. Initialize PnL engine with latest capital
4. Load symbol history from file
5. Send Telegram startup message (if enabled)
6. Start monitor loop (`run_bg(update_monitor_ui)`)

#### `save_trades_to_csv(trades_to_log)`
**Purpose**: Persist completed trades to CSV for record-keeping  
**Path**: `logs/trades_YYYY-MM-DD.csv`  
**Columns**:
- Timestamp, Symbol, Qty, BuyPrice, SellPrice, GrossPnL, Charges, NetPnL
- EntryTime, ExitTime, EntrySignal, ExitReason
- RSI, Momentum, EMA, ROC, BBWidth

**Daily Reset**:
- Creates new CSV each day
- At 3:30 PM: saves capital snapshot to `capital_history.csv`

#### `render_monitor_display(lines, net_val, gross_val, day_net_val)`
**Purpose**: Format and update monitor text box  
**Layout**:
```
Week (Mon-Fri): 2026-02-24 to 2026-02-28
Trades: 12
W/L   : 8/4 (66.7%)
--------------------
Gross PnL: 1506.0
Net PnL  : 1200.0
Day PnL  : 450.0
Charges  : 306.0
--------------------
RSI: 72.5 | Mom: 2.3% | EMA: 23400
Signal: BULLISH (Strength: 85%)
Pulse: Yes | SR: 23350 / 23500
--------------------
Recent Trades:
[14:15] BUY  NIFTY2623750CE  @ 120.0
[14:20] SELL NIFTY2623750CE  @ 125.0  (+500.0 net)
[14:25] BUY  NIFTY2623750CE  @ 123.5
...
```

**Color Coding**:
- Green: Positive PnL, BULLISH signal
- Red: Negative PnL, BEARISH signal
- Yellow: Neutral/sideways
- Blue: Pulse detected (expansion)

**Dependencies**: tkinter, pandas, datetime, common modules, monitor/pnl_engine, indicator/scalping_indicator, csv, json, threading, time

---

## 10. Configuration & Deployment

### [.env](/.env) (Not in Repo, Created Locally)
**Purpose**: Store sensitive credentials and config  
**Format**: KEY=VALUE pairs

**Example**:
```env
# Broker Auth
CONSUMER_KEY=your_key_here
MOBILE=9999999999
UCC=your_ucc
MPIN=9999
TOTP_SECRET=JBSWY3DPEHPK3PXP

# Trading
INITIAL_CAPITAL=50000
CAPITAL_TOPUP=0
PNL_RESET_DATE=2024-01-01
COOL_OFF_PERIOD=10

# Risk
BUY_DISABLE_MAX_LOSS=2500
BUY_DISABLE_MAX_PROFIT=5000
BUY_DISABLE_DAILY_LOSS_LIMIT=50

# Telegram (optional)
TELEGRAM_BOTS_URL=https://config.example.com/bots

# Web
WEB_API_TOKEN=your_random_token_here
TRADING_ENABLED=false
WEB_POLL_SECONDS=5
WORKER_HEALTH_WINDOW_SECONDS=30
```

---

### [requirements-web.txt](requirements-web.txt)
**Purpose**: Dependencies for web mode (beyond base requirements.txt)

**Content**:
```
fastapi==0.116.1
uvicorn[standard]==0.35.0
```

**Installation**:
```bash
pip install -r requirements.txt -r requirements-web.txt
```

---

### [.github/workflows/deploy-azure-vm.yml](.github/workflows/deploy-azure-vm.yml)
**Purpose**: GitHub Actions CI/CD pipeline (scaffolded, not finalized)  
**Status**: P3 (low priority), workflow exists but incomplete

**Planned Steps**:
1. Build + test on push to main
2. Create release artifact
3. SSH to Azure VM
4. Deploy artifact
5. Restart systemd services
6. Health check API
7. Rollback on failure

**Required Secrets** (to configure in GitHub):
- `AZURE_VM_HOST` – IP or FQDN
- `AZURE_VM_USER` – SSH username
- `AZURE_VM_SSH_KEY` – Private key
- `DEPLOY_PATH` – Destination directory

---

## 11. State Machines & Key Flows

### Buy-Exit Lifecycle (Desktop)
```
[NO POSITION]
     ↓ User clicks BUY / Auto signal
[PENDING BUY] (buy_pending=True)
     ↓ Order verification loop
[POSITION OPEN] (buy_active=True, active_symbol set)
     ↓ Auto-exit conditions OR user clicks EXIT
[PENDING EXIT] (exit_pending=True)
     ↓ Order verification loop
[NO POSITION, COOL-OFF] (buy_disabled=True, cool_off timer set)
     ↓ Wait COOL_OFF_PERIOD
[NO POSITION] (buy_disabled=False)
```

### Risk Lockout Tiers (Progressive Loss)
```
Loss < 500 pts       → No lockout
Loss 500-1000 pts    → 5-min lockout
Loss 1000-2500 pts   → 10-min lockout
Loss >= 2500 pts     → Hard stop (rest of day)
```

### Recovery Logic
```
Buy-disabled JSON written with threshold=1000
     ↓
Next trade is profitable
     ↓
PnL improves, cumulative loss drops to 850 pts
     ↓
Threshold check: 850 < 1000 → Lockout cleared
     ↓
BUY allowed again
```

### Worker Polling Cycle (Web)
```
[Worker Started]
     ↓ Every 5 seconds
[Poll broker.order_report()]
     ↓
[Rebuild PositionPnLEngine from scratch]
     ↓
[Calculate indicators via scalp_manager]
     ↓
[Build rich snapshot]
     ↓
[Check risk conditions]
     ↓
[Atomic write to JSON (temp + rename)]
     ↓
[Sleep 5s, repeat]

[API reads snapshot (any time)]
     ↓
[Check worker health: age < 30s?]
     ↓
[Return to client or WebSocket]
```

---

## 12. Quick Reference: File → Function Mapping

| File | Primary Purpose | Key Functions |
|------|-----------------|----------------|
| `run.py` | Desktop entry | N/A (imports module) |
| `scalper/neoscalper.py` | Tkinter UI + desktop logic | `do_buy()`, `do_exit()`, `update_monitor_ui()`, `is_buy_disabled()` |
| `web/backend/main.py` | FastAPI server | Routes: `/health`, `/api/system/status`, `/api/monitor/snapshot`, `/api/trade/action`, `/ws/monitor` |
| `web/backend/auth.py` | Auth guard | `require_api_key()`, `require_ws_token()`, `is_trading_enabled()` |
| `web/backend/models.py` | Pydantic schemas | `TradeActionRequest`, `SystemStatusResponse`, `MonitorSnapshotResponse` |
| `web/worker/main.py` | Polling daemon | Main loop: poll → rebuild engine → build snapshot → write JSON |
| `web/shared/state_store.py` | Atomic I/O | `read_snapshot()`, `write_snapshot()` |
| `web/shared/monitor_snapshot.py` | Stats aggregation | `build_monitor_snapshot(trades)` |
| `web/shared/trading_actions.py` | Order execution | `execute_market_action(symbol, lots, action)` |
| `web/shared/symbol_helpers.py` | Symbol parsing | `parse_symbol_parts()`, `suggest_symbol_for_index()` |
| `web/shared/risk_controls.py` | Lockout logic | `is_buy_allowed()`, `apply_lockout()` |
| `common/config.py` | Config mgmt | `get_next_expiry()`, `detect_strike_step()` |
| `common/neo_login.py` | Broker auth | `get_neo_client()` |
| `common/orders.py` | Order execution | `place_market_order()`, `detect_exchange_segment()` |
| `common/scrip_master.py` | Symbol lookup | `find_token_for_trading_symbol()`, `load_scrip_master_csv()` |
| `common/utils.py` | Utilities | `run_bg()`, `log_with_callback()`, `fetch_remote_config()`, `send_telegram_msg()` |
| `monitor/pnl_engine.py` | PnL calculation | `PositionPnLEngine`, `parse_api_orders()`, `ChargesCalculator` |
| `monitor/neomonitor.py` | Legacy monitor | Main loop, statistics print |
| `indicator/scalping_indicator.py` | Indicators | `ScalpingStrategyV1`, `RSIMomentumStrategy`, `LiveScalpingManager` |

---

## 13. Development & Debugging Notes

### Running Desktop Mode
```bash
python run.py
```
- Opens Tkinter window
- Auto-login to broker
- Monitor updates every 1s
- Manual BUY/EXIT buttons

### Running Web Mode
```bash
# Terminal 1: Worker
python -m web.worker.main

# Terminal 2: API
uvicorn web.backend.main:app --host 0.0.0.0 --port 8000

# Open browser
http://localhost:8000
```

### Authentication (Web)
```bash
# Set token in .env
WEB_API_TOKEN=my_secret_token_here

# Test endpoint
curl -H "X-API-Key: my_secret_token_here" http://localhost:8000/api/system/status
```

### Debugging Common Issues

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| "Order not confirmed" | Order placement succeeded but not appearing in report | Increase verification retry count (10→20) or wait time (1s→2s) |
| Buy-disable not triggering | Lockout logic not evaluating correctly | Check `buy_disabled.json` timestamp vs current time |
| Worker unhealthy | Snapshot age > 30s (poll took too long or crashed) | Check worker logs, may need broker API timeout increase |
| Symbol token not found | Scrip master CSV stale | Re-run `load_scrip_master_csv()` to re-download |
| Telegram alerts not sending | Bot list not loaded or network error | Check `TELEGRAM_BOTS_URL` and test curl |
| UI freezing | Monitor loop blocking UI thread | Should use `run_bg()` to spawn daemon thread |

### Key Files to Monitor
- `buy_disabled.json` – Lockout state (check timestamp for debugging)
- `logs/web_monitor_state.json` – Worker output (API reads this)
- `logs/trades_YYYY-MM-DD.csv` – Trade history (verify PnL calculations)
- `.env` – Secrets (never commit, always in .gitignore)

---

**End of Project Logic Reference**

This document serves as a quick index for all core files and their logic. On future requests, reference this document instead of re-scanning files to load context faster.
