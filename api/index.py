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
    return re.sub(r"[^a-z0-9]", "", text.lower())


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

    # Remove episode tags
    title = re.sub(r"S\d{1,2}E\d{1,2}.*", "", title, flags=re.I)
    title = re.sub(r"\d{1,2}x\d{1,2}.*", "", title, flags=re.I)

    # Remove IMDb ID
    title = re.sub(r"tt\d{7,9}", "", title, flags=re.I)

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

        season, episode = extract_season_episode(f.get("name", ""))

        result.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "season": season,
            "episode": episode,
            "is_video": f.get("is_video"),
        })

    return result


# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "33.0.0",
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
            "id": normalize(f["name"]),
            "type": "movie",
            "name": f["name"],

            "poster": f.get("thumb"),
            "posterShape": "poster",

            "description": f["name"],
        })

    print("MOVIE CATALOG ITEMS:", len(metas))

    return {"metas": metas}


# ---------------------------------------------------
# SERIES CATALOG
# IMPORTANT:
# Filenames MUST contain IMDb ID
# Example:
# The.Mandalorian.tt8111088.S01E01.mkv
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

        if season is None:
            continue

        filename = f["name"]

        imdb_match = re.search(r"(tt\d{7,9})", filename)

        if not imdb_match:
            continue

        imdb_id = imdb_match.group(1)

        if imdb_id in added:
            continue

        added.add(imdb_id)

        try:

            series_title, year = get_meta("series", imdb_id)

        except Exception as e:

            print("CINEMETA ERROR:", e)

            continue

        metas.append({
            "id": imdb_id,
            "type": "series",
            "name": series_title,

            "poster": f.get("thumb"),
            "posterShape": "poster",

            "description": series_title
        })

    print("SERIES CATALOG ITEMS:", len(metas))

    return {"metas": metas}


# ---------------------------------------------------
# META
# ---------------------------------------------------

@app.get("/meta/{type}/{id}.json")
def meta(type: str, id: str):

    files = get_all_files()

    for f in files:

        if not f.get("is_video"):
            continue

        # ---------------------------------------------------
        # SERIES META
        # ---------------------------------------------------

        if type == "series":

            imdb_match = re.search(r"(tt\d{7,9})", f["name"])

            if not imdb_match:
                continue

            imdb_id = imdb_match.group(1)

            if imdb_id != id:
                continue

            try:

                series_title, year = get_meta("series", imdb_id)

            except:
                continue

            return {
                "meta": {
                    "id": imdb_id,
                    "type": "series",
                    "name": series_title,

                    "poster": f.get("thumb"),
                    "posterShape": "poster",

                    "description": series_title
                }
            }

        # ---------------------------------------------------
        # MOVIE META
        # ---------------------------------------------------

        else:

            if normalize(id) == normalize(f["name"]):

                return {
                    "meta": {
                        "id": normalize(f["name"]),
                        "type": "movie",
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

            # Example:
            # tt8111088%3A1%3A1
            # ->
            # tt8111088:1:1

            decoded_id = unquote(id)

            print("DECODED ID:", decoded_id)

            match = re.match(r"(tt\d+):(\d+):(\d+)", decoded_id)

            if not match:
                return {"streams": []}

            imdb_id = match.group(1)

            target_season = int(match.group(2))
            target_episode = int(match.group(3))

            print("IMDB ID:", imdb_id)
            print("SEASON:", target_season)
            print("EPISODE:", target_episode)

            for f in files:

                if not f.get("is_video"):
                    continue

                filename = f["name"]

                imdb_match = re.search(r"(tt\d{7,9})", filename)

                if not imdb_match:
                    continue

                file_imdb_id = imdb_match.group(1)

                if file_imdb_id != imdb_id:
                    continue

                season, episode = extract_season_episode(filename)

                if season is None:
                    continue

                if season != target_season:
                    continue

                if episode != target_episode:
                    continue

                print("MATCHED EPISODE:", filename)

                try:

                    direct_url = get_seedr_download_url(f["id"])

                    if not direct_url:
                        continue

                    quality = detect_quality(filename)

                    streams.append({
                        "name": "☁️ Seedr",

                        "title": (
                            f"📺 S{season:02d}E{episode:02d}\n"
                            f"⚡ {quality}\n"
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

        # ---------------------------------------------------
        # MOVIE STREAMS
        # ---------------------------------------------------

        elif type == "movie":

            if id.startswith("tt"):

                movie_title, movie_year = get_meta("movie", id)

                print("MOVIE TITLE:", movie_title)
                print("MOVIE YEAR:", movie_year)

                target_title = normalize(movie_title)

                for f in files:

                    if not f.get("is_video"):
                        continue

                    parsed_title, parsed_year = extract_title_year(f["name"])

                    normalized_file_title = normalize(parsed_title)

                    # Skip TV episodes
                    season, episode = extract_season_episode(f["name"])

                    if season is not None:
                        continue

                    if target_title not in normalized_file_title:
                        continue

                    if movie_year and parsed_year:
                        if movie_year != parsed_year:
                            continue

                    print("MATCHED MOVIE:", f["name"])

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

            else:

                for f in files:

                    if not f.get("is_video"):
                        continue

                    if normalize(id) != normalize(f["name"]):
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

                        print("STREAM ERROR:")
                        print(e)

    except Exception as e:

        print("MAIN STREAM ERROR:")
        print(e)

    print("TOTAL STREAMS:", len(streams))

    return {"streams": streams}
