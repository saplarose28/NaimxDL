
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

RELEASE_URL = os.environ["RELEASE_URL"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

session = requests.Session()
session.headers["User-Agent"] = "ReleaseDownloader/1.0"


def send_telegram(message):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message},
        timeout=30,
    )
    response.raise_for_status()


def get_release():
    parsed = urlparse(RELEASE_URL)
    match = re.fullmatch(
        r"/([^/]+)/([^/]+)/releases/(?:tag/([^/]+)|latest)/?",
        parsed.path,
    )

    if parsed.netloc != "github.com" or not match:
        raise ValueError("Invalid public GitHub Release URL")

    owner, repo, tag = match.groups()
    api = f"https://api.github.com/repos/{owner}/{repo}/releases"

    if tag:
        api += f"/tags/{tag}"
    else:
        api += "/latest"

    response = session.get(api, timeout=30)
    response.raise_for_status()
    return response.json()


def download_resume(url, output, expected_size):
    output = Path(output)
    partial = Path(str(output) + ".part")

    for attempt in range(1, 9):
        offset = partial.stat().st_size if partial.exists() else 0

        if expected_size and offset == expected_size:
            partial.replace(output)
            return

        headers = {}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        try:
            with session.get(
                url,
                headers=headers,
                stream=True,
                timeout=(30, 90),
            ) as response:
                if offset and response.status_code == 206:
                    mode = "ab"
                elif response.status_code == 200:
                    mode = "wb"
                else:
                    response.raise_for_status()
                    raise RuntimeError(
                        f"Unexpected HTTP {response.status_code}"
                    )

                with open(partial, mode) as file:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            file.write(chunk)
                    file.flush()
                    os.fsync(file.fileno())

            actual = partial.stat().st_size
            if expected_size and actual != expected_size:
                raise IOError(
                    f"Downloaded {actual} of {expected_size} bytes"
                )

            partial.replace(output)
            return

        except Exception as error:
            print(f"Attempt {attempt}: {error}")
            if attempt == 8:
                raise
            time.sleep(min(2 ** attempt, 60))


def main():
    release = get_release()
    assets = release.get("assets", [])

    if not assets:
        raise RuntimeError("Release contains no assets")

    # Persistent workspace helps resume if the job runs again
    # on a runner that retains this directory.
    directory = Path("downloads")
    directory.mkdir(exist_ok=True)

    send_telegram(
        f"Download started: {release['name']}\n"
        f"Files: {len(assets)}"
    )

    for index, asset in enumerate(assets, start=1):
        name = Path(asset["name"]).name
        destination = directory / name

        send_telegram(f"{index}/{len(assets)} Downloading: {name}")

        download_resume(
            asset["browser_download_url"],
            destination,
            int(asset["size"]),
        )

        send_telegram(
            f"Download complete: {name}\n"
            "Ready for Gofile upload."
        )

    send_telegram(
        "All Release assets downloaded. "
        "Gofile upload needs its supported upload API."
    )


if __name__ == "__main__":
    main()
