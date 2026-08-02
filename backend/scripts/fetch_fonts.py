"""Download the typefaces resume templates are actually built in.

A matched layout is only a match if the type matches, and the type is whatever Canva,
Docs or Word put on the page — not whatever happens to be installed on the server. This
puts the families next to the app so a fresh deployment renders the same as a laptop
with a full font library on it.

    python scripts/fetch_fonts.py            # the default set
    python scripts/fetch_fonts.py Cormorant  # plus anything else by name

Families come from github.com/google/fonts, which is where all of these are open
licensed. Anything already downloaded is left alone.
"""

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "..", "app", "static", "fonts")

LISTING = "https://api.github.com/repos/google/fonts/contents/{licence}/{slug}"

LICENCES = ("ofl", "apache", "ufl")

# What resume templates are set in, in rough order of how often they turn up. Inter and
# the Liberation faces are usually packaged by the distribution, so they are not here.
DEFAULT = (
    "Quicksand", "Poppins", "Montserrat", "Lato", "Raleway", "Open Sans", "Nunito",
    "Roboto", "Source Sans 3", "Work Sans", "Rubik", "Karla", "Merriweather",
    "Playfair Display", "Libre Baskerville", "EB Garamond", "Cormorant Garamond",
)

def slug_of(family: str) -> str:
    return family.replace(" ", "").casefold()

def listing(family: str):
    """Every file the repo holds for this family, whichever licence it sits under."""
    for licence in LICENCES:
        url = LISTING.format(licence=licence, slug=slug_of(family))
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  {family}: {licence} listing failed ({e.code})")
        except Exception as e:
            print(f"  {family}: {licence} listing failed ({e!r})")
    return None

def fetch(family: str) -> int:
    files = listing(family)
    if not files:
        print(f"{family}: not found in google/fonts")
        return 0

    got = 0
    for entry in files:
        name = entry.get("name", "")
        if not name.lower().endswith((".ttf", ".otf")) or not entry.get("download_url"):
            continue

        target = os.path.join(FONT_DIR, name)
        if os.path.exists(target):
            got += 1
            continue
        try:
            with urllib.request.urlopen(entry["download_url"], timeout=60) as response:
                data = response.read()
            with open(target, "wb") as out:
                out.write(data)
            print(f"  {name} ({len(data) // 1024} KB)")
            got += 1
        except Exception as e:
            print(f"  {name}: failed ({e!r})")
    return got

def main() -> int:
    os.makedirs(FONT_DIR, exist_ok=True)
    wanted = list(DEFAULT) + sys.argv[1:]

    total = 0
    for family in wanted:
        print(family)
        total += fetch(family)

    print(f"\n{total} files in {os.path.realpath(FONT_DIR)}")
    print("Typst is pointed at this directory by the renderer; nothing else to do.")
    return 0 if total else 1

if __name__ == "__main__":
    raise SystemExit(main())
