import argparse
import asyncio
import json
import logging

from .orchestrator import scrape_listings
from .utils import clean_url, load_proxies

logger = logging.getLogger("tripadvisor_reviews_scraper")


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape reviews from tripadvisor.com listing pages")
    parser.add_argument("urls", nargs="+", help="One or more tripadvisor.com listing URLs (hotel, restaurant, or attraction)")
    parser.add_argument("--proxies", required=True, help="Path to a proxies file, one proxy per line")
    parser.add_argument("--output", default="reviews.jsonl", help="Output file, JSON lines format")
    parser.add_argument("--max-results", type=int, default=10000, help="Max reviews per listing")
    parser.add_argument("--rating", nargs="*", type=int, default=[], help="Filter by rating, e.g. 1 2")
    parser.add_argument("--since-period", default=None, help="Relative date filter: 1_month, 3_months, 6_months, 1_year")
    parser.add_argument("--since-date", default=None, help="Absolute date filter, YYYY-MM-DD, overrides --since-period")
    parser.add_argument("--months", nargs="*", default=[], help="Filter by visit month")
    parser.add_argument("--type", nargs="*", default=[], help="Trip type filter, e.g. Couples Family Solo")
    parser.add_argument("--search", default="", help="Keyword search or filter")
    parser.add_argument("--search-is-local", action="store_true",
                         help="Apply --search client-side on fetched reviews instead of sending it to the server")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent listings scraped at once")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def run():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        proxies = load_proxies(args.proxies)
    except FileNotFoundError:
        logger.error(f"Proxies file not found: {args.proxies}")
        return
    except ValueError as e:
        logger.error(str(e))
        return

    listing_urls = [clean_url(u) for u in args.urls]

    out_file = open(args.output, "a", encoding="utf-8")

    async def push_data(batch: list[dict]):
        for item in batch:
            out_file.write(json.dumps(item, ensure_ascii=False) + "\n")
        out_file.flush()
        logger.info(f"Wrote {len(batch)} items")

    shared_filters = {
        "desired_count": args.max_results,
        "rating": args.rating,
        "sincePeriod": args.since_period,
        "sinceDate": args.since_date,
        "months": args.months,
        "type": args.type,
        "search": args.search,
        "searchIsLocalFilter": args.search_is_local,
    }

    query_filters_list = [
        {**shared_filters, "listing_url": url}
        for url in listing_urls
    ]

    try:
        await scrape_listings(
            query_filters_list=query_filters_list,
            proxies=proxies,
            push_data=push_data,
            max_concurrent=args.concurrency,
        )
    finally:
        out_file.close()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
