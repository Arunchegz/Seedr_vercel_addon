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
# Seedr Client (OFFICIAL /fs API)
# -----------------------
class SeedrClient:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://www.seedr.cc/api/v0.1/p"

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "seedr-stremio-addon/1.0"
        }

    def get_folder_items(self, folder_id: int = 0):
        url = f"{self.base}/fs/folder/{folder_id}/items"
        res = requests.get(url, headers=self.headers(), timeout=15)
        res.raise_for_status()
        return res.json()

    def get_file(self, file_id: int):
        # Returns metadata including a direct/streamable URL
        url = f"{self.base}/fs/file/{file_id}"
        res = requests.get(url, headers=self.headers(), timeout=15)
        res.raise_for_status()
        return res.json()


def get_client() -> SeedrClient:
    token = os.environ.get("SEEDR_ACCESS_TOKEN")
    if not token:
        raise Exception("Missing SEEDR_ACCESS_TOKEN")
    return SeedrClient(token)

# -----------------------
# Helpers
# -----------------------
def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())

def extract_title_year(filename: str):
    year_match = re.search(r"(19|20)\d{2}", filename)
    year = year_match.group(0) if year_match else ""

    title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)
    title = re.sub(r"(19|20)\d{2}", "", title)
    title = title.replace(".", " ").replace("_", " ").strip()

    return title or filename, year

def walk_files(client: SeedrClient, folder_id: int = 0):
    """
    Recursively yield all file items.
    NOTE: /fs/folder/{id}/items returns { items: [ {id, name, type}, ... ] }
    """
    data = client.get_folder_items(folder_id)

    for item in data.get("items", []):
        t = item.get("type")
        if t == "file":
            yield item
        elif t == "folder":
            # recurse
            yield from walk_files(client, item.get("id"))

def get_stream_url(client: SeedrClient, file_id: int) -> str:
    """
    Resolve a playable URL from file metadata.
    Seedr returns a 'url' (or sometimes nested fields depending on account/file).
    """
    info = client.get_file(file_id)

    # Common keys seen:
    # - 'url'
    # - 'stream_url'
    # - 'download_url'
    for k in ("url", "stream_url", "download_url"):
        if info.get(k):
            return info[k]

    # Fallback: return empty string if nothing found
    return ""

# -----------------------
# Routes
# -----------------------
@app.get("/")
def root():
    return {"status": "ok"}

# ---- Debug ----
@app.get("/debug/test")
def debug_test():
    try:
        client = get_client()
        return client.get_folder_items(0)
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/files")
def debug_files():
    try:
        client = get_client()
        return list(walk_files(client))
    except Exception as e:
        return {"error": str(e)}

# ---- Manifest ----
@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedrcc.stremio",
        "version": "9.0.0",
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

# ---- Catalog ----
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
                "name": title,
                "year": year
            })

    except Exception as e:
        return {"metas": [], "error": str(e)}

    return {"metas": metas}

# ---- Stream ----
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
                url = get_stream_url(client, file_id)
                if not url:
                    continue

                streams.append({
                    "name": "Seedr",
                    "title": name,
                    "url": url,
                    "behaviorHints": {"notWebReady": False}
                })

    except Exception as e:
        return {"streams": [], "error": str(e)}

    return {"streams": streams}
