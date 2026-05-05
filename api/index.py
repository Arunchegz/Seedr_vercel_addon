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
# CORS (Stremio friendly)
# -----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Upstash Redis
# -----------------------
redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

# -----------------------
# Seedr Client (FIXED)
# -----------------------
def get_client():
    access_token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not access_token:
        raise Exception("SEEDR_ACCESS_TOKEN missing")
    return Seedr(access_token=access_token)

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
    return meta.get("name", ""), str(meta.get("year", ""))

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
# KV Cache (24h)
# -----------------------
def get_cached_stream_url(client, file):
    key = f"seedr:stream:{file.folder_file_id}"

    cached = redis.get(key)
    if cached:
        cached = json.loads(cached)
        print("KV HIT:", key)
        return cached["url"]

    print("KV MISS:", key)

    result = client.fetch_file(file.folder_file_id)

    data = {"url": result.url}
    redis.set(key, json.dumps(data), ex=86400)

    return result.url

# -----------------------
# Root
# -----------------------
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Addon running (PAT auth + KV cache)"
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
        "description": "Stream your Seedr files in Stremio",
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
                "poster": None,
                "description": "From your Seedr account"
            })

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
        with get_client() as client:

            # IMDb match
            if id.startswith("tt"):
                movie_title, movie_year = get_movie_title(id)
                norm_title = normalize(movie_title)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    fname_norm = normalize(file.name)

                    if norm_title in fname_norm and movie_year in file.name:
                        url = get_cached_stream_url(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": file.name,
                            "url": url,
                            "behaviorHints": {"notWebReady": False}
                        })

            # Filename match
            else:
                id_norm = normalize(id)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    fname_norm = normalize(file.name)
                    title, year = extract_title_year(file.name)
                    file_id = normalize(title + year)

                    if file_id == id or fname_norm == id_norm or id_norm in fname_norm:
                        url = get_cached_stream_url(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": file.name,
                            "url": url,
                            "behaviorHints": {"notWebReady": False}
                        })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
