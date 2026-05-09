import requests
import json

# ---------------------------------------------------
# Seedr OAuth Config
# ---------------------------------------------------

CLIENT_ID = "YOUR_CLIENT_ID"

REFRESH_TOKEN = "YOUR_REFRESH_TOKEN"

# ---------------------------------------------------
# Refresh Access Token
# ---------------------------------------------------

response = requests.post(
    "https://v2.seedr.cc/api/v0.1/p/oauth/token",
    data={
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID
    }
)

# ---------------------------------------------------
# Output
# ---------------------------------------------------

print("STATUS CODE:\n")
print(response.status_code)

print("\nRESPONSE:\n")
print(json.dumps(response.json(), indent=2))

# ---------------------------------------------------
# Extract new tokens
# ---------------------------------------------------

data = response.json()

if "access_token" in data:

    print("\nNEW ACCESS TOKEN:\n")
    print(data["access_token"])

    print("\nNEW REFRESH TOKEN:\n")
    print(data.get("refresh_token"))

    print("\nSCOPES:\n")
    print(data.get("scope"))

else:

    print("\nTOKEN REFRESH FAILED")
