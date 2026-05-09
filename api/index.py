from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re
import requests

from seedr_api import SeedrClient

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
# Get client
# ---------------------------------------------------

async def get_client():

    return SeedrClient.from_token(ACCESS_TOKEN)


# ---------------------------------------------------
# Recursive folder walker
# ---------------------------------------------------

async def walk_folder(client, folder_id):

    contents = await client.filesystem.list_folder_contents(folder_id)

    files = []

    # Files
    for f in contents.files or []:
        files.append(f)

    # Recursive folders
    for folder in contents.folders or []:
        nested = await walk_folder(client, folder.id)
        files.extend(nested)

    return files


# ---------------------------------------------------
# Get all files
# ---------------------------------------------------

async def get_all_files():

    async with await get_client() as client:

        root = await client.filesystem.list_root_contents()

        files = []

        # Root files
        for f in root.files or []:
            files.append(f)

        # Recursive folders
        for folder in root.folders or []:
            nested = await walk_folder(client, folder.id)
            files.extend(nested)

        return files


# ---------------------------------------------------
# Debug endpoint
# ---------------------------------------------------

@app.get("/debug/files")
async def debug_files():

    files = await get_all_files()

    result = []

    for f in files:

        result.append({
            "id": f.id,
            "normalized_id": normalize(f.name),
            "name": f.name,
            "size": f.size,
            "is_video": f.is_video,
            "available": f.is_available,
            "video_progress": f.video_progress,
        })

    return result


# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "28.0.0",
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
async def catalog():

    metas = []

    files = await get_all_files()

    for f in files:

        if not f.is_video:
            continue

        poster = None

        try:
            poster = f.thumb
        except:
            pass

        metas.append({
            "id": normalize(f.name),
            "type": "movie",
            "name": f.name,

            "poster": poster,
            "posterShape": "poster",

            "description": f.name,
        })

    return {"metas": metas}


# ---------------------------------------------------
# Meta
# ---------------------------------------------------

@app.get("/meta/{type}/{id}.json")
async def meta(type: str, id: str):

    files = await get_all_files()

    for f in files:

        if normalize(id) == normalize(f.name):

            poster = None

            try:
                poster = f.thumb
            except:
                pass

            return {
                "meta": {
                    "id": normalize(f.name),
                    "type": "movie",
                    "name": f.name,

                    "poster": poster,
                    "posterShape": "poster",

                    "description": f.name
                }
            }

    return {"meta": {}}


# ---------------------------------------------------
# Get Seedr direct URL
# ---------------------------------------------------

def get_seedr_download_url(file_id):

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json"
    }

    response = requests.get(
        f"https://www.seedr.cc/api/v0.1/p/download/file/{file_id}/url",
        headers=headers,
        timeout=15
    )

    print("DOWNLOAD STATUS:")
    print(response.status_code)

    print("DOWNLOAD RESPONSE:")
    print(response.text)

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
async def stream(type: str, id: str):

    streams = []

    if type != "movie":
        return {"streams": []}

    try:

        files = await get_all_files()

        # ---------------------------------------------------
        # IMDb Movie Page Matching
        # ---------------------------------------------------

        if id.startswith("tt"):

            movie_title, movie_year = get_movie_title(id)

            print("MOVIE TITLE:", movie_title)
            print("MOVIE YEAR:", movie_year)

            target_title = normalize(movie_title)

            for f in files:

                if not f.is_video:
                    continue

                parsed_title, parsed_year = extract_title_year(f.name)

                normalized_file_title = normalize(parsed_title)

                # Match title
                if target_title not in normalized_file_title:
                    continue

                # Match year
                if movie_year and parsed_year:
                    if movie_year != parsed_year:
                        continue

                print("MATCHED:", f.name)

                try:

                    direct_url = get_seedr_download_url(f.id)

                    if not direct_url:
                        continue

                    quality = detect_quality(f.name)

                    streams.append({
                        "name": "☁️ Seedr",

                        "title": (
                            f"⚡ {quality}\n"
                            f"📁 {f.name}"
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

                if not f.is_video:
                    continue

                if normalize(id) != normalize(f.name):
                    continue

                try:

                    direct_url = get_seedr_download_url(f.id)

                    if not direct_url:
                        continue

                    quality = detect_quality(f.name)

                    streams.append({
                        "name": "☁️ Seedr",

                        "title": (
                            f"⚡ {quality}\n"
                            f"📁 {f.name}"
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
