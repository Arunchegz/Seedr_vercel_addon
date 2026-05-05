from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
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
# Upstash KV (NO EXPIRY)
# -----------------------

redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

# -----------------------
# Seedr Client (API TOKEN)
# -----------------------

def get_client():
    api_token = os.environ.get("SEEDR_API_TOKEN")
    if not api_token:
        raise Exception("SEEDR_API_TOKEN environment variable is missing")

    client = Seedr()

    # Inject API token into headers
    client.session.headers.update({
        "Authorization": f"Bearer {api_token}"
    })

    return client

# -----------------------
# Helpers
# -----------------------

def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def get_movie_title(imdb_id: str):
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    meta = data.get("meta", {})
    title = meta.get("name", "")
    year = str(meta.get("year", ""))
    return title, year

def walk_files(client, folder_id=None):
    contents = client.list_contents(folder_id=folder_id)

    for f in contents.files:
        yield f

    for folder in contents.folders:
        yield from walk_files(client, folder.id)

def extract_title_year(filename: str):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

# -----------------------
# KV Cache
# -----------------------

def get_cached_stream_url(client, file):
    key = f"seedr:stream:{file.folder_file_id}"

    cached = redis.get(key)
    if cached:
        cached = json.loads(cached)
        return cached["url"]

    result = client.fetch_file(file.folder_file_id)

    data = {
        "url": result.url
    }

    redis.set(key, json.dumps(data), ex=86400)

    return result.url

# -----------------------
# Sync KV
# -----------------------

def sync_kv_with_seedr(client):
    seedr_ids = set(str(f.folder_file_id) for f in walk_files(client))
    keys = redis.keys("seedr:stream:*")

    for key in keys:
        file_id = key.split(":")[-1]
        if file_id not in seedr_ids:
            redis.delete(key)

# -----------------------
# Root
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr API Token Addon running"
    }

# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "2.0.0",
        "name": "Seedr.cc Personal Addon",
        "description": "API Token version (stable)",
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

    with get_client() as client:
        for f in walk_files(client):
            if not f.play_video:
                continue

            title, year = extract_title_year(f.name)
            meta_id = normalize(title + year)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title or f.name,
                "year": year,
                "poster": None
            })

    return {"metas": metas}

# -----------------------
# Stream
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        with get_client() as client:

            sync_kv_with_seedr(client)

            if id.startswith("tt"):
                movie_title, movie_year = get_movie_title(id)
                norm_title = normalize(movie_title)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    if norm_title in normalize(file.name) and movie_year in file.name:
                        url = get_cached_stream_url(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": file.name,
                            "url": url
                        })

            else:
                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    title, year = extract_title_year(file.name)
                    file_id = normalize(title + year)

                    if file_id == id:
                        url = get_cached_stream_url(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": file.name,
                            "url": url
                        })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
