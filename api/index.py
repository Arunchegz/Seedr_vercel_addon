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

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


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
        "version": "25.0.0",
        "name": "Seedr Addon",
        "description": "Stream your Seedr files in Stremio",

        "resources": [
            "catalog",
            "meta",
            "stream"
        ],

        "types": [
            "movie"
        ],

        "catalogs": [
            {
                "type": "movie",
                "id": "seedr",
                "name": "My Seedr Files"
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

                    "description": f.name,

                    "videos": [
                        {
                            "id": normalize(f.name),
                            "title": f.name,
                            "released": "2026-01-01T00:00:00.000Z"
                        }
                    ]
                }
            }

    return {"meta": {}}


# ---------------------------------------------------
# Stream
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str):

    streams = []

    if type != "movie":
        return {"streams": []}

    files = await get_all_files()

    for f in files:

        if not f.is_video:
            continue

        if normalize(id) == normalize(f.name):

            try:

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

                streams.append({
                    "name": "Seedr",
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
