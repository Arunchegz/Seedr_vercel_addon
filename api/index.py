from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re
import requests

from urllib.parse import unquote

app = FastAPI()

# ---------------------------------------------------
# CORS
# ---------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------
# Permanent Access Token
# ---------------------------------------------------

ACCESS_TOKEN = os.environ.get("SEEDR_ACCESS_TOKEN")

BASE_URL = "https://www.seedr.cc/api/v0.1/p"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json"
}

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def normalize(text: str):

    text = text.lower()

    text = re.sub(r"[^a-z0-9 ]", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def flexible_match(title: str, filename: str):
    title_n = normalize(title)
    file_n = normalize(filename)
    words = title_n.split()
    
    if not words:
        return False

    matched = sum(1 for w in words if w in file_n)

    if len(words) <= 2:
        required = len(words)
    else:
        required = max(2, len(words) // 2)

    return matched >= required


def get_meta(type_name: str, imdb_id: str):

    url = f"https://v3-cinemeta.strem.io/meta/{type_name}/{imdb_id}.json"

    r = requests.get(url, timeout=10)

    r.raise_for_status()

    data = r.json()

    meta = data.get("meta", {})

    title = meta.get("name", "")

    year = str(meta.get("year", ""))

    return title, year


def extract_title_year(filename: str):

    year_match = re.search(r"(19|20)\d{2}", filename)

    year = year_match.group(0) if year_match else ""

    title = re.sub(
        r"\.(mkv|mp4|avi|mov|webm|wmv|srt).*",
        "",
        filename,
        flags=re.I
    )

    title = re.sub(r"(19|20)\d{2}", "", title)

    title = re.sub(r"S\d{1,2}E\d{1,2}.*", "", title, flags=re.I)

    title = re.sub(r"\d{1,2}x\d{1,2}.*", "", title, flags=re.I)

    title = title.replace(".", " ")

    title = title.replace("_", " ")

    title = title.strip()

    return title, year


def extract_season_episode(filename: str):

    patterns = [
        r"S(\d{1,2})E(\d{1,2})",
        r"(\d{1,2})x(\d{1,2})",
    ]

    for pattern in patterns:

        match = re.search(pattern, filename, re.I)

        if match:
            return int(match.group(1)), int(match.group(2))

    return None, None


# ---------------------------------------------------
# Seedr API Helpers
# ---------------------------------------------------

def list_root_contents():

    response = requests.get(
        f"{BASE_URL}/fs/root/contents",
        headers=HEADERS,
        timeout=15
    )

    print("ROOT STATUS:", response.status_code)

    response.raise_for_status()

    return response.json()


def list_folder_contents(folder_id):

    response = requests.get(
        f"{BASE_URL}/fs/folder/{folder_id}/contents",
        headers=HEADERS,
        timeout=15
    )

    print("FOLDER STATUS:", response.status_code)

    response.raise_for_status()

    return response.json()


# ---------------------------------------------------
# Recursive folder walker
# ---------------------------------------------------

def walk_folder(folder_id):

    contents = list_folder_contents(folder_id)

    files = []

    # Files
    for f in contents.get("files", []):
        files.append(f)

    # Nested folders
    for folder in contents.get("folders", []):
        nested = walk_folder(folder["id"])
        files.extend(nested)

    return files


# ---------------------------------------------------
# Get all files
# ---------------------------------------------------

def get_all_files():

    root = list_root_contents()

    files = []

    # Root files
    for f in root.get("files", []):
        files.append(f)

    # Recursive folders
    for folder in root.get("folders", []):
        nested = walk_folder(folder["id"])
        files.extend(nested)

    return files


# ---------------------------------------------------
# Debug endpoint
# ---------------------------------------------------

@app.get("/debug/files")
def debug_files():

    files = get_all_files()

    result = []

    for f in files:

        season, episode = extract_season_episode(f.get("name", ""))

        result.append({
            "id": f.get("id"),
            "normalized_id": normalize(f.get("name", "")),
            "name": f.get("name"),
            "season": season,
            "episode": episode,
            "size": f.get("size"),
            "is_video": f.get("is_video"),
            "thumb": f.get("thumb"),
        })

    return result


# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "36.0.0",
        "name": "☁️ Seedr",

        "description": "Stream your Seedr files in Stremio",

        "resources": [
            "catalog",
            "meta",
            "stream"
        ],

        "types": [
            "movie",
            "series"
        ],

        "idPrefixes": [
            "tt",
            "seedr",
            "seedrseries"
        ],

        "catalogs": [
            {
                "type": "movie",
                "id": "seedr",
                "name": "☁️ Seedr Movies"
            },
            {
                "type": "series",
                "id": "seedr_series",
                "name": "☁️ Seedr Series"
            }
        ]
    }


# ---------------------------------------------------
# MOVIE CATALOG
# ---------------------------------------------------

@app.get("/catalog/movie/seedr.json")
def movie_catalog():

    metas = []
    files = get_all_files()

    for f in files:
        if not f.get("is_video"):
            continue

        season, episode = extract_season_episode(f["name"])

        # Skip TV episodes
        if season is not None:
            continue

        metas.append({
            # ADDED 'seedr:' PREFIX HERE
            "id": f"seedr:{normalize(f['name'])}", 
            "type": "movie",
            "name": f["name"],
            "poster": f.get("thumb"),
            "posterShape": "poster",
            "description": f["name"],
        })

    return {"metas": metas}
# ---------------------------------------------------
# SERIES CATALOG
# ---------------------------------------------------

@app.get("/catalog/series/seedr_series.json")
def series_catalog():

    metas = []

    files = get_all_files()

    added = set()

    for f in files:

        if not f.get("is_video"):
            continue

        season, episode = extract_season_episode(f["name"])

        # Only TV episodes
        if season is None:
            continue

        title, year = extract_title_year(f["name"])

        normalized = normalize(title)

        if normalized in added:
            continue

        added.add(normalized)

        metas.append({
            "id": f"seedrseries:{normalized}",
            "type": "series",
            "name": title,

            "poster": f.get("thumb"),
            "posterShape": "poster",

            "description": title
        })

    return {"metas": metas}


# ---------------------------------------------------
# META
# ---------------------------------------------------

@app.get("/meta/{type}/{id}.json")
def meta(type: str, id: str):

    print("META REQUEST:", type, id)

    # ---------------------------------------------------
    # IMDb Discover Support
    # ---------------------------------------------------

    if id.startswith("tt"):

        try:

            title, year = get_meta(type, id)

            return {
                "meta": {
                    "id": id,
                    "type": type,
                    "name": title,
                    "year": year,

                    "poster": "https://www.seedr.cc/images/seedr-logo.png",
                    "posterShape": "poster",

                    "description": title
                }
            }

        except Exception as e:

            print("IMDb META ERROR:", e)

            return {"meta": {}}

    # ---------------------------------------------------
    # Local Catalog Support
    # ---------------------------------------------------

    files = get_all_files()

    # ---------------------------------------------------
    # SERIES META
    # ---------------------------------------------------

    if type == "series":

        clean_id = id.replace("seedrseries:", "")

        episodes = []

        series_name = None

        added = set()

        for f in files:

            if not f.get("is_video"):
                continue

            parsed_title, _ = extract_title_year(
                f["name"]
            )

            normalized = normalize(parsed_title)

            if normalized != normalize(clean_id):
                continue

            season, episode = extract_season_episode(
                f["name"]
            )

            if season is None:
                continue

            series_name = parsed_title

            key = f"{season}-{episode}"

            if key in added:
                continue

            added.add(key)

            episodes.append({
                "id": (
                    f"seedrseries:{normalized}:"
                    f"{season}:{episode}"
                ),

                "title": (
                    f"S{season:02d}E{episode:02d}"
                ),

                "season": season,

                "episode": episode,

                "released": "2024-01-01T00:00:00.000Z"
            })

        # Sort episodes
        episodes.sort(
            key=lambda x: (
                x["season"],
                x["episode"]
            )
        )

        if episodes:

            return {
                "meta": {
                    "id": f"seedrseries:{clean_id}",

                    "type": "series",

                    "name": series_name,

                    "poster": (
                        "https://www.seedr.cc/"
                        "images/seedr-logo.png"
                    ),

                    "posterShape": "poster",

                    "description": series_name,

                    # IMPORTANT
                    "videos": episodes
                }
            }

# ---------------------------------------------------
# MOVIE META (Inside the @app.get("/meta/{type}/{id}.json") endpoint)
# ---------------------------------------------------

    else:
        # STRIP THE PREFIX FOR LOOKUP
        clean_id = id.replace("seedr:", "") if id.startswith("seedr:") else id

        for f in files:
            if not f.get("is_video"):
                continue

            # COMPARE WITH CLEAN ID
            if normalize(clean_id) == normalize(f["name"]):

                return {
                    "meta": {
                        # RETURN WITH PREFIX
                        "id": f"seedr:{normalize(f['name'])}", 
                        "type": "movie",
                        "name": f["name"],
                        "poster": f.get("thumb"),
                        "posterShape": "poster",
                        "description": f["name"]
                    }
                }


# ---------------------------------------------------
# Get Seedr direct URL
# ---------------------------------------------------

def get_seedr_download_url(file_id):

    response = requests.get(
        f"{BASE_URL}/download/file/{file_id}/url",
        headers=HEADERS,
        timeout=15
    )

    print("DOWNLOAD STATUS:", response.status_code)

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        return None

    return data.get("url")


# ---------------------------------------------------
# Detect quality
# ---------------------------------------------------

def detect_quality(filename):

    filename_lower = filename.lower()

    if "2160" in filename_lower or "4k" in filename_lower:
        return "4K"

    elif "1080" in filename_lower:
        return "1080p"

    elif "720" in filename_lower:
        return "720p"

    elif "480" in filename_lower:
        return "480p"

    return "Auto"


# ---------------------------------------------------
# STREAM
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):

    streams = []

    try:

        files = get_all_files()

        # ---------------------------------------------------
        # SERIES STREAMS
        # ---------------------------------------------------

        if type == "series":

            decoded_id = unquote(id)

            print("DECODED ID:", decoded_id)

            match = re.match(
                r"(seedrseries:[^:]+):(\d+):(\d+)",
                decoded_id
            )

            if not match:
                return {"streams": []}

            series_id = match.group(1)

            target_season = int(match.group(2))

            target_episode = int(match.group(3))

            # Local catalog
            if series_id.startswith("seedrseries:"):

                series_title = series_id.replace(
                    "seedrseries:",
                    ""
                )

                series_title = series_title.replace(
                    ".",
                    " "
                )

            print("SERIES TITLE:", series_title)

            print("TARGET SEASON:", target_season)

            print("TARGET EPISODE:", target_episode)

            for f in files:

                if not f.get("is_video"):
                    continue

                parsed_title, _ = extract_title_year(
                    f["name"]
                )

                season, episode = extract_season_episode(
                    f["name"]
                )

                if season is None:
                    continue

                if not flexible_match(
                    series_title,
                    parsed_title
                ):
                    continue

                if season != target_season:
                    continue

                if episode != target_episode:
                    continue

                print("MATCHED EPISODE:", f["name"])

                try:

                    direct_url = get_seedr_download_url(
                        f["id"]
                    )

                    if not direct_url:
                        continue

                    quality = detect_quality(
                        f["name"]
                    )

                    streams.append({
                        "name": "☁️ Seedr",

                        "title": (
                            f"📺 S{season:02d}E{episode:02d}\n"
                            f"⚡ {quality}\n"
                            f"📁 {f['name']}"
                        ),

                        "url": direct_url,

                        "behaviorHints": {
                            "notWebReady": False
                        }
                    })

                except Exception as e:

                    print("STREAM ERROR:", e)

