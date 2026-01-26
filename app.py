from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
import os
import re
import requests

app = FastAPI()

# Allow Stremio + browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Health check
# -----------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "Seedr Stremio Addon"}

# -----------------------
# Seedr Client
# -----------------------

def get_client():
    if "SEEDR_DEVICE_CODE" not in os.environ:
        raise Exception("SEEDR_DEVICE_CODE not set")
    return Seedr.from_device_code(os.environ["SEEDR_DEVICE_CODE"])


# -----------------------
# Device Authorization
# -----------------------

@app.get("/authorize")
def authorize():
    """
    Generates a Seedr device code and user authorization URL.
    Visit the URL, approve device, then set SEEDR_DEVICE_CODE in Vercel.
    """
    device = Seedr.get_device_code()
    return {
        "device_code": device.device_code,
        "user_code": device.user_code,
        "verification_url": device.verification_url,
        "message": "Open verification_url and enter user_code to authorize"
    }


@app.get("/auth/status")
def auth_status():
    """
    Checks if current device code is valid.
    """
    try:
        with get_client() as client:
            settings = client.get_settings()
            return {
                "authorized": True,
                "username": settings.account.username
            }
    except Exception as e:
        return {
            "authorized": False,
            "error": str(e)
        }


# -----------------------
# Helpers
# -----------------------

def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def get_movie_title(imdb_id: str):
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    data = requests.get(url, timeout=10).json()
    meta = data.get("meta", {})
    title = meta.get("name", "")
    year = str(meta.get("year", ""))
    return title, year


def walk_files(client, folder_id=None):
    contents = client.list_contents(folder_id=folder_id)

    for f in contents.files:
        yield f

    for folder in contents.folders:
        yield from walk_files(client, folder.id)


def extract_title_year(filename: str):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year


# -----------------------
# Manifest
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "1.2.0",
        "name": "Seedr.cc Personal Addon",
        "description": "Stream and browse your Seedr.cc files in Stremio",
        "resources": ["stream", "catalog", "meta"],
        "types": ["movie"],
        "catalogs": [
            {
                "type": "movie",
                "id": "seedr",
                "name": "My Seedr Files"
            }
        ]
    }


# -----------------------
# Debug
# -----------------------

@app.get("/debug/files")
def debug_files():
    with get_client() as client:
        return [
            {
                "file_id": f.file_id,
                "folder_file_id": f.folder_file_id,
                "name": f.name,
                "size": f.size,
                "play_video": f.play_video
            }
            for f in walk_files(client)
        ]


# -----------------------
# Catalog
# -----------------------

@app.get("/catalog/movie/seedr.json")
def catalog():
    metas = []

    with get_client() as client:
        for f in walk_files(client):
            if not f.play_video:
                continue

            title, year = extract_title_year(f.name)
            meta_id = normalize(title + year)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title or f.name,
                "year": year,
                "poster": None,
                "description": "From your Seedr.cc account"
            })

    return {"metas": metas}


# -----------------------
# Meta
# -----------------------

@app.get("/meta/movie/{id}.json")
def meta(id: str):
    return {
        "meta": {
            "id": id,
            "type": "movie",
            "name": id
        }
    }


# -----------------------
# Stream
# -----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    streams = []

    if type != "movie":
        return {"streams": []}

    try:
        movie_title, movie_year = get_movie_title(id)
        norm_title = normalize(movie_title)

        with get_client() as client:
            for file in walk_files(client):
                if not file.play_video:
                    continue

                fname_norm = normalize(file.name)

                if norm_title in fname_norm and movie_year in file.name:
                    result = client.fetch_file(file.folder_file_id)

                    streams.append({
                        "name": "Seedr.cc",
                        "title": file.name,
                        "url": result.url,
                        "behaviorHints": {
                            "notWebReady": False
                        }
                    })

    except Exception:
        pass

    return {"streams": streams}
