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
        r"\.(mkv|mp4|avi|mov|webm|wmv).*",
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
            "is_video": f.get("play_video"),
            "available": f.get("is_ready"),
        })

    return result


# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "29.0.0",
        "name": "☁️ Seedr",

        "description": "Stream your Seedr files in Stremio",

        "resources": [
            "catalog",
            "meta",
            "stream"
        ],

        "types": [
            "movie"
        ],

        "idPrefixes": [
            "tt"
        ],

        "catalogs": [
            {
                "type": "movie",
                "id": "seedr",
                "name": "☁️ My Seedr Files"
            }
        ]
    }


# ---------------------------------------------------
# Catalog
# ---------------------------------------------------

@app.get("/catalog/movie/seedr.json")
def catalog():

    metas = []

    files = get_all_files()

    for f in files:

        if not f.get("play_video"):
            continue

        metas.append({
            "id": normalize(f["name"]),
            "type": "movie",
            "name": f["name"],

            "poster": f.get("thumb"),
            "posterShape": "poster",

            "description": f["name"],
        })

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

    print("DOWNLOAD STATUS:")
    print(response.status_code)

    print("DOWNLOAD RESPONSE:")
    print(response.text)

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

    if type != "movie":
        return {"streams": []}

    try:

        files = get_all_files()

        # ---------------------------------------------------
        # IMDb Movie Page Matching
        # ---------------------------------------------------

        if id.startswith("tt"):

            movie_title, movie_year = get_movie_title(id)

            print("MOVIE TITLE:", movie_title)
            print("MOVIE YEAR:", movie_year)

            target_title = normalize(movie_title)

            for f in files:

                if not f.get("play_video"):
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

                if not f.get("play_video"):
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
