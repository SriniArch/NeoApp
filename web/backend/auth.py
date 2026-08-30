import os
from fastapi import Header, HTTPException, Query


def get_configured_api_token() -> str:
    return os.getenv("WEB_API_TOKEN", "").strip()


def is_local_auth_bypass_enabled() -> bool:
    return os.getenv("WEB_ALLOW_LOCAL_NOAUTH", "false").strip().lower() in ("1", "true", "yes", "on")


def is_trading_enabled() -> bool:
    return os.getenv("TRADING_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def require_api_key(x_api_key: str = Header(default="")) -> None:
    token = get_configured_api_token()
    if not token:
        if is_local_auth_bypass_enabled():
            return
        raise HTTPException(status_code=503, detail="API token not configured")
    if x_api_key != token:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_ws_token(token: str = Query(default="")) -> None:
    configured = get_configured_api_token()
    if not configured:
        if is_local_auth_bypass_enabled():
            return
        raise HTTPException(status_code=503, detail="API token not configured")
    if token != configured:
        raise HTTPException(status_code=401, detail="Invalid WebSocket token")
