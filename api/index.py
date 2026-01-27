from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
from upstash_redis import Redis
import os
import re
import requests
import time
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
# Upstash KV (Redis)
# -----------------------

redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

CACHE_TTL = 5 * 60 * 60  # 5 hours


def get_cached_stream_url(client, file):
    key = f"seedr:stream:{file.folder_file_id}"
    now = int(time.time())

    cached = redis.get(key)
    if cached:
        cached = json.loads(cached)
        if cached["expires"] > now:
            print("KV HIT:", key)
            return cached["url"]

    print("KV MISS:", key)

    result = client.fetch_file(file.folder_file_id)

    data = {
        "url": result.url,
        "expires": now + CACHE_TTL
    }

    redis.set(key, json.dumps(data), ex=CACHE_TTL)
    return result.url


# -----------------------
# Root
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Vercel Addon running (with quality tags)"
    }


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
# Step 1: Video quality parser
# -----------------------

def parse_quality(filename: str):
    f = filename.lower()
    tags = []

    # Resolution
    if "2160p" in f or "4k" in f:
        tags.append("4K")
    elif "1080p" in f:
        tags.append("1080p")
    elif "720p" in f:
        tags.append("720p")

    # Source
    if "web-dl" in f or "webdl" in f:
        tags.append("WEB-DL")
    elif "webrip" in f:
        tags.append("WEBRip")
    elif "bluray" in f or "brrip" in f:
        tags.append("BluRay")
    elif "hdrip" in f:
        tags.append("HDRip")

    # Video codec
    if "hevc" in f or "x265" in f:
        tags.append("HEVC")
    elif "x264" in f:
        tags.append("x264")
    elif "avc" in f:
        tags.append("AVC")

    # Audio codec
    if "ddp" in f or "eac3" in f:
        tags.append("DDP")
    elif "aac" in f:
        tags.append("AAC")
    elif "dts" in f:
        tags.append("DTS")

    # Channels
    if "5.1" in f:
        tags.append("5.1")
    elif "7.1" in f:
        tags.append("7.1")

    return " ".join(tags) if tags else "Unknown"


# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "1.7.0",
        "name": "Seedr.cc Personal Addon",
        "description": "Stream and browse your Seedr.cc files in Stremio (with quality tags)",
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
# Stream
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        with get_client() as client:

            # CASE 1 → IMDb ID
            if id.startswith("tt"):
                movie_title, movie_year = get_movie_title(id)
                norm_title = normalize(movie_title)

                for file in walk_files(client):
                    if not file.play_video:
                        continue

                    fname_norm = normalize(file.name)

                    if norm_title in fname_norm and movie_year in file.name:
                        url = get_cached_stream_url(client, file)
                        quality = parse_quality(file.name)

                        streams.append({
                            "name": "Seedr.cc",
                            "title": f"{file.name}  •  {quality}",
                            "url": url,
                            "behaviorHints": {"notWebReady": False}
                        })

            # CASE 2 → Catalog IDs + filename IDs
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
                        quality = parse_quality(file.name)

                        streams.append({
                            "name": "Seedr.cc",
                            "title": f"{file.name}  •  {quality}",
                            "url": url,
                            "behaviorHints": {"notWebReady": False}
                        })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
