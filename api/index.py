from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
import os
import re
import requests

app = FastAPI()

-----------------------

CORS (Stremio + Browser)

-----------------------

app.add_middleware(
CORSMiddleware,
allow_origins=[""],
allow_methods=[""],
allow_headers=["*"],
)

-----------------------

Seedr Client

-----------------------

def get_client():
device_code = os.environ.get("SEEDR_DEVICE_CODE")
if not device_code:
raise Exception("SEEDR_DEVICE_CODE environment variable is missing")
return Seedr.from_device_code(device_code)

-----------------------

Helpers

-----------------------

def normalize(text: str):
return re.sub(r"[^a-z0-9]", "", text.lower())

def extract_title_year(filename: str):
year_match = re.search(r"(19|20)\d{2}", filename)
year = year_match.group(0) if year_match else ""

title = re.sub(r"\.(mkv|mp4|avi|mov|webm|wmv).*", "", filename, flags=re.I)  
title = re.sub(r"(19|20)\d{2}", "", title)  
title = title.replace(".", " ").replace("_", " ").strip()  

return title, year

def walk_files(client, folder_id=None):
contents = client.list_contents(folder_id=folder_id)

for f in contents.files:  
    yield f  

for folder in contents.folders:  
    yield from walk_files(client, folder.id)

def get_movie_title(imdb_id: str):
try:
url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
r = requests.get(url, timeout=10)
r.raise_for_status()
meta = r.json().get("meta", {})
return meta.get("name", ""), str(meta.get("year", ""))
except Exception:
return "", ""

def get_fresh_stream_url(client, file):
result = client.fetch_file(file.folder_file_id)
return result.url

-----------------------

Root

-----------------------

@app.get("/")
def root():
return {
"status": "ok",
"message": "Seedr Stremio Addon running (Fresh URL on every request)"
}

-----------------------

Manifest

-----------------------

@app.get("/manifest.json")
def manifest():
return {
"id": "org.seedrcc.stremio",
"version": "2.0.0",
"name": "Seedr.cc Personal Addon",
"description": "Stream your Seedr.cc files in Stremio (always fresh links)",
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

-----------------------

Catalog

-----------------------

@app.get("/catalog/movie/seedr.json")
def catalog():
metas = []

with get_client() as client:  
    for file in walk_files(client):  
        if not file.play_video:  
            continue  

        title, year = extract_title_year(file.name)  
        meta_id = f"seedr:{file.folder_file_id}"  

        metas.append({  
            "id": meta_id,  
            "type": "movie",  
            "name": title or file.name,  
            "year": year,  
            "poster": None,  
            "description": "From your Seedr.cc account"  
        })  

return {"metas": metas}

-----------------------

Meta

-----------------------

@app.get("/meta/movie/{id}.json")
def meta(id: str):
return {
"meta": {
"id": id,
"type": "movie",
"name": id
}
}

-----------------------

Stream

-----------------------

@app.get("/stream/{type}/{id}.json")
def stream(type: str, id: str):
streams = []

if type != "movie":  
    return {"streams": []}  

try:  
    with get_client() as client:  

        # IMDb-based matching  
        if id.startswith("tt"):  
            movie_title, movie_year = get_movie_title(id)  
            norm_title = normalize(movie_title)  

            for file in walk_files(client):  
                if not file.play_video:  
                    continue  

                fname_norm = normalize(file.name)  
                title_match = norm_title and norm_title in fname_norm  
                year_match = not movie_year or movie_year in fname_norm  

                if title_match and year_match:  
                    url = get_fresh_stream_url(client, file)  
                    streams.append({  
                        "name": "Seedr.cc",  
                        "title": file.name,  
                        "url": url,  
                        "behaviorHints": {  
                            "notWebReady": False  
                        }  
                    })  

        # Catalog / direct file matching  
        elif id.startswith("seedr:"):  
            file_id = id.split(":", 1)[1]  

            for file in walk_files(client):  
                if str(file.folder_file_id) == file_id:  
                    url = get_fresh_stream_url(client, file)  
                    streams.append({  
                        "name": "Seedr.cc",  
                        "title": file.name,  
                        "url": url,  
                        "behaviorHints": {  
                            "notWebReady": False  
                        }  
                    })  
                    break  

except Exception as e:  
    return {"streams": [], "error": str(e)}  

return {"streams": streams}