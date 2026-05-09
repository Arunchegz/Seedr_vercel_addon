from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re

from seedr_api import SeedrClient

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def get_token():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")

    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")

    return token

# ---------------------------------------------------
# Recursive folder walker
# ---------------------------------------------------

async def walk_folder(client, folder_id):
    contents = await client.filesystem.list_folder_contents(folder_id)

    files = []

    for f in contents.files or []:
        files.append(f)

    for folder in contents.folders or []:
        nested = await walk_folder(client, folder.id)
        files.extend(nested)

    return files

# ---------------------------------------------------
# Get all files
# ---------------------------------------------------

async def get_all_files():

    token = get_token()

    async with SeedrClient.from_token(token) as client:

        root = await client.filesystem.list_root_contents()

        files = []

        # root files
        for f in root.files or []:
            files.append(f)

        # recursive folders
        for folder in root.folders or []:
            nested = await walk_folder(client, folder.id)
            files.extend(nested)

        return files

# ---------------------------------------------------
# Debug
# ---------------------------------------------------

@app.get("/debug/files")
async def debug_files():

    files = await get_all_files()

    return [
        {
            "id": f.id,
            "name": f.name,
            "size": f.size,
            "is_video": f.is_video,
        }
        for f in files
    ]

# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "13.0.0",
        "name": "Seedr Addon",
        "description": "Stream Seedr files in Stremio",
        "resources": ["stream", "catalog"],
        "types": ["movie"],
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

        if not f.name:
            continue

        metas.append({
            "id": normalize(f.name),
            "type": "movie",
            "name": f.name,
        })

    return {"metas": metas}

# ---------------------------------------------------
# Stream
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str):

    streams = []

    files = await get_all_files()

    for f in files:

        if not f.name:
            continue

        if normalize(id) in normalize(f.name):

            hls_url = None

            try:
                hls_url = f.presentation_urls.video["hls"]
            except:
                pass

            if hls_url:

                streams.append({
                    "name": "Seedr",
                    "title": f.name,
                    "url": hls_url,
                    "behaviorHints": {
                        "notWebReady": False
                    }
                })

    return {"streams": streams}
