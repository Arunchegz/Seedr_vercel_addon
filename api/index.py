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
        "version": "26.0.0",
        "name": "Seedr Addon",
        "description": "Stream your Seedr files in Stremio",

        "resources": [
            "stream"
        ],

        "types": [
            "movie"
        ],

        "idPrefixes": [
            "tt"
        ],

        "catalogs": []
    }


# ---------------------------------------------------
# Stream
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str):

    streams = []

    if type != "movie":
        return {"streams": []}

    try:

        # -----------------------------------
        # Get movie title from IMDb ID
        # -----------------------------------

        movie_title, movie_year = get_movie_title(id)

        print("MOVIE TITLE:", movie_title)
        print("MOVIE YEAR:", movie_year)

        target_title = normalize(movie_title)

        files = await get_all_files()

        for f in files:

            if not f.is_video:
                continue

            parsed_title, parsed_year = extract_title_year(f.name)

            normalized_file_title = normalize(parsed_title)

            # -----------------------------------
            # Match movie title
            # -----------------------------------

            if target_title not in normalized_file_title:
                continue

            # Optional year check
            if movie_year and parsed_year:
                if movie_year != parsed_year:
                    continue

            print("MATCHED:", f.name)

            # -----------------------------------
            # Get direct Seedr URL
            # -----------------------------------

            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Accept": "application/json"
            }

            response = requests.get(
                f"https://www.seedr.cc/api/v0.1/p/download/file/{f.id}/url",
                headers=headers,
                timeout=15
            )

            print("DOWNLOAD STATUS:")
            print(response.status_code)

            print("DOWNLOAD RESPONSE:")
            print(response.text)

            data = response.json()

            if not data.get("success"):
                continue

            direct_url = data.get("url")

            if not direct_url:
                continue

            # -----------------------------------
            # Quality detection
            # -----------------------------------

            quality = "Auto"

            filename_lower = f.name.lower()

            if "2160" in filename_lower or "4k" in filename_lower:
                quality = "4K"

            elif "1080" in filename_lower:
                quality = "1080p"

            elif "720" in filename_lower:
                quality = "720p"

            elif "480" in filename_lower:
                quality = "480p"

            # -----------------------------------
            # Stream entry
            # -----------------------------------

            streams.append({
                "name": f"Seedr {quality}",
                "title": f.name,
                "url": direct_url,

                "behaviorHints": {
                    "notWebReady": False
                }
            })

    except Exception as e:

        print("STREAM ERROR:")
        print(e)

    return {"streams": streams}
