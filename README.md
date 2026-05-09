# Seedr Stremio Addon

Stream your personal Seedr files directly inside Stremio using a lightweight FastAPI + Vercel addon.

Supports:

* 📂 Browsing Seedr files
* 🎬 Direct movie streaming
* 🖼 Poster thumbnails
* 🔎 IMDb title matching
* ☁️ Seedr direct streaming links
* ⚡ Serverless deployment on Vercel

---

## Features

* Automatically scans your Seedr account
* Recursively loads folders/files
* Detects video files
* Streams directly from Seedr CDN
* Works inside:

  * Stremio Web
  * Stremio Desktop
  * Android TV
  * Mobile

---

Movies added to Seedr automatically appear in Stremio.

---

## Tech Stack

* Python
* FastAPI
* Vercel Serverless Functions
* Seedr API
* Stremio Addon SDK format

---

## Deployment

### 1. Clone Repository

```bash
git clone https://github.com/Arunchegz/Seedr_vercel_addon.git
cd Seedr_vercel_addon
```

---

### 2. Install Requirements

```bash
pip install -r requirements.txt
```

---

### 3. Add Environment Variable

Create `.env`:

```env
SEEDR_ACCESS_TOKEN=your_seedr_access_token
```

Or add it in Vercel:

```text
Project Settings → Environment Variables
```

---

## Run Locally

```bash
uvicorn api.index:app --reload
```

Manifest:

```text
http://127.0.0.1:8000/manifest.json
```

---

## Deploy to Vercel

### vercel.json

```json
{
  "functions": {
    "api/index.py": {
      "runtime": "python3.12"
    }
  },
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

---

### Deploy

```bash
vercel
```

---

## Install in Stremio

Add this URL:

```text
https://your-vercel-app.vercel.app/manifest.json
```

---

## API Endpoints

| Endpoint                    | Description            |
| --------------------------- | ---------------------- |
| `/manifest.json`            | Stremio manifest       |
| `/catalog/movie/seedr.json` | Personal Seedr catalog |
| `/meta/{type}/{id}.json`    | Metadata               |
| `/stream/{type}/{id}.json`  | Stream URLs            |
| `/debug/files`              | Debug Seedr files      |

---

## Seedr API Used

```text
GET /fs/root/contents
GET /fs/folder/{id}/contents
GET /download/file/{id}/url
```

---

## Notes

* Only video files are shown in catalog
* Large libraries may increase response time
* Seedr links expire automatically
* Requires active Seedr subscription/storage

---

## Screenshots

Add screenshots here:

```text
/docs/stremio.png
/docs/catalog.png
```

---

## Future Improvements

* TV show support
* Search support
* Subtitle support
* Caching
* Async optimization
* Multi-user auth

---

## License

MIT

---

## Author

GitHub: `@Arunchegz`
