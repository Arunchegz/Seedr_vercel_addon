from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import re

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

def get_client():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")

    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")

    return SeedrClient(token=token)

# ---------------------------------------------------
# Recursive folder walker
# ---------------------------------------------------

def walk_folder(client, folder_id):

    contents = client.list_folder(folder_id)

    files = []

    for f in contents.get("files", []):
        files.append(f)

    for folder in contents.get("folders", []):
        nested = walk_folder(client, folder["id"])
        files.extend(nested)

    return files

# ---------------------------------------------------
# Get all files
# ---------------------------------------------------

def get_all_files():

    client = get_client()

    root = client.list_folder()

    files = []

    for f in root.get("files", []):
        files.append(f)

    for folder in root.get("folders", []):
        nested = walk_folder(client, folder["id"])
        files.extend(nested)

    return files

# ---------------------------------------------------
# Manifest
# ---------------------------------------------------

@app.get("/manifest.json")
def manifest():

    return {
        "id": "org.seedrcc.stremio",
        "version": "1.0.0",
        "name": "Seedr Addon",
        "description": "Seedr streaming addon",

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
def catalog():

    files = get_all_files()

    metas = []

    for f in files:

        name = f.get("name", "")

        if not name:
            continue

        metas.append({
            "id": normalize(name),
            "type": "movie",
            "name": name,
            "posterShape": "poster",
            "description": name
        })

    return {"metas": metas}

# ---------------------------------------------------
# Meta
# ---------------------------------------------------

@app.get("/meta/{type}/{id}.json")
def meta(type: str, id: str):

    files = get_all_files()

    for f in files:

        name = f.get("name", "")

        if normalize(name) == normalize(id):

            return {
                "meta": {
                    "id": normalize(name),
                    "type": "movie",
                    "name": name,

                    "posterShape": "poster",

                    "description": name,

                    "videos": [
                        {
                            "id": normalize(name),
                            "title": name
                        }
                    ]
                }
            }

    return {"meta": {}}

# ---------------------------------------------------
# Stream
# ---------------------------------------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):

    if type != "movie":
        return {"streams": []}

    files = get_all_files()

    streams = []

    for f in files:

        name = f.get("name", "")

        if normalize(name) != normalize(id):
            continue

        url = f.get("url")

        if not url:
            continue

        streams.append({
            "name": "Seedr",
            "title": name,
            "url": url
        })

    return {"streams": streams}
