
import os
import sys
from dotenv import load_dotenv

# Allow importing from parent directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common.neo_login import get_neo_client

def test_order_report():
    load_dotenv(".env")
    client = get_neo_client()
    if not client:
        print("Login failed")
        return
    
    report = client.order_report()
    data = report.get("data", []) if isinstance(report, dict) else report
    if data and isinstance(data, list):
        sources = {}
        for o in data:
            src = o.get("ordSrc", "UNKNOWN")
            if src not in sources:
                sources[src] = o.get("trdSym")
        
        print("UNIQUE ORDER SOURCES FOUND:")
        for src, sym in sources.items():
            print(f"- {src} (Sample: {sym})")
    else:
        print(f"No orders found or invalid response: {report}")

if __name__ == "__main__":
    test_order_report()
