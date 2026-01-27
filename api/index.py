from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
import os
import re
import requests
import time

app = FastAPI()

# Allow Stremio + browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# In-Memory Cache
# -----------------------

STREAM_CACHE = {}
# Structure:
# {
#   folder_file_id: {
#       "url": "...",
#       "expires": unix_timestamp
#   }
# }

CACHE_TTL = 5 * 60 * 60  # 5 hours


def get_cached_stream_url(client, file):
    """
    Get Seedr stream URL from in-memory cache.
    If expired or missing, generate a new one and cache it.
    """
    key = file.folder_file_id
    now = int(time.time())

    cached = STREAM_CACHE.get(key)

    if cached and cached["expires"] > now:
        print("CACHE HIT:", key)
        return cached["url"]

    print("CACHE MISS:", key)

    # Generate new Seedr streaming URL
    result = client.fetch_file(file.folder_file_id)

    STREAM_CACHE[key] = {
        "url": result.url,
        "expires": now + CACHE_TTL
    }

    return result.url


# -----------------------
# Root
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Vercel Addon running (with in-memory cache)"
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
    """
    Get movie title + year from Stremio Cinemeta using IMDb ID
    """
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    meta = data.get("meta", {})
    title = meta.get("name", "")
    year = str(meta.get("year", ""))
    return title, year


def walk_files(client, folder_id=None):
    """
    Recursively walk through Seedr root and all subfolders
    and yield every file found.
    """
    contents = client.list_contents(folder_id=folder_id)

    for f in contents.files:
        yield f

    for folder in contents.folders:
        yield from walk_files(client, folder.id)


def extract_title_year(filename: str):
    """
    Try to extract title and year from a filename.
    Example:
      The.Matrix.1999.1080p.mkv -> ("The Matrix", "1999")
    """
    name = filename

    year_match = re.search(r"(19|20)\d{2}", name)
    year = year_match.group(0) if year_match else ""

    # Remove extension
    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", name, flags=re.I)
    # Remove year
    title = re.sub(r"(19|20)\d{2}", "", title)
    # Replace dots and underscores
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year


# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "1.0.0",
        "name": "Seedr.cc Personal Addon",
        "description": "Stream and browse your Seedr.cc files in Stremio (with in-memory cache)",
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
# Debug: See all files Seedr sees
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
# Catalog (Browse Seedr inside Stremio)
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
# Meta (Minimal)
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
# Stream endpoint
# Works for:
# 1. IMDb pages (ttxxxxxx)
# 2. "My Seedr Files" catalog entries
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        with get_client() as client:

            # CASE 1 → IMDb movie page
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
                            "behaviorHints": {
                                "notWebReady": False
                            }
                        })

            # CASE 2 → Playing from "My Seedr Files"
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
                            "url": url,
                            "behaviorHints": {
                                "notWebReady": False
                            }
                        })

    except Exception as e:
        return {
            "streams": [],
            "error": str(e)
        }

    return {"streams": streams}
