from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
from upstash_redis import Redis
import os
import re
import requests
import json

app = FastAPI()

# Allow Stremio + browser access
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

CACHE_TTL = 60 * 60 * 24  # 24 hours


# -----------------------
# Seedr Client
# -----------------------

def get_client():
    device_code = os.environ.get("SEEDR_DEVICE_CODE")
    if not device_code:
        raise Exception("SEEDR_DEVICE_CODE environment variable is missing")
    return Seedr.from_device_code(device_code)


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
# KV Storage (with metadata + 24h TTL)
# -----------------------

def get_cached_stream_data(client, file):
    key = f"seedr:stream:{file.folder_file_id}"

    cached = redis.get(key)
    if cached:
        print("KV HIT:", key)
        return json.loads(cached)

    print("KV MISS:", key)

    result = client.fetch_file(file.folder_file_id)

    title, year = extract_title_year(file.name)
    meta_id = normalize(title + year)

    data = {
        "url": result.url,
        "name": file.name,
        "title": title,
        "year": year,
        "meta_id": meta_id
    }

    redis.set(key, json.dumps(data), ex=CACHE_TTL)
    return data


# -----------------------
# Sync KV with Seedr
# -----------------------

def sync_kv_with_seedr(client):
    seedr_ids = set(str(f.folder_file_id) for f in walk_files(client))
    keys = redis.keys("seedr:stream:*")

    deleted = []

    for key in keys:
        file_id = key.split(":")[-1]
        if file_id not in seedr_ids:
            redis.delete(key)
            deleted.append(key)
            print("KV DELETE (file removed):", key)

    return {
        "total_keys": len(keys),
        "deleted": deleted,
        "remaining": len(keys) - len(deleted)
    }


# -----------------------
# Root
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Vercel Addon running (KV-first, 24h TTL, catalog-safe)"
    }


# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "1.7.2",
        "name": "Seedr.cc Personal Addon",
        "description": "Stream and browse your Seedr.cc files in Stremio (KV-first, 24h cache, auto cleanup)",
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
# Debug
# -----------------------

@app.get("/debug/files")
def debug_files():
    with get_client() as client:
        return [
            {
                "file_id": f.file_id,
                "folder_file_id": f.folder_file_id,
                "name": f.name,
                "size": f.size,
                "play_video": f.play_video
            }
            for f in walk_files(client)
        ]


@app.get("/debug/sync")
def debug_sync():
    with get_client() as client:
        result = sync_kv_with_seedr(client)
        return {
            "status": "ok",
            "message": "KV synced with Seedr cloud",
            "result": result
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
                "description": "From your Seedr.cc account"
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
# Stream (KV FIRST → Seedr fallback)
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    print("STREAM REQUEST:", type, id)
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        # ---------------------------------
        # 1. Use KV only for catalog IDs
        # ---------------------------------
        if not id.startswith("tt"):
            keys = redis.keys("seedr:stream:*")

            for key in keys:
                cached = redis.get(key)
                if not cached:
                    continue

                data = json.loads(cached)

                if data["meta_id"] == id:
                    streams.append({
                        "name": "Seedr.cc",
                        "title": data["name"],
                        "url": data["url"],
                        "behaviorHints": {"notWebReady": False}
                    })

            if streams:
                print("KV HIT (catalog) → Seedr API not called")
                return {"streams": streams}

        # ---------------------------------
        # 2. Fallback to Seedr API
        # ---------------------------------
        print("Calling Seedr API")

        with get_client() as client:
            sync_kv_with_seedr(client)

            # IMDb matching (TITLE ONLY, YEAR OPTIONAL)
            if id.startswith("tt"):
                movie_title, movie_year = get_movie_title(id)
                norm_title = normalize(movie_title)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    fname_norm = normalize(file.name)

                    # Title match is enough
                    if norm_title in fname_norm:
                        data = get_cached_stream_data(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": data["name"],
                            "url": data["url"],
                            "behaviorHints": {"notWebReady": False}
                        })

            # Catalog / filename matching
            else:
                id_norm = normalize(id)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    fname_norm = normalize(file.name)
                    title, year = extract_title_year(file.name)
                    file_id = normalize(title + year)

                    if file_id == id or fname_norm == id_norm or id_norm in fname_norm:
                        data = get_cached_stream_data(client, file)
                        streams.append({
                            "name": "Seedr.cc",
                            "title": data["name"],
                            "url": data["url"],
                            "behaviorHints": {"notWebReady": False}
                        })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
