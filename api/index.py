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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Upstash KV
# =========================

redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

BASE_TTL = 5 * 60 * 60     # 5 hours
HOT_TTL  = 12 * 60 * 60    # 12 hours


# =========================
# Seedr Client
# =========================

def get_client():
    code = os.environ.get("SEEDR_DEVICE_CODE")
    if not code:
        raise Exception("SEEDR_DEVICE_CODE missing")
    return Seedr.from_device_code(code)


# =========================
# Helpers
# =========================

def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def extract_title_year(filename: str):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year


def parse_quality(filename: str):
    f = filename.lower()
    quality = []

    if "2160p" in f or "4k" in f:
        quality.append("4K")
    elif "1080p" in f:
        quality.append("1080p")
    elif "720p" in f:
        quality.append("720p")

    if "hevc" in f or "x265" in f:
        quality.append("HEVC")
    elif "x264" in f:
        quality.append("x264")

    return " ".join(quality) if quality else "Unknown"


def get_movie_meta_from_cinemeta(title, year):
    try:
        q = requests.get(
            f"https://v3-cinemeta.strem.io/search/movie/{title}.json",
            timeout=10
        ).json()

        for m in q.get("metas", []):
            if str(m.get("year")) == str(year):
                return m
    except:
        pass
    return None


# =========================
# Cache Helper (Smart TTL)
# =========================

def get_cached_stream_url(client, file):
    key = f"seedr:stream:{file.folder_file_id}"
    now = int(time.time())

    cached = redis.get(key)
    if cached:
        cached = json.loads(cached)
        if cached["expires"] > now:
            print("KV HIT:", key)

            # Hot cache → extend TTL
            redis.expire(key, HOT_TTL)
            return cached["url"]

    print("KV MISS:", key)

    result = client.fetch_file(file.folder_file_id)

    data = {
        "url": result.url,
        "expires": now + BASE_TTL
    }

    redis.set(key, json.dumps(data), ex=BASE_TTL)
    return result.url


# =========================
# Routes
# =========================

@app.get("/")
def root():
    return {"status": "ok", "message": "Seedr Addon PRO running"}


@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "2.0.0",
        "name": "Seedr.cc PRO Addon",
        "description": "Fast Seedr streaming with cache, posters, quality tags",
        "resources": ["stream", "catalog", "meta"],
        "types": ["movie"],
        "catalogs": [{"type": "movie", "id": "seedr", "name": "My Seedr Library"}]
    }


@app.get("/catalog/movie/seedr.json")
def catalog():
    metas = []

    with get_client() as client:
        for f in client.list_contents().files:
            if not f.play_video:
                continue

            title, year = extract_title_year(f.name)
            cid = normalize(title + year)

            meta = get_movie_meta_from_cinemeta(title, year)

            metas.append({
                "id": cid,
                "type": "movie",
                "name": meta["name"] if meta else title,
                "year": year,
                "poster": meta.get("poster") if meta else None,
                "description": meta.get("description") if meta else "From Seedr"
            })

    return {"metas": metas}


@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    with get_client() as client:
        id_norm = normalize(id)

        for file in client.list_contents().files:
            if not file.play_video:
                continue

            fname_norm = normalize(file.name)
            title, year = extract_title_year(file.name)
            fid = normalize(title + year)

            if fid == id_norm or id_norm in fname_norm:
                print(f"PLAY: {title} ({year})")

                url = get_cached_stream_url(client, file)
                quality = parse_quality(file.name)

                streams.append({
                    "name": "Seedr.cc",
                    "title": f"{file.name} – {quality}",
                    "url": url,
                    "behaviorHints": {"notWebReady": False}
                })

    return {"streams": streams}
