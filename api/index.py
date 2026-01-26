from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seedrcc import Seedr
import os
import re
import requests

app = FastAPI()  # <-- THIS is what Vercel is complaining about if missing

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# Seedr Client
# -----------------------

def get_client():
    return Seedr.from_device_code(os.environ["SEEDR_DEVICE_CODE"])

# -----------------------
# Helpers
# -----------------------

def normalize(text: str):
    return re.sub(r"[^a-z0-9]", "", text.lower())


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Seedr Vercel Addon running"
    }
