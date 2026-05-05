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
# Seedr API (DIRECT - NO seedrcc)
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

    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

# -----------------------
# Helpers
# -----------------------

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def walk_files(folder_id=None):
    data = seedr_request("folder", {"folder_id": folder_id or 0})

    for f in data.get("files", []):
        yield f

    for folder in data.get("folders", []):
        yield from walk_files(folder["id"])

def extract_title_year(filename):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

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
    return {"status": "ok", "version": "API TOKEN VERSION"}

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "2.0.0",
        "name": "Seedr.cc Personal Addon",
        "resources": ["stream", "catalog"],
        "types": ["movie"],
        "catalogs": [
            {"type": "movie", "id": "seedr", "name": "My Seedr Files"}
        ]
    }

@app.get("/catalog/movie/seedr.json")
def catalog():
    metas = []

    for f in walk_files():
        if not f.get("play_video"):
            continue

        title, year = extract_title_year(f["name"])

        metas.append({
            "id": normalize(title + year),
            "type": "movie",
            "name": title,
            "year": year
        })

    return {"metas": metas}

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    for f in walk_files():
        if not f.get("play_video"):
            continue

        title, year = extract_title_year(f["name"])
        file_id = normalize(title + year)

        if file_id == id:
            url = get_cached_stream_url(f["id"])

            streams.append({
                "name": "Seedr.cc",
                "title": f["name"],
                "url": url
            })

    return {"streams": streams}
