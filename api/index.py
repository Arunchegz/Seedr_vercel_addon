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

BASE = "https://www.seedr.cc/api/v0.1/p/resource.php"

# -----------------------
# Auth
# -----------------------
def get_token():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")
    return token

# -----------------------
# Seedr API (WORKING)
# -----------------------
def list_contents(folder_id=None):
    data = {
        "access_token": get_token(),
        "func": "list_contents"
    }
    if folder_id:
        data["folder_id"] = folder_id

    res = requests.post(BASE, data=data, timeout=15)
    res.raise_for_status()
    return res.json()

def fetch_file(file_id):
    res = requests.post(
        BASE,
        data={
            "access_token": get_token(),
            "func": "fetch_file",
            "folder_file_id": file_id
        },
        timeout=15
    )
    res.raise_for_status()
    return res.json()

# -----------------------
# Helpers
# -----------------------
def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def walk_files(folder_id=None):
    data = list_contents(folder_id)

    for f in data.get("files", []):
        yield f

    for folder in data.get("folders", []):
        yield from walk_files(folder.get("id"))

# -----------------------
# Debug
# -----------------------
@app.get("/debug/test")
def debug_test():
    try:
        return list_contents()
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/files")
def debug_files():
    try:
        return list(walk_files())
    except Exception as e:
        return {"error": str(e)}

# -----------------------
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "13.0.0",
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

    try:
        for f in walk_files():
            name = f.get("name")
            file_id = f.get("folder_file_id")

            if not name:
                continue

            metas.append({
                "id": normalize(name),
                "type": "movie",
                "name": name
            })

    except Exception as e:
        return {"metas": [], "error": str(e)}

    return {"metas": metas}

# -----------------------
# Stream
# -----------------------
@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    try:
        for f in walk_files():
            name = f.get("name")
            file_id = f.get("folder_file_id")

            if not name or not file_id:
                continue

            if normalize(id) in normalize(name):
                file_data = fetch_file(file_id)
                url = file_data.get("url")

                if url:
                    streams.append({
                        "name": "Seedr",
                        "title": name,
                        "url": url
                    })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
