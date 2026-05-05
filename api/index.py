from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import re
import requests

app = FastAPI()

# -----------------------
# CORS
# -----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Seedr Client (OFFICIAL API)
# -----------------------
class SeedrClient:
    def __init__(self, token):
        self.token = token
        self.base = "https://www.seedr.cc/api/v0.1/p"

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }

    def get_folder(self, folder_id=0):
        url = f"{self.base}/fs/folder/{folder_id}/items"
        res = requests.get(url, headers=self.headers(), timeout=10)
        res.raise_for_status()
        return res.json()

    def get_file(self, file_id):
        url = f"{self.base}/fs/file/{file_id}"
        res = requests.get(url, headers=self.headers(), timeout=10)
        res.raise_for_status()
        return res.json()


def get_client():
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")
    return SeedrClient(token)

# -----------------------
# Helpers
# -----------------------
def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

def extract_title_year(filename):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title, year

def walk_files(client, folder_id=0):
    data = client.get_folder(folder_id)

    for f in data.get("files", []):
        yield f

    for folder in data.get("folders", []):
        yield from walk_files(client, folder.get("id"))

# -----------------------
# Root
# -----------------------
@app.get("/")
def root():
    return {"status": "ok"}

# -----------------------
# Debug: check API
# -----------------------
@app.get("/debug/test")
def test():
    client = get_client()
    return client.get_folder(0)

@app.get("/debug/files")
def debug_files():
    client = get_client()
    return list(walk_files(client))

# -----------------------
# Manifest
# -----------------------
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "8.0.0",
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

# -----------------------
# Catalog
# -----------------------
@app.get("/catalog/movie/seedr.json")
def catalog():
    client = get_client()
    metas = []

    try:
        for f in walk_files(client):
            name = f.get("name")
            if not name:
                continue

            title, year = extract_title_year(name)
            meta_id = normalize(title + year)

            metas.append({
                "id": meta_id,
                "type": "movie",
                "name": title or name,
                "year": year
            })

    except Exception as e:
        return {"metas": [], "error": str(e)}

    return {"metas": metas}

# -----------------------
# Stream
# -----------------------
@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    if type != "movie":
        return {"streams": []}

    client = get_client()
    streams = []

    try:
        id_norm = normalize(id)

        for f in walk_files(client):
            name = f.get("name")
            file_id = f.get("id")

            if not name or not file_id:
                continue

            if id_norm in normalize(name):
                streams.append({
                    "name": "Seedr",
                    "title": name,
                    "url": f"https://www.seedr.cc/api/v0.1/p/fs/file/{file_id}"
                })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
