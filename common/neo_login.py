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

    client = NeoAPI(
        consumer_key=CONSUMER_KEY,
        environment="prod"
    )

    totp = pyotp.TOTP(TOTP_SECRET).now()

    client.totp_login(
        mobile_number=MOBILE,
        ucc=UCC,
        totp=totp
    )

    client.totp_validate(mpin=MPIN)

    # Check session state
    if hasattr(client, 'access_token') and client.access_token:
        print(f"DEBUG: Login successful. Access Token: {client.access_token[:10]}...")
    else:
        # If the API works downstream even without this attribute visible, we assume success
        print("DEBUG: Login process completed.")

    return client
