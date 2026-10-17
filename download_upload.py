
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

FILE_URL = os.environ["FILE_URL"]
GOFILE_TOKEN = os.getenv("GOFILE_TOKEN", "")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

def telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=30,
    )
    r.raise_for_status()

def download_file(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Please provide a valid HTTPS URL.")

    name = Path(parsed.path).name or "download.bin"
    target = DOWNLOAD_DIR / name
    part = Path(str(target) + ".part")

    with requests.Session() as s:
        for attempt in range(1, 9):
            offset = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}

            try:
                with s.get(
                    url, headers=headers, stream=True,
                    timeout=(30, 90)
                ) as r:
                    if offset and r.status_code == 206:
                        mode = "ab"
                    elif r.status_code == 200:
                        mode = "wb"
                    else:
                        r.raise_for_status()
                        raise RuntimeError(
                            f"Unexpected HTTP {r.status_code}"
                        )

                    with open(part, mode) as f:
                        for chunk in r.iter_content(1024 * 1024):
                            if chunk:
                                f.write(chunk)

                part.replace(target)
                return target

            except Exception:
                if attempt == 8:
                    raise
                time.sleep(min(2 ** attempt, 60))

def upload_gofile(path):
    headers = {}
    if GOFILE_TOKEN:
        headers["Authorization"] = f"Bearer {GOFILE_TOKEN}"

    with open(path, "rb") as f:
        r = requests.post(
            "https://upload.gofile.is/uploadfile",
            headers=headers,
            files={"file": (path.name, f)},
            timeout=(30, 900),
        )
    r.raise_for_status()
    result = r.json()

    if result.get("status") != "ok":
        raise RuntimeError(f"Gofile upload failed: {result}")

    data = result.get("data", {})
    return (
        data.get("downloadPage")
        or data.get("directLink")
        or data.get("code")
    )

def main():
    telegram("Download started.")
    file_path = download_file(FILE_URL)
    telegram(f"Download complete: {file_path.name}")

    link = upload_gofile(file_path)
    if not link:
        raise RuntimeError("Upload succeeded but no share link was returned.")

    telegram(f"Gofile upload complete:\n{link}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            telegram(f"Task failed: {e}")
        except Exception:
            pass
        raise
