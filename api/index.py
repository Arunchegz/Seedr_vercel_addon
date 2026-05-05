from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from upstash_redis import Redis
import os
import re
import requests
import json

app = FastAPI()

# -----------------------
# CORS
# -----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Redis (optional)
# -----------------------
redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

# -----------------------
# Seedr Client (ONLY THIS)
# -----------------------
class SeedrClient:
    def __init__(self, token):
        self.token = token
        self.url = "https://www.seedr.cc/api/v0.1/p/resource.php"

    def list_contents(self, folder_id=None):
        data = {
            "access_token": self.token,
            "func": "list_contents"
        }
        if folder_id:
            data["folder_id"] = folder_id

        res = requests.post(self.url, data=data, timeout=15)
        res.raise_for_status()
        return res.json()

    def fetch_file(self, file_id):
        data = {
            "access_token": self.token,
            "func": "fetch_file",
            "folder_file_id": file_id
        }

        res = requests.post(self.url, data=data, timeout=15)
        res.raise_for_status()
        return res.json()


def get_client():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")
    return SeedrClient(token)

# -----------------------
# Helpers
# -----------------------
def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def extract_title_year(filename):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

def walk_files(client, folder_id=None):
    data = client.list_contents(folder_id)

    for f in data.get("files", []):
        yield f

    for folder in data.get("folders", []):
        yield from walk_files(client, folder.get("id"))

# -----------------------
# Cache
# -----------------------
def get_cached_stream_url(client, file):
    file_id = file.get("folder_file_id")

    key = f"seedr:stream:{file_id}"

    cached = redis.get(key)
    if cached:
        return json.loads(cached)["url"]

    result = client.fetch_file(file_id)
    url = result.get("url")

    redis.set(key, json.dumps({"url": url}), ex=86400)
    return url

# -----------------------
# Root
# -----------------------
@app.get("/")
def root():
    return {"status": "ok"}

# -----------------------
# Debug: Check token
# -----------------------
@app.get("/debug/test-seedr")
def test_seedr():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")

    if not token:
        return {"error": "Missing token"}

    try:
        res = requests.get(
            "https://www.seedr.cc/api/v0.1/p/user",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )

        return {
            "status": res.status_code,
            "data": res.json()
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------
# Debug: List files
# -----------------------
@app.get("/debug/files")
def debug_files():
    client = get_client()
    return list(walk_files(client))

# -----------------------
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "6.0.0",
        "name": "Seedr Personal Addon",
        "description": "Stream Seedr files",
        "resources": ["stream", "catalog"],
        "types": ["movie"],
        "catalogs": [
            {
                "type": "movie",
                "id": "seedr",
                "name": "My Seedr Files"
            }
        ]
    }

# -----------------------
# Catalog
# -----------------------
@app.get("/catalog/movie/seedr.json")
def catalog():
    metas = []
    client = get_client()

    try:
        for f in walk_files(client):
            name = f.get("name")
            if not name:
                continue

            title, year = extract_title_year(name)
            meta_id = normalize(title + year)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title or name,
                "year": year
            })

    except Exception as e:
        return {"metas": [], "error": str(e)}

    return {"metas": metas}

# -----------------------
# Stream
# -----------------------
@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    if type != "movie":
        return {"streams": []}

    client = get_client()
    streams = []

    try:
        id_norm = normalize(id)

        for f in walk_files(client):
            name = f.get("name", "")
            if not name:
                continue

            if id_norm in normalize(name):
                url = get_cached_stream_url(client, f)

                streams.append({
                    "name": "Seedr",
                    "title": name,
                    "url": url
                })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
