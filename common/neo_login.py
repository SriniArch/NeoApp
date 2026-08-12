import os
import pyotp
from dotenv import load_dotenv
from neo_api_client import NeoAPI

def get_neo_client():
    """
    Initializes and returns an authenticated NeoAPI client.
    Reads credentials from environment variables.
    """
    load_dotenv()
    
    CONSUMER_KEY = os.getenv("CONSUMER_KEY")
    MOBILE = os.getenv("MOBILE")
    UCC = os.getenv("UCC")
    MPIN = os.getenv("MPIN")
    TOTP_SECRET = os.getenv("TOTP_SECRET")

    if not all([CONSUMER_KEY, MOBILE, UCC, MPIN, TOTP_SECRET]):
        raise Exception("Missing environment variables (CONSUMER_KEY, MOBILE, UCC, MPIN, TOTP_SECRET) for Neo login")

    # Clean variables by stripping whitespace
    CONSUMER_KEY = CONSUMER_KEY.strip()
    MOBILE = MOBILE.strip()
    UCC = UCC.strip()
    MPIN = str(MPIN).strip()
    TOTP_SECRET = TOTP_SECRET.strip().replace(" ", "")

    client = NeoAPI(
        consumer_key=CONSUMER_KEY,
        environment="prod"
    )

    totp = pyotp.TOTP(TOTP_SECRET).now()

    login_resp = client.totp_login(
        mobile_number=MOBILE,
        ucc=UCC,
        totp=totp
    )
    
    # Check for login errors
    if isinstance(login_resp, dict) and "error" in login_resp:
        err_msg = login_resp["error"][0].get("message", "Unknown Error")
        err_code = login_resp["error"][0].get("code", "Unknown Code")
        raise Exception(f"TOTP Login Failed (Code: {err_code}): {err_msg}")
    elif isinstance(login_resp, dict) and login_resp.get("status") == "error":
        raise Exception(f"TOTP Login Failed: {login_resp.get('message', 'Unknown Error')}")

    validate_resp = client.totp_validate(mpin=MPIN)
    
    # Check for validation/MPIN errors
    if isinstance(validate_resp, dict) and "error" in validate_resp:
        err_msg = validate_resp["error"][0].get("message", "Unknown Error")
        err_code = validate_resp["error"][0].get("code", "Unknown Code")
        raise Exception(f"MPIN Validation Failed (Code: {err_code}): {err_msg}")
    elif isinstance(validate_resp, dict) and validate_resp.get("status") == "error":
        raise Exception(f"MPIN Validation Failed: {validate_resp.get('message', 'Unknown Error')}")

    # Check if access token is successfully set or check base_url
    if hasattr(client, 'access_token') and client.access_token:
        print(f"DEBUG: Login successful. Access Token: {client.access_token[:10]}...")
    elif client.configuration.base_url:
        print(f"DEBUG: Login successful. Base URL: {client.configuration.base_url}")
    else:
        raise Exception("Login failed: Access token or Base URL not set in client configuration")

    return client
