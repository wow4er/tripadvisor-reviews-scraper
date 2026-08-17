import asyncio
import logging
from typing import Awaitable, Callable

from .scraper import TripAdvisorScraper

logger = logging.getLogger("tripadvisor_reviews_scraper")

PAGE_SIZE = 20
BATCH_SIZE = 100

PushCallback = Callable[[list[dict]], Awaitable[None]]


async def scrape_one_listing(
    query_filters: dict,
    proxies: list[str],
    push_data: PushCallback,
):
    """Scrapes a single listing end-to-end: paginated reviews only, no separate listing/company data step."""

    url = query_filters['listing_url']

    listing_id = TripAdvisorScraper.extract_listing_id(url)
    content_type = TripAdvisorScraper.extract_content_type(url)

    if listing_id is None:
        logger.warning(f"[ {url} ] Could not extract listing id from URL, skipping")
        return

    worker = TripAdvisorScraper(proxies, query_filters)

    target = query_filters.get('desired_count', 100)

    buffer = []
    offset = 0

    while True:
        if offset >= target:
            break

        rev_raw_data = await worker.fetch_reviews(listing_id, content_type, offset=offset)

        if rev_raw_data is None or 'data' not in rev_raw_data:
            logger.warning(f"[ {url} ] fetch_reviews failed after retries at page={int(offset / PAGE_SIZE) + 1}, stopping this listing")
            break

        sections = rev_raw_data['data']['AppPresentation_queryPoiReviews'].get('sections', [])
        if not sections:
            logger.info(f"[ {url} ] no reviews found at page={int(offset / PAGE_SIZE) + 1}")
            break

        for s in sections:
            if s.get('__typename') == 'AppPresentation_SecondaryButton':
                worker.session_params['updateToken'] = s['link']['updateToken']
                break

        reviews_data = worker.process_reviews(rev_raw_data)
        buffer.extend(reviews_data)
        offset += len(reviews_data)

        logger.info(f"[ {url} ] fetched {offset} reviews so far")

        while len(buffer) >= BATCH_SIZE:
            batch, buffer = buffer[:BATCH_SIZE], buffer[BATCH_SIZE:]
            await push_data(batch)

        if len(reviews_data) < PAGE_SIZE:
            logger.info(f"[ {url} ] last page reached")
            break

        await asyncio.sleep(0.2)

    if buffer:
        await push_data(buffer)

    logger.info(f"[ {url} ] done, total reviews: {offset}")


async def scrape_listings(
    query_filters_list: list[dict],
    proxies: list[str],
    push_data: PushCallback,
    max_concurrent: int = 5,
):
    """Scrapes multiple listings concurrently, min(max_concurrent, len(query_filters_list)) workers pulling from a shared queue.

    Each item in query_filters_list is a full filter dict for one listing
    (must include 'listing_url'); entries whose URL can't be parsed for a
    listing id are dropped before queuing, with a warning logged.
    """

    if not query_filters_list:
        return

    valid_tasks = []
    for qf in query_filters_list:
        url = qf.get('listing_url', '')
        if TripAdvisorScraper.extract_listing_id(url) is None:
            logger.warning(f"Could not extract listing id from URL, skipping: {url}")
            continue
        valid_tasks.append(qf)

    if not valid_tasks:
        return

    queue: asyncio.Queue = asyncio.Queue()
    for qf in valid_tasks:
        queue.put_nowait(qf)

    workers_needed = min(max_concurrent, len(valid_tasks))

    async def worker_loop():
        while True:
            try:
                qf = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            url = qf['listing_url']
            logger.info(f"Scraping: {url}")
            try:
                await scrape_one_listing(
                    query_filters=qf,
                    proxies=proxies,
                    push_data=push_data,
                )
            except Exception as e:
                logger.warning(f"[ {url} ] Unhandled error: {e}")
                await push_data([{
                    "listing_url": url,
                    "listing_data": None,
                    "error": "failed_to_fetch_listing_data",
                }])

    tasks = [asyncio.ensure_future(worker_loop()) for _ in range(workers_needed)]
    await asyncio.gather(*tasks)
