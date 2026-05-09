from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re
import urllib.parse

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
# Build direct Seedr download URL
# ---------------------------------------------------

def build_direct_url(file_obj):

    # Extract base URL from HLS URL
    hls_url = file_obj.presentation_urls.video["hls"]

    # Example:
    # https://rd23.seedr.cc/presentations/p/file/v1/784606/5908559199/assets/video/master-2160.m3u8

    match = re.search(r"https://([^/]+)/", hls_url)

    if not match:
        return None

    domain = match.group(1)

    encoded_name = urllib.parse.quote(file_obj.name)

    direct_url = (
        f"https://{domain}/ff_get/"
        f"{file_obj.id}/"
        f"{encoded_name}"
    )

    return direct_url

# ---------------------------------------------------
# Recursive folder walker
# ---------------------------------------------------

async def walk_folder(client, folder_id):

    contents = await client.filesystem.list_folder_contents(folder_id)

    files = []

    # Files in current folder
    for f in contents.files or []:
        files.append(f)

    # Walk subfolders recursively
    for folder in contents.folders or []:
        nested = await walk_folder(client, folder.id)
        files.extend(nested)

    return files

# ---------------------------------------------------
# Get all Seedr files
# ---------------------------------------------------

async def get_all_files():

    token = get_token()

    async with SeedrClient.from_token(token) as client:

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
# Debug
# ---------------------------------------------------

@app.get("/debug/files")
async def debug_files():

    files = await get_all_files()

    result = []

    for f in files:

        if not f.is_video:
            continue

        direct_url = None

        try:
            direct_url = build_direct_url(f)
        except:
            pass

        result.append({
            "id": normalize(f.name),
            "name": f.name,
            "size": f.size,
            "direct_url": direct_url
        })

    return result

# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "21.0.0",
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

                original_hls = f.presentation_urls.video["hls"]

                qualities = [
                    ("1080p", "master-1080.m3u8"),
                    ("720p", "master-720.m3u8"),
                    ("480p", "master-480.m3u8"),
                ]

                for quality_name, quality_file in qualities:

                    stream_url = re.sub(
                        r"master-\d+\.m3u8",
                        quality_file,
                        original_hls
                    )

                    streams.append({
                        "name": f"Seedr {quality_name}",
                        "title": f.name,
                        "url": stream_url,

                        "behaviorHints": {
                            "notWebReady": False
                        }
                    })

            except Exception as e:
                print(e)

    return {"streams": streams}
