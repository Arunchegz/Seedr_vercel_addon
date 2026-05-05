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
# Redis
# -----------------------
redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

# -----------------------
# Seedr API Client
# -----------------------
class SeedrClient:
    def __init__(self, token):
        self.token = token
        self.base = "https://www.seedr.cc/api/v0.1"

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}"
        }

    def list_contents(self, folder_id=None):
        url = f"{self.base}/folder"
        params = {}
        if folder_id:
            params["folder_id"] = folder_id

        res = requests.get(url, headers=self.headers(), params=params)
        res.raise_for_status()
        return res.json()

    def fetch_file(self, file_id):
        url = f"{self.base}/file/{file_id}"
        res = requests.get(url, headers=self.headers())
        res.raise_for_status()
        return res.json()


def get_client():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("SEEDR_ACCESS_TOKEN missing")
    return SeedrClient(token)

# -----------------------
# Helpers
# -----------------------
def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def get_movie_title(imdb_id):
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    meta = r.json().get("meta", {})
    return meta.get("name", ""), str(meta.get("year", ""))

def walk_files(client, folder_id=None):
    contents = client.list_contents(folder_id)

    for f in contents.get("files", []):
        yield f

    for folder in contents.get("folders", []):
        yield from walk_files(client, folder.get("id"))

def extract_title_year(filename):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

# -----------------------
# Cache
# -----------------------
def get_cached_stream_url(client, file):
    file_id = file.get("id") or file.get("folder_file_id")
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
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "3.1.0",
        "name": "Seedr Personal Addon",
        "description": "Stream Seedr files in Stremio",
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
    client = get_client()

    try:
        data = client.list_contents()
        print("Seedr response:", data)

        for f in walk_files(client):
            print("FILE:", f)

            name = f.get("name")
            if not name:
                continue

            # fallback: assume video if extension matches
            if not f.get("play_video", True):
                if not re.search(r"\.(mkv|mp4|avi|mov|webm|wmv)$", name, re.I):
                    continue

            title, year = extract_title_year(name)
            meta_id = normalize(title + year)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title or name,
                "year": year,
                "poster": None
            })

    except Exception as e:
        print("ERROR:", str(e))
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
        # IMDb match
        if id.startswith("tt"):
            title, year = get_movie_title(id)
            norm_title = normalize(title)

            for f in walk_files(client):
                name = f.get("name", "")
                if not name:
                    continue

                fname_norm = normalize(name)

                if norm_title in fname_norm and year in name:
                    url = get_cached_stream_url(client, f)
                    streams.append({
                        "name": "Seedr",
                        "title": name,
                        "url": url,
                        "behaviorHints": {"notWebReady": False}
                    })

        else:
            id_norm = normalize(id)

            for f in walk_files(client):
                name = f.get("name", "")
                if not name:
                    continue

                fname_norm = normalize(name)
                title, year = extract_title_year(name)
                file_id = normalize(title + year)

                if file_id == id or id_norm in fname_norm:
                    url = get_cached_stream_url(client, f)
                    streams.append({
                        "name": "Seedr",
                        "title": name,
                        "url": url,
                        "behaviorHints": {"notWebReady": False}
                    })

    except Exception as e:
        print("STREAM ERROR:", str(e))
        return {"streams": [], "error": str(e)}

    return {"streams": streams}

# -----------------------
# Debug
# -----------------------
@app.get("/debug/files")
def debug_files():
    client = get_client()
    return list(walk_files(client))

@app.get("/debug/cache")
def debug_cache():
    keys = redis.keys("seedr:stream:*")
    return {"total": len(keys), "keys": keys}
