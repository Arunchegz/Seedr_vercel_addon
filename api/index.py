from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
from upstash_redis import Redis
import os
import re
import requests
import json
from typing import List, Dict, Optional, Generator, Tuple
from datetime import datetime

app = FastAPI(title="Seedr.cc Stremio Addon (Movies + Series)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upstash Redis
redis = Redis(
    url=os.environ.get("UPSTASH_KV_REST_API_URL"),
    token=os.environ.get("UPSTASH_KV_REST_API_TOKEN"),
)

def get_client() -> Seedr:
    device_code = os.environ.get("SEEDR_DEVICE_CODE")
    if not device_code:
        raise HTTPException(status_code=500, detail="SEEDR_DEVICE_CODE missing")
    return Seedr.from_device_code(device_code)

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())

def get_cinemeta_data(id: str, type_: str = "movie") -> Optional[Dict]:
    try:
        url = f"https://v3-cinemeta.strem.io/meta/{type_}/{id}.json"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("meta", {})
    except:
        return None

def walk_files(client: Seedr, folder_id: Optional[str] = None) -> Generator[any, None, None]:
    contents = client.list_contents(folder_id=folder_id)
    for f in contents.files:
        yield f
    for folder in contents.folders:
        yield from walk_files(client, folder.id)

def extract_title_year(filename: str) -> Tuple[str, str]:
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv|flv|srt).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = re.sub(r"\[.*?\]|\(.*?\)|\bS\d{2}E\d{2}\b|\bS\d+E\d+\b", "", title, flags=re.I)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title.strip(), year

def parse_episode_info(filename: str) -> Tuple[Optional[int], Optional[int]]:
    # Common patterns: S01E05, s1e7, Season 02 Episode 10, 1x13, etc.
    patterns = [
        r"[sS](\d{1,2})[eE](\d{1,2})",               # S01E05
        r"(\d{1,2})[xX](\d{1,2})",                    # 1x13
        r"[sS]eason\s*(\d{1,2}).*?[eE]pisode\s*(\d{1,2})",  # Season 2 Episode 3
        r"\b(\d{1,2})\s*[xX]\s*(\d{1,2})\b",          # 02x04
    ]
    for pat in patterns:
        m = re.search(pat, filename, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None

def get_quality_hint(filename: str) -> str:
    if re.search(r"4k|2160p|uhd", filename, re.I): return "4K"
    if re.search(r"1080p|fullhd|fhd", filename, re.I): return "1080p"
    if re.search(r"720p|hd", filename, re.I): return "720p"
    return ""

# ────────────────────────────────────────────────
# Cached Stream URL (24h)
# ────────────────────────────────────────────────

def get_cached_stream_url(client: Seedr, file: any) -> str:
    key = f"seedr:stream:{file.folder_file_id}"
    cached = redis.get(key)
    if cached:
        return json.loads(cached)["url"]

    result = client.fetch_file(file.folder_file_id)
    if not hasattr(result, "url") or not result.url:
        raise ValueError("No stream URL from Seedr")

    data = {"url": result.url}
    redis.set(key, json.dumps(data), ex=86400)
    return result.url

# ────────────────────────────────────────────────
# Cleanup
# ────────────────────────────────────────────────

def sync_kv_with_seedr(client: Seedr) -> Dict:
    seedr_ids = {str(f.folder_file_id) for f in walk_files(client)}
    keys = redis.keys("seedr:stream:*")
    deleted = 0
    for key in keys:
        fid = key.split(":")[-1]
        if fid not in seedr_ids:
            redis.delete(key)
            deleted += 1
    return {"total": len(keys), "deleted": deleted, "remaining": len(keys) - deleted}

# ────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "Seedr Addon – Movies & Series", "version": "1.8.0"}

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio.enhanced",
        "version": "1.8.0",
        "name": "Seedr.cc Personal (Movies + Series)",
        "description": "Stream your Seedr files • movies + TV series • cached links • auto cleanup",
        "resources": ["stream", "catalog", "meta"],
        "types": ["movie", "series"],
        "catalogs": [
            {"type": "movie", "id": "seedr-movies", "name": "My Seedr Movies"},
            {"type": "series", "id": "seedr-series", "name": "My Seedr Series"}
        ],
        "logo": "https://via.placeholder.com/256?text=Seedr",  # replace with real if desired
    }

# ── Movie Catalog ──────────────────────────────────────

@app.get("/catalog/movie/seedr-movies.json")
def catalog_movies():
    metas = []
    seen = set()

    with get_client() as client:
        for f in walk_files(client):
            if not f.play_video: continue
            title, year = extract_title_year(f.name)
            if not title: continue
            meta_id = normalize(title + year)
            if meta_id in seen: continue
            seen.add(meta_id)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title,
                "year": year or None,
                "poster": None,
                "description": "From your Seedr cloud",
            })

    return {"metas": metas}

