from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
import os
import re
import requests
from collections import defaultdict

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
# Seedr Client
# -----------------------
def get_client():
    device_code = os.environ.get("SEEDR_DEVICE_CODE")
    if not device_code:
        raise Exception("SEEDR_DEVICE_CODE missing")
    return Seedr.from_device_code(device_code)

# -----------------------
# Helpers
# -----------------------
def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def extract_title_year(filename: str):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

def extract_season_episode(name: str):
    patterns = [
        r"S(\d{1,2})E(\d{1,2})",
        r"(\d{1,2})x(\d{1,2})",
        r"Season\s*(\d{1,2}).*Episode\s*(\d{1,2})"
    ]

    for p in patterns:
        m = re.search(p, name, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None

def walk_files(client, folder_id=None):
    contents = client.list_contents(folder_id=folder_id)

    for f in contents.files:
        yield f

    for folder in contents.folders:
        yield from walk_files(client, folder.id)

def get_meta(type_: str, imdb_id: str):
    url = f"https://v3-cinemeta.strem.io/meta/{type_}/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()["meta"]

def get_fresh_stream_url(client, file):
    return client.fetch_file(file.folder_file_id).url

# -----------------------
# Root
# -----------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Seedr Stremio Addon (Movies + Series)"}

# -----------------------
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "3.0.0",
        "name": "Seedr.cc Personal Addon",
        "description": "Stream movies & series from Seedr.cc",
        "resources": ["stream", "catalog", "meta"],
        "types": ["movie", "series"],
        "catalogs": [
            {"type": "movie", "id": "seedr_movies", "name": "My Movies"},
            {"type": "series", "id": "seedr_series", "name": "My Series"}
        ]
    }

# -----------------------
# Catalog
# -----------------------
@app.get("/catalog/{type}/{id}.json")
def catalog(type: str, id: str):
    metas = []
    seen_series = set()

    with get_client() as client:
        for file in walk_files(client):
            if not file.play_video:
                continue

            name = file.name

            # Movies
            if type == "movie":
                title, year = extract_title_year(name)
                metas.append({
                    "id": f"seedr:{file.folder_file_id}",
                    "type": "movie",
                    "name": title or name,
                    "year": year
                })

            # Series
            elif type == "series":
                season, episode = extract_season_episode(name)
                if season is None:
                    continue

                series_title = re.split(r"S\d{1,2}E\d{1,2}|\d+x\d+", name, flags=re.I)[0]
                series_title = series_title.replace(".", " ").strip()

                norm = normalize(series_title)
                if norm in seen_series:
                    continue

                seen_series.add(norm)

                metas.append({
                    "id": f"seedr_series:{norm}",
                    "type": "series",
                    "name": series_title
                })

    return {"metas": metas}

# -----------------------
# Meta (Series Seasons)
# -----------------------
@app.get("/meta/series/{id}.json")
def series_meta(id: str):
    seasons = defaultdict(set)

    with get_client() as client:
        for file in walk_files(client):
            season, episode = extract_season_episode(file.name)
            if season:
                seasons[season].add(episode)

    return {
        "meta": {
            "id": id,
            "type": "series",
            "name": id,
            "videos": [
                {
                    "id": f"{id}:{s}:{e}",
                    "season": s,
                    "episode": e,
                    "title": f"S{s:02d}E{e:02d}"
                }
                for s in sorted(seasons)
                for e in sorted(seasons[s])
            ]
        }
    }

# -----------------------
# Stream (Movies + Episodes)
# -----------------------
@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    with get_client() as client:
        # ---------------- Movies ----------------
        if type == "movie":
            for file in walk_files(client):
                if f"seedr:{file.folder_file_id}" == id:
                    streams.append({
                        "name": "Seedr.cc",
                        "title": file.name,
                        "url": get_fresh_stream_url(client, file)
                    })
                    break

        # ---------------- Episodes ----------------
        elif type == "series":
            _, season, episode = id.split(":")
            season = int(season)
            episode = int(episode)

            for file in walk_files(client):
                s, e = extract_season_episode(file.name)
                if s == season and e == episode:
                    streams.append({
                        "name": "Seedr.cc",
                        "title": file.name,
                        "url": get_fresh_stream_url(client, file)
                    })
                    break

    return {"streams": streams}