# ---------------------------------------------------
# MOVIE STREAMS (Inside the @app.get("/stream/{type}/{id}.json") endpoint)
# ---------------------------------------------------

        elif type == "movie":

            # IMDb Matching
            if id.startswith("tt"):
                # ... (Keep your existing IMDb code here) ...
                pass 

            # Personal Catalog Matching
            else:
                # STRIP THE PREFIX FOR LOOKUP
                clean_id = id.replace("seedr:", "") if id.startswith("seedr:") else id

                for f in files:

                    if not f.get("is_video"):
                        continue

                    # COMPARE WITH CLEAN ID
                    if normalize(clean_id) != normalize(f["name"]):
                        continue

                    try:
                        direct_url = get_seedr_download_url(f["id"])

                        if not direct_url:
                            continue

                        quality = detect_quality(f["name"])

                        streams.append({
                            "name": "☁️ Seedr",
                            "title": (
                                f"⚡ {quality}\n"
                                f"📁 {f['name']}"
                            ),
                            "url": direct_url,
                            "behaviorHints": {
                                "notWebReady": False
                            }
                        })

                    except Exception as e:
                        print("STREAM ERROR:", e)

    except Exception as e:

        print("MAIN STREAM ERROR:", e)

    print("TOTAL STREAMS:", len(streams))

    return {"streams": streams}
