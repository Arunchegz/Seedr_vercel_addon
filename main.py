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
# Upstash KV
# -----------------------

redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

# -----------------------
# Seedr API
# -----------------------

SEEDR_API = "https://www.seedr.cc/rest"

def seedr_request(endpoint, params=None):
    api_token = os.environ.get("SEEDR_API_TOKEN")
    if not api_token:
        raise Exception("SEEDR_API_TOKEN missing")

    headers = {
        "Authorization": f"Bearer {api_token}"
    }

    url = f"{SEEDR_API}/{endpoint}"

    r = requests.get(url, headers=headers, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()

# -----------------------
# Helpers
# -----------------------

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def walk_files(folder_id=None):
    params = {}

    if folder_id is not None:
        params["folder_id"] = folder_id

    data = seedr_request("folder", params)

    for f in data.get("files", []):
        yield f

    for folder in data.get("folders", []):
        yield from walk_files(folder["id"])

def extract_title_year(filename):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

def is_video(filename):
    return any(filename.lower().endswith(ext) for ext in [
        ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"
    ])

# -----------------------
# Cache
# -----------------------

def get_cached_stream_url(file_id):
    key = f"seedr:stream:{file_id}"

    cached = redis.get(key)
    if cached:
        return json.loads(cached)["url"]

    data = seedr_request("file", {"file_id": file_id})
    url = data.get("url")

    redis.set(key, json.dumps({"url": url}), ex=86400)

    return url

# -----------------------
# Routes
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "FINAL API TOKEN VERSION"
    }

# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "2.1.0",
        "name": "Seedr.cc Personal Addon",
        "description": "Stable API Token version",
        "resources": ["stream", "catalog", "meta"],
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

    try:
        for f in walk_files():
            name = f.get("name", "")

            if not is_video(name):
                continue

            title, year = extract_title_year(name)

            metas.append({
                "id": normalize(title + year),
                "type": "movie",
                "name": title or name,
                "year": year
            })

    except Exception as e:
        return {"error": str(e)}

    return {"metas": metas}

# -----------------------
# Meta
# -----------------------

@app.get("/meta/movie/{id}.json")
def meta(id: str):
    return {
        "meta": {
            "id": id,
            "type": "movie",
            "name": id
        }
    }

# -----------------------
# Stream
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        for f in walk_files():
            name = f.get("name", "")

            if not is_video(name):
                continue

            title, year = extract_title_year(name)
            file_id = normalize(title + year)

            if file_id == id:
                url = get_cached_stream_url(f["id"])

                streams.append({
                    "name": "Seedr.cc",
                    "title": name,
                    "url": url
                })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}

# -----------------------
# Debug
# -----------------------

@app.get("/debug")
def debug():
    try:
        return seedr_request("folder")
    except Exception as e:
        return {"error": str(e)}
