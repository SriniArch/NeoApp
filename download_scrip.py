from common.neo_login import get_neo_client
import requests
client = get_neo_client()
print("Downloading scrip master...")
try:
    url = client.scrip_master(exchange_segment="nse_fo")
    print("URL:", url)
    headers = {"Authorization": f"Bearer {client.access_token}"} if hasattr(client, 'access_token') else {}
    resp = requests.get(url, headers=headers)
    print("Status code:", resp.status_code)
    if resp.status_code == 200:
        with open('nse_fo_new.csv', 'wb') as f:
            f.write(resp.content)
        print("Saved to nse_fo_new.csv")
except Exception as e:
    print("Error:", e)
