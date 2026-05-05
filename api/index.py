@app.get("/debug/user")
def debug_user():
    import requests
    import os

    token = os.environ.get("SEEDR_ACCESS_TOKEN")

    if not token:
        return {"error": "Missing token"}

    try:
        res = requests.get(
            "https://www.seedr.cc/api/v0.1/p/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },
            timeout=10
        )

        return {
            "status": res.status_code,
            "data": res.json()
        }

    except Exception as e:
        return {"error": str(e)}
