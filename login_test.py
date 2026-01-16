from common.neo_login import get_neo_client
import sys

print("Testing Neo Login...")
try:
    client = get_neo_client()
    print("Login Successful!")
    print(client.quotes([{"instrument_token": "26000", "exchange_segment": "nse_fo"}], quote_type="ltp"))
except Exception as e:
    print(f"Login Failed: {e}")
