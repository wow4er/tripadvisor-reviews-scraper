import asyncio
import json
import logging

from tripadvisor_reviews_scraper.orchestrator import scrape_listings
from tripadvisor_reviews_scraper.utils import clean_url, load_proxies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tripadvisor_reviews_scraper")

# Edit these instead of passing CLI flags.

LISTING_URLS = [
    "https://www.tripadvisor.com/Restaurant_Review-g187892-d12850867-Reviews-Restaurant_Armonia-Taormina_Province_of_Messina_Sicily.html",
    # "https://www.tripadvisor.com/Hotel_Review-g60763-d99765-Reviews-Some_Hotel.html",
]

PROXIES_FILE = "proxies.txt"
OUTPUT_FILE = "reviews.jsonl"

MAX_RESULTS = 100  # per listing

FILTERS = {
    "rating": [],              # e.g. [1, 2]
    "sincePeriod": None,        # "1_month", "3_months", "6_months", "1_year"
    "sinceDate": None,          # "YYYY-MM-DD", overrides sincePeriod
    "months": [],
    "type": [],                 # e.g. ["Couples", "Family", "Solo"]
    "search": "",
    "searchIsLocalFilter": False,  # True filters client-side instead of sending the term to the server
}

CONCURRENCY = 5  # listings scraped in parallel


async def main():
    proxies = load_proxies(PROXIES_FILE)
    listing_urls = [clean_url(u) for u in LISTING_URLS]

    out_file = open(OUTPUT_FILE, "a", encoding="utf-8")

    async def push_data(batch: list[dict]):
        for item in batch:
            out_file.write(json.dumps(item, ensure_ascii=False) + "\n")
        out_file.flush()
        logger.info(f"Wrote {len(batch)} items")

    query_filters_list = [
        {**FILTERS, "desired_count": MAX_RESULTS, "listing_url": url}
        for url in listing_urls
    ]

    try:
        await scrape_listings(
            query_filters_list=query_filters_list,
            proxies=proxies,
            push_data=push_data,
            max_concurrent=CONCURRENCY,
        )
    finally:
        out_file.close()


if __name__ == "__main__":
    asyncio.run(main())
