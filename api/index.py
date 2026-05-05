import requests

TOKEN = "YOUR_SEEDR_ACCESS_TOKEN"

BASE_URL = "https://www.seedr.cc/api/v0.1/p"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}

# -----------------------
# Get user profile
# -----------------------
def get_user():
    url = f"{BASE_URL}/user"
    res = requests.get(url, headers=headers)
    print("User:", res.status_code)
    print(res.json())


# -----------------------
# List files in root folder
# -----------------------
def list_files(folder_id=0):
    url = f"{BASE_URL}/fs/folder/{folder_id}/items"
    res = requests.get(url, headers=headers)
    res.raise_for_status()

    data = res.json()

    print("\nFolders:")
    for f in data.get("folders", []):
        print(f"📁 {f['name']} (ID: {f['id']})")

    print("\nFiles:")
    for f in data.get("files", []):
        print(f"🎬 {f['name']} (ID: {f['id']})")

    return data


# -----------------------
# Get file stream URL
# -----------------------
def get_stream(file_id):
    url = f"{BASE_URL}/fs/file/{file_id}"
    res = requests.get(url, headers=headers)
    res.raise_for_status()

    data = res.json()

    print("\nStream URL:")
    print(data.get("url"))


# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    get_user()

    data = list_files()

    # take first file
    if data.get("files"):
        first_file_id = data["files"][0]["id"]
        get_stream(first_file_id)