# ── Series Catalog ─────────────────────────────────────

@app.get("/catalog/series/seedr-series.json")
def catalog_series():
    show_map: Dict[str, Dict] = {}  # normalized_key -> {name, year, id, seasons}

    with get_client() as client:
        for f in walk_files(client):
            if not f.play_video: continue

            title, year = extract_title_year(f.name)
            if not title: continue

            key = normalize(title + year)
            s, e = parse_episode_info(f.name)

            if key not in show_map:
                show_map[key] = {
                    "id": key,
                    "type": "series",
                    "name": title,
                    "year": year or None,
                    "poster": None,
                    "description": "TV series from your Seedr account",
                    "numberOfSeasons": 0,
                }

            if s:
                show_map[key]["numberOfSeasons"] = max(show_map[key].get("numberOfSeasons", 0), s)

    return {"metas": list(show_map.values())}

# ── Meta (movie + series) ──────────────────────────────

@app.get("/meta/{type_}/{id}.json")
def meta(type_: str, id: str):
    if type_ not in ("movie", "series"):
        raise HTTPException(404)

    title_parts = re.findall(r'[A-Za-z0-9]+', id)
    name = " ".join(title_parts[:-1]).title() if len(title_parts) > 1 else " ".join(title_parts).title()
    year_match = re.search(r'(\d{4})$', id)
    year = year_match.group(1) if year_match else ""

    poster = None
    description = f"Personal {type_} from Seedr.cc"

    # Try real metadata if looks like IMDb
    if id.startswith("tt") and len(id) in (9, 10):
        data = get_cinemeta_data(id, type_)
        if data:
            name = data.get("name", name)
            year = str(data.get("year", year))
            poster = data.get("poster")
            description = data.get("description", description)[:300]

    meta_obj = {
        "id": id,
        "type": type_,
        "name": name,
        "year": year,
        "poster": poster,
        "description": description,
        "released": f"{year}-01-01" if year else None,
    }

    if type_ == "series":
        meta_obj["numberOfSeasons"] = 1  # fallback; real value from catalog if available

    return {"meta": meta_obj}

# ── Stream (movie + series) ────────────────────────────

@app.get("/stream/{type_}/{id}.json")
async def stream(type_: str, id: str, request: Request):
    if type_ not in ("movie", "series"):
        return {"streams": []}

    season = None
    episode = None
    if type_ == "series":
        try:
            season = int(request.query_params.get("season", ""))
            episode = int(request.query_params.get("episode", ""))
        except:
            pass  # will fallback to title match only

    streams = []
    with get_client() as client:
        sync_kv_with_seedr(client)  # cleanup

        candidates = []

        search_norm = normalize(id)

        for file in walk_files(client):
            if not file.play_video: continue

            f_norm = normalize(file.name)
            title, year = extract_title_year(file.name)
            file_norm_title = normalize(title + year)

            score = 0
            if search_norm in f_norm or search_norm in file_norm_title:
                score += 10
            if year and year in file.name:
                score += 5

            s, e = parse_episode_info(file.name)
            if season is not None and episode is not None:
                if s == season and e == episode:
                    score += 30  # strong match
                elif s == season:
                    score += 10

            if score >= 10:
                candidates.append((score, file, title, year, s, e))

        # Sort: episode match > title match > size
        candidates.sort(key=lambda x: (-x[0], -x[1].size))

        for _, file, title, year, s, e in candidates[:6]:  # top 6
            try:
                url = get_cached_stream_url(client, file)
                quality = get_quality_hint(file.name) or "?"
                size_gb = round(file.size / (1024**3), 1)

                stream_title = file.name
                if type_ == "series" and s and e:
                    stream_title = f"S{s:02d}E{e:02d} • {title}"

                streams.append({
                    "name": f"Seedr • {quality} • {size_gb} GB",
                    "title": stream_title,
                    "url": url,
                    "behaviorHints": {"notWebReady": False},
                })
            except:
                pass

    return {"streams": streams}

# Debug
@app.get("/debug/sync")
def debug_sync():
    with get_client() as client:
        return sync_kv_with_seedr(client)

@app.get("/debug/files")
def debug_files():
    with get_client() as client:
        return [
            {
                "name": f.name,
                "size_gb": round(f.size / (1024**3), 2),
                "play_video": f.play_video,
                "season_episode": parse_episode_info(f.name)
            }
            for f in walk_files(client)
        ]
