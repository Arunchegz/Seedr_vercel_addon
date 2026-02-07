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
# Upstash KV (24h expiry)
# -----------------------

redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

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

def extract_season_episode(filename: str):
    """
    Detect S01E02 or 1x02 formats
    """
    match = re.search(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,2})", filename)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(r"(\d{1,2})x(\d{1,2})", filename)
    if match:
        return int(match.group(1)), int(match.group(2))

    return None, None

# -----------------------
# Cinemeta Fetch
# -----------------------

def get_movie_title(imdb_id: str):
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    meta = data.get("meta", {})
    title = meta.get("name", "")
    year = str(meta.get("year", ""))
    return title, year

def get_series_episode_info(stremio_id: str):
    """
    stremio_id format: tt0944947:1:1
    returns: series_title, season, episode
    """
    parts = stremio_id.split(":")
    if len(parts) != 3:
        return None, None, None

    imdb_id = parts[0]
    season = int(parts[1])
    episode = int(parts[2])

    url = f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    meta = data.get("meta", {})
    series_title = meta.get("name", "")

    return series_title, season, episode

# -----------------------
# Permanent KV Storage
# -----------------------

def get_cached_stream_url(client, file):
    """
    Stores Seedr URLs in Upstash with 24 hours expiry.
    """
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
        "message": "Seedr Vercel Addon running (Movies + Series supported)"
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
        "description": "Stream your Seedr.cc files in Stremio (Movies + Series + Auto KV cleanup)",
        "resources": ["stream", "catalog", "meta"],
        "types": ["movie", "series"],
        "catalogs": [
            {
                "type": "movie",
                "id": "seedr_movies",
                "name": "My Seedr Movies"
            },
            {
                "type": "series",
                "id": "seedr_series",
                "name": "My Seedr Series"
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
# Catalog (Movies)
# -----------------------

@app.get("/catalog/movie/seedr_movies.json")
def catalog_movies():
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
# Catalog (Series)
# -----------------------

@app.get("/catalog/series/seedr_series.json")
def catalog_series():
    metas = []

    seen = set()

    with get_client() as client:
        for f in walk_files(client):
            if not f.play_video:
                continue

            season, episode = extract_season_episode(f.name)
            if season is None:
                continue

            # Guess series name (remove SxxExx part)
            name = re.sub(r"[Ss]\d{1,2}[ ._-]*[Ee]\d{1,2}", "", f.name)
            name = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", name, flags=re.I)
            name = name.replace(".", " ").replace("_", " ").strip()

            series_id = normalize(name)

            if series_id in seen:
                continue

            seen.add(series_id)

            metas.append({
                "id": series_id,
                "type": "series",
                "name": name,
                "poster": None,
                "description": "From your Seedr.cc account"
            })

    return {"metas": metas}

# -----------------------
# Meta (Movie / Series)
# -----------------------

@app.get("/meta/{type}/{id}.json")
def meta(type: str, id: str):
    return {
        "meta": {
            "id": id,
            "type": type,
            "name": id
        }
    }

# -----------------------
# Stream (Movie / Series)
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    try:
        with get_client() as client:

            # Auto-clean KV entries for removed files
            sync_kv_with_seedr(client)

            # -----------------------
            # MOVIE STREAMS
            # -----------------------
            if type == "movie":

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

            # -----------------------
            # SERIES STREAMS
            # -----------------------
            elif type == "series":

                # Stremio series stream id is like: tt0944947:1:1
                if id.startswith("tt") and ":" in id:
                    series_title, season, episode = get_series_episode_info(id)

                    if not series_title:
                        return {"streams": []}

                    norm_series = normalize(series_title)

                    for file in walk_files(client):
                        if not file.play_video:
                            continue

                        fname_norm = normalize(file.name)

                        f_season, f_episode = extract_season_episode(file.name)

                        if f_season is None:
                            continue

                        if f_season == season and f_episode == episode and norm_series in fname_norm:
                            url = get_cached_stream_url(client, file)
                            streams.append({
                                "name": "Seedr.cc",
                                "title": file.name,
                                "url": url,
                                "behaviorHints": {"notWebReady": False}
                            })

            else:
                return {"streams": []}

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}