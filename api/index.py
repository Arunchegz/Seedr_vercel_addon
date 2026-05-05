from fastapi import FastAPI
import requests
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

# -----------------------
# TEST ALL IN ONE
# -----------------------
@app.get("/debug/all")
def debug_all():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")

    if not token:
        return {"error": "Missing SEEDR_ACCESS_TOKEN"}

    base = "https://www.seedr.cc/api/v0.1"

    try:
        # 1. USER
        user = requests.get(
            f"{base}/p/user",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )

        # 2. FILE LIST
        files = requests.post(
            f"{base}/p/resource.php",
            data={
                "access_token": token,
                "func": "list_contents"
            },
            timeout=10
        )

        file_data = files.json()

        # 3. STREAM TEST
        stream = {}
        if file_data.get("files"):
            file_id = file_data["files"][0]["folder_file_id"]

            stream_res = requests.post(
                f"{base}/p/resource.php",
                data={
                    "access_token": token,
                    "func": "fetch_file",
                    "folder_file_id": file_id
                },
                timeout=10
            )

            stream = stream_res.json()

        return {
            "user_status": user.status_code,
            "user": user.json(),

            "files_status": files.status_code,
            "files": file_data,

            "stream": stream
        }

    except Exception as e:
        return {"error": str(e)}
