from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = "https://www.seedr.cc/api/v0.1/p"

# -----------------------
# Auth
# -----------------------
def get_headers():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

# -----------------------
# Seedr API
# -----------------------
def get_folder(folder_id=0):
    url = f"{BASE}/fs/folder/{folder_id}/items"
    res = requests.get(url, headers=get_headers(), timeout=15)
    res.raise_for_status()
    return res.json()

def get_file(file_id):
    url = f"{BASE}/fs/file/{file_id}"
    res = requests.get(url, headers=get_headers(), timeout=15)
    res.raise_for_status()
    return res.json()

# -----------------------
# Helpers
# -----------------------
def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def walk_files(folder_id=0):
    data = get_folder(folder_id)

    for item in data.get("items", []):
        if item.get("type") == "file":
            yield item
        elif item.get("type") == "folder":
            yield from walk_files(item.get("id"))

# -----------------------
# Debug
# -----------------------
@app.get("/debug/test")
def debug_test():
    try:
        data = get_folder(0)
        return data
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "trace": traceback.format_exc()
        }

# -----------------------
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "12.0.0",
        "name": "Seedr Addon",
        "resources": ["stream", "catalog"],
        "types": ["movie"],
        "catalogs": [
            {"type": "movie", "id": "seedr", "name": "My Seedr Files"}
        ]
    }

# -----------------------
# Catalog
# -----------------------
@app.get("/catalog/movie/seedr.json")
def catalog():
    metas = []

    for f in walk_files():
        name = f.get("name")
        if not name:
            continue

        metas.append({
            "id": normalize(name),
            "type": "movie",
            "name": name
        })

    return {"metas": metas}

# -----------------------
# Stream
# -----------------------
@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    for f in walk_files():
        name = f.get("name")
        file_id = f.get("id")

        if not name:
            continue

        if normalize(id) in normalize(name):
            file_info = get_file(file_id)

            url = file_info.get("url") or file_info.get("stream_url")

            if url:
                streams.append({
                    "name": "Seedr",
                    "title": name,
                    "url": url
                })

    return {"streams": streams}
