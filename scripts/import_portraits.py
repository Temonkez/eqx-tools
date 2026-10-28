
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

GALLERY = "https://tacticus.wiki.gg/wiki/Gallery_Faction"
API = "https://tacticus.wiki.gg/api.php"
CATEGORIES = {"Chaos", "Imperial", "Xenos", "Machines of War"}
TEST_NAMES = {"Abaddon The Despoiler", "Jain Zar", "Biovore"}


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def get_entries(session):
    response = session.get(GALLERY, timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    content = soup.select_one(".mw-parser-output") or soup

    category = None
    unit = None
    seen = set()

    for node in content.descendants:
        if not getattr(node, "name", None):
            continue

        if node.name in ("h2", "h3"):
            heading = clean(node.get_text(" ", strip=True))
            heading = heading.replace("[edit]", "").strip()

            if heading in CATEGORIES:
                category = heading
                unit = None
            elif node.name in ("h3", "h4") and category:
                unit = heading

        elif node.name == "a" and category and unit:
            href = node.get("href", "")
            title = node.get("title", "")
            img = node.find("img")
            alt = img.get("alt", "") if img else ""
            description = " ".join([href, title, alt])

            if not any(x in description for x in
                       ("Icon_Large", "Icon Large", "Large Icon")):
                continue

            file_title = title if title.startswith("File:") else \
                unquote(href.split("/wiki/")[-1]).replace("_", " ")

            if not file_title.startswith("File:"):
                continue

            key = (category, unit)
            if key in seen:
                continue

            seen.add(key)
            yield {
                "name": unit,
                "type": "machine-of-war" if category == "Machines of War"
                        else "character",
                "faction": category,
                "file": file_title
            }


def image_url(session, file_title):
    response = session.get(API, params={
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url",
        "titles": file_title
    }, timeout=40)
    response.raise_for_status()

    for page in response.json().get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo", [])
        if info:
            return info[0]["url"]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not args.test and not args.all:
        parser.error("Choose --test or --all")

    session = requests.Session()
    session.headers["User-Agent"] = "EQX-Portrait-Importer/0.1"

    entries = list(get_entries(session))
    if args.test:
        entries = [e for e in entries if e["name"] in TEST_NAMES]

    if not entries:
        raise RuntimeError("No matching portraits found. Check gallery parsing.")

    catalogue = []
    root = Path("portraits")

    for entry in entries:
        url = image_url(session, entry["file"])
        if not url:
            print("Missing:", entry["name"])
            continue

        folder = root / (
            "machines-of-war" if entry["type"] == "machine-of-war"
            else "characters"
        )
        folder.mkdir(parents=True, exist_ok=True)

        filename = re.sub(
            r"[^A-Za-z0-9._-]+", "_", entry["name"]
        ).strip("_") + ".png"

        path = folder / filename
        response = session.get(url, timeout=40)
        response.raise_for_status()

        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            print("Not a PNG:", entry["name"])
            continue

        path.write_bytes(response.content)

        catalogue.append({
            "name": entry["name"],
            "type": entry["type"],
            "faction": entry["faction"],
            "image": path.as_posix()
        })
        print("Imported:", entry["name"])
        time.sleep(0.3)

    root.mkdir(exist_ok=True)
    (root / "catalogue.json").write_text(
        json.dumps({"version": 1, "units": catalogue}, indent=2),
        encoding="utf-8"
    )

    print("Total imported:", len(catalogue))


if __name__ == "__main__":
    main()
