# tripadvisor-reviews-scraper

Scrapes reviews from tripadvisor.com over plain HTTP, no browser involved. This is reverse engineered from the official Android app, not the website: it talks to the same internal GraphQL API and persisted queries the mobile app uses, and impersonates a real Pixel device down to the user-agent string.

## How it works

Tripadvisor's mobile app authenticates with a static API key and sends GraphQL requests as persisted queries, a query hash instead of the query text itself. The scraper reuses that same hash (`QueryPoiReviews`) and API key, and builds a user-agent string matching the Android app's exact format, `Mobile Android TAaApp ... deviceName=Google_{codename}_{model} osVer=... taAppVersionString=...`, picked at random from a pool of real Pixel device profiles on every session. No WAF challenge to solve here, the mobile API doesn't sit behind one the way the website does, the barrier is getting the request shape and headers to match what the app actually sends.

Each listing gets scraped independently by paging through `offset` in steps of 20. After the first page, subsequent requests carry an `updateToken` pulled from the response, tripadvisor's own cursor for continuing the review list. Multiple listings run concurrently, pulled off a shared queue by a worker pool, `--concurrency` controls the pool size.

### Device profiles

The Pixel device pool lives in `tripadvisor_reviews_scraper/utils.py`, as `DEVICE_PROFILES`. Each entry is a real codename, model, Android version, screen density and size combination, they have to line up together or the fingerprint looks fabricated. One gets picked at random per session:

```python
DEVICE_PROFILES = [
    {"codename": "redfin", "model": "Pixel 5", "osVer": "13", "density": "xxhdpi", "screenSize": "393x851@2.75x"},
    ...
]
```

Add more entries here if you want a wider spread, just keep the four fields internally consistent for whatever device you add.

## Install

```bash
git clone https://github.com/yourname/tripadvisor-reviews-scraper
cd tripadvisor-reviews-scraper
pip install -e .
```

Requires Python 3.10 or newer.

## Proxies

The scraper needs proxies. Put yours in a text file, one per line. The proxy string gets inserted directly after `http://` when building the request, so the format has to match what curl_cffi accepts there:

```
1.2.3.4:8080
user:pass@5.6.7.8:8080
```

Lines starting with `#` and blank lines are skipped. There is no parsing beyond reading lines, whatever you put in the file is passed straight through. If the file is missing or has no usable proxies, the scraper stops and prints an error instead of running unproxied.

## CLI usage

```bash
tripadvisor-reviews-scraper "https://www.tripadvisor.com/Restaurant_Review-g187892-d12850867-Reviews-Restaurant_Armonia-Taormina_Province_of_Messina_Sicily.html" --proxies proxies.txt
```

Works for hotels, restaurants, and attractions, the listing type is detected from the URL.

With filters:

```bash
tripadvisor-reviews-scraper URL1 URL2 \
  --proxies proxies.txt \
  --output reviews.jsonl \
  --max-results 500 \
  --rating 1 2 \
  --since-period 6_months \
  --type Couples Family \
  --search "rude staff" \
  --concurrency 5
```

- `--max-results` caps reviews per listing, default 10000.
- `--since-period` accepts `1_month`, `3_months`, `6_months`, `1_year`. `--since-date` (YYYY-MM-DD) overrides it if both are set.
- `--search` sends the term to tripadvisor as a server-side filter by default. Add `--search-is-local` to instead fetch normally and flag matching reviews client-side with `keyword_match`.

Run `tripadvisor-reviews-scraper --help` for the full list.

## Plain script

If you don't want to deal with CLI flags, `run.py` has the same options as plain variables at the top of the file, edit those and run it directly:

```bash
python run.py
```

## Using it as a library

```python
import asyncio
from tripadvisor_reviews_scraper import scrape_listings
from tripadvisor_reviews_scraper.utils import load_proxies

async def main():
    proxies = load_proxies("proxies.txt")
    collected = []

    async def push_data(batch):
        collected.extend(batch)

    await scrape_listings(
        query_filters_list=[{
            "listing_url": "https://www.tripadvisor.com/Restaurant_Review-g187892-d12850867-Reviews-Restaurant_Armonia-Taormina_Province_of_Messina_Sicily.html",
            "desired_count": 100,
            "rating": [],
            "sincePeriod": None,
            "sinceDate": None,
            "months": [],
            "type": [],
            "search": "",
            "searchIsLocalFilter": False,
        }],
        proxies=proxies,
        push_data=push_data,
    )

    print(f"Got {len(collected)} reviews")

asyncio.run(main())
```

## Output fields

Each review is a flat dict:

| Field | Description |
|---|---|
| `listing_title`, `listing_url` | The listing this review belongs to |
| `reviews_stats` | Listing-level rating breakdown and totals, same for every review of that listing |
| `review_id`, `review_url`, `report_url` | Review identifiers and links |
| `rating`, `title`, `text`, `text_clean` | Review content, `text` keeps HTML, `text_clean` strips it |
| `published_date`, `visited_date`, `trip_type`, `tip` | Review metadata |
| `helpful_votes` | How many people found the review helpful |
| `photos` | List of photo URLs attached to the review |
| `author` | Reviewer name, profile URL, avatar, hometown, contributions, helpful vote count |
| `owner_response` | Business owner's reply, if any, with its own author, date, and text fields |
| `subratings` | Category-level ratings (service, food, value, etc), where the listing type has them |
| `keyword_query`, `keyword_match` | Only meaningful when `--search` is used |

## Notes

- The scraper impersonates Chrome's TLS fingerprint via curl_cffi's `chrome_android` profile, on top of the Android app's own user-agent and headers.
- This project is for personal and research use. Check tripadvisor's terms of service before scraping at any real volume, and keep request rates reasonable.

## Support

☕ If this saved you time, a coffee is appreciated: mof1reromeo@gmail.com (PayPal)
