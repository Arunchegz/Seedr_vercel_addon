from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re
import requests

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

    title = title.replace(".", " ")
    title = title.replace("_", " ")

    title = title.strip()

    return title, year


# ---------------------------------------------------
# Detect season/episode
# ---------------------------------------------------

def extract_season_episode(filename):

    match = re.search(r"[Ss](\d+)[Ee](\d+)", filename)

    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(r"(\d+)x(\d+)", filename)

    if match:
        return int(match.group(1)), int(match.group(2))

    return None, None


def is_series_file(filename):

    season, episode = extract_season_episode(filename)

    return season is not None


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
    print("ROOT RESPONSE:", response.text)

    response.raise_for_status()

    return response.json()


def list_folder_contents(folder_id):

    response = requests.get(
        f"{BASE_URL}/fs/folder/{folder_id}/contents",
        headers=HEADERS,
        timeout=15
    )

    print("FOLDER STATUS:", response.status_code)
    print("FOLDER RESPONSE:", response.text)

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

        result.append({
            "id": f.get("id"),
            "normalized_id": normalize(f.get("name", "")),
            "name": f.get("name"),
            "size": f.get("size"),
            "is_video": f.get("is_video"),
            "thumb": f.get("thumb"),
            "is_series": is_series_file(f.get("name", ""))
        })

    return result


# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "31.0.0",
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
            "tt"
        ],

        "catalogs": [
            {
                "type": "movie",
                "id": "seedr_movies",
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
# Catalog
# ---------------------------------------------------

@app.get("/catalog/{type}/{id}.json")
def catalog(type: str, id: str):

    metas = []

    files = get_all_files()

    for f in files:

        if not f.get("is_video"):
            continue

        filename = f["name"]

        series_file = is_series_file(filename)

        # Movies only
        if type == "movie" and series_file:
            continue

        # Series only
        if type == "series" and not series_file:
            continue

        metas.append({
            "id": normalize(filename),
            "type": type,
            "name": filename,

            "poster": f.get("thumb"),
            "posterShape": "poster",

            "description": filename,
        })

    print("CATALOG ITEMS:", len(metas))

    return {"metas": metas}


# ---------------------------------------------------
# Meta
# ---------------------------------------------------

@app.get("/meta/{type}/{id}.json")
def meta(type: str, id: str):

    files = get_all_files()

    for f in files:

        if normalize(id) == normalize(f["name"]):

            return {
                "meta": {
                    "id": normalize(f["name"]),
                    "type": type,
                    "name": f["name"],

                    "poster": f.get("thumb"),
                    "posterShape": "poster",

                    "description": f["name"]
                }
            }

    return {"meta": {}}


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
    print("DOWNLOAD RESPONSE:", response.text)

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
# Stream
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):

    streams = []

    if type not in ["movie", "series"]:
        return {"streams": []}

    try:

        files = get_all_files()

        # ---------------------------------------------------
        # IMDb Matching (Movies only)
        # ---------------------------------------------------

        if type == "movie" and id.startswith("tt"):

            movie_title, movie_year = get_movie_title(id)

            print("MOVIE TITLE:", movie_title)
            print("MOVIE YEAR:", movie_year)

            target_title = normalize(movie_title)

            for f in files:

                if not f.get("is_video"):
                    continue

                if is_series_file(f["name"]):
                    continue

                parsed_title, parsed_year = extract_title_year(f["name"])

                normalized_file_title = normalize(parsed_title)

                # Match title
                if target_title not in normalized_file_title:
                    continue

                # Match year
                if movie_year and parsed_year:
                    if movie_year != parsed_year:
                        continue

                print("MATCHED:", f["name"])

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

                    print("STREAM ERROR:")
                    print(e)

        # ---------------------------------------------------
        # Personal Catalog Matching
        # ---------------------------------------------------

        else:

            for f in files:

                if not f.get("is_video"):
                    continue

                filename = f["name"]

                if type == "series" and not is_series_file(filename):
                    continue

                if type == "movie" and is_series_file(filename):
                    continue

                if normalize(id) != normalize(filename):
                    continue

                try:

                    direct_url = get_seedr_download_url(f["id"])

                    if not direct_url:
                        continue

                    quality = detect_quality(filename)

                    season, episode = extract_season_episode(filename)

                    extra = ""

                    if season and episode:
                        extra = f"\n📺 S{season:02d}E{episode:02d}"

                    streams.append({
                        "name": "☁️ Seedr",

                        "title": (
                            f"⚡ {quality}"
                            f"{extra}\n"
                            f"📁 {filename}"
                        ),

                        "url": direct_url,

                        "behaviorHints": {
                            "notWebReady": False
                        }
                    })

                except Exception as e:

                    print("STREAM ERROR:")
                    print(e)

    except Exception as e:

        print("MAIN STREAM ERROR:")
        print(e)

    print("TOTAL STREAMS:", len(streams))

    return {"streams": streams}
