from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Maps the URL prefix Tripadvisor uses for each listing type to the
# contentType value the mobile app's GraphQL API expects.
CONTENT_TYPE_MAP = {
    'Hotel_Review': 'hotel',
    'Restaurant_Review': 'restaurant',
    'AttractionProductReview': 'attraction_product',
    'Attraction_Review': 'attraction',
}

# Real Pixel device profiles, one is picked at random per session to build
# the mobile app's user-agent string. Matches what the official Android
# TripAdvisor app sends, codename, model, Android version, screen density
# and size all have to line up for a given device or the fingerprint looks
# fabricated.
DEVICE_PROFILES = [
    {
        "codename": "redfin",
        "model": "Pixel 5",
        "osVer": "13",
        "density": "xxhdpi",
        "screenSize": "393x851@2.75x",
    },
    {
        "codename": "oriole",
        "model": "Pixel 6",
        "osVer": "16",
        "density": "xxhdpi",
        "screenSize": "393x841@2.75x",
    },
    {
        "codename": "panther",
        "model": "Pixel 7",
        "osVer": "16",
        "density": "xxhdpi",
        "screenSize": "393x850@2.75x",
    },
    {
        "codename": "lynx",
        "model": "Pixel 7a",
        "osVer": "15",
        "density": "xxhdpi",
        "screenSize": "393x841@2.75x",
    },
    {
        "codename": "husky",
        "model": "Pixel 8 Pro",
        "osVer": "16",
        "density": "xxxhdpi",
        "screenSize": "412x892@3.5x",
    },
    {
        "codename": "shiba",
        "model": "Pixel 8",
        "osVer": "16",
        "density": "xxhdpi",
        "screenSize": "393x852@2.75x",
    },
    {
        "codename": "tokay",
        "model": "Pixel 9",
        "osVer": "16",
        "density": "xxhdpi",
        "screenSize": "393x852@2.75x",
    },
    {
        "codename": "caiman",
        "model": "Pixel 9 Pro",
        "osVer": "16",
        "density": "xxxhdpi",
        "screenSize": "412x892@3.0x",
    },
]

# Relative "since" period filters mapped to a day count, used to compute an
# absolute since-date when the caller passes a period instead of a date.
PERIOD_TO_DAYS = {
    "1_month": 30,
    "3_months": 90,
    "6_months": 180,
    "1_year": 365,
}


def clean_text(text) -> str:
    """Strips HTML from a review's htmlString field, turning <br> and <p> into newlines."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_after("\n")
    return soup.get_text()


def load_proxies(path: str) -> list[str]:
    """
    Reads a proxies file, one proxy per line, format host:port or user:pass@host:port.
    Blank lines and lines starting with # are skipped.
    Raises FileNotFoundError if the path doesn't exist, ValueError if the file has no usable proxies.
    """
    proxies = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxies.append(line)

    if not proxies:
        raise ValueError(f"No proxies found in {path}, add at least one proxy per line")

    return proxies


def clean_url(raw_url: str) -> str:
    """Strips query params and trailing junk from a tripadvisor listing URL."""
    parsed = urlparse(raw_url.strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
