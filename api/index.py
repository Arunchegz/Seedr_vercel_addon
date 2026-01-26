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
# Root (Health Check)
# -----------------------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Vercel Addon running"
    }

# -----------------------
# STREMIO MANIFEST
# -----------------------

@app.get("/manifest.json")
def manifest():
    return {
        "id": "org.seedr.vercel.addon",
        "version": "1.0.0",
        "name": "Seedr Verccel Addon",
        "description": "Stream files directly from Seedr into Stremio",
        "resources": ["stream"],
        "types": ["movie", "series"],
        "catalogs": [],
        "idPrefixes": ["tt"]
    }

# -----------------------
# Seedr Client
# -----------------------

def get_client():
    """
    Uses Seedr device code authentication.
    SEEDR_DEVICE_CODE must be set in Vercel environment variables.
    """
    device_code = os.environ.get("SEEDR_DEVICE_CODE")
    if not device_code:
        raise Exception("SEEDR_DEVICE_CODE environment variable is missing")
    return Seedr.from_device_code(device_code)

# -----------------------
# Helpers
# -----------------------

def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def get_movie_title(imdb_id: str):
    """
    Fetch movie title + year from Stremio Cinemeta using IMDb ID
    """
    url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    meta = data.get("meta", {})
    title = meta.get("name", "")
    year = meta.get("year", "")
    return f"{title} {year}".strip()


# -----------------------
# STREMIO STREAM HANDLER
# -----------------------
# This is what Stremio calls when user clicks Play

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
    """
    For now this is a placeholder.
    Once Seedr search + direct file link is added,
    streams will appear inside Stremio.
    """

    # Example empty response (valid for Stremio)
    return {
        "streams": [
            {
                "name": "Seedr",
                "title": "Seedr addon is running (no stream linked yet)",
                "url": ""
            }
        ]
    }
