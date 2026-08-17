import logging
import base64
from curl_cffi import requests
import re
import asyncio
import time, random, string
import uuid
import secrets
from datetime import datetime, timedelta, UTC

from .utils import CONTENT_TYPE_MAP, DEVICE_PROFILES, PERIOD_TO_DAYS, clean_text

logger = logging.getLogger("tripadvisor_reviews_scraper")



class TripAdvisorScraper:
    def __init__(self, proxies, filters: dict):
        self.proxy = None
        self.proxies = proxies
        self.session = None
        self.query_filters = filters
        self.agent_version = random.randint(146, 151)
        self.reviews_hash = 'b2816c5313f132ee374040573c454ecd4da89a6a5672476b76c444f0580feb86'
        self.hotel_data_hash = '85599930f1826a490d3835ff7537c72739d70d523420a0941d7b153a307fad1c'
        self.ta_api_key = 'ce957ab2-0385-40f2-a32d-ed80296ff67f'
        self.ta_client_version = '4e93a4878415297ab95d22665c666b6602dcfcbb'
        self.api_url = "https://api.tripadvisor.com/api/internal/1.0/graphql"
        self.BASE_URL = 'https://www.tripadvisor.com'
        self.FILTERS_ADDED = False

        user_agent, screenSize = self._random_user_agent()
        session = secrets.token_hex(16).upper()
        pageview_id = str(uuid.uuid4())
        locationEnabled = random.choice([True, False])
        preciseLocationEnabled = random.choice([True, False])
        pushNotificationEnabled = random.choice([True, False])
        viewMode = random.choice(['LIGHT_MODE', 'DARK_MODE'])

        self.session_params = {
            'user_agent': user_agent,
            'screenSize': screenSize,
            'session': session,
            'pageview_id': pageview_id,
            'locationEnabled': locationEnabled,
            'preciseLocationEnabled': preciseLocationEnabled,
            'pushNotificationEnabled': pushNotificationEnabled,
            'viewMode': viewMode,
            't_uid': str(uuid.uuid4())
        }

        self.proxy = random.choice(self.proxies)
        self.proxy_formatted = {
            "http": f"http://{self.proxy}",
            "https": f"http://{self.proxy}",
        }
        self.session = requests.AsyncSession(
            impersonate="chrome_android"
        )



    def _random_user_agent(self, app_version="260706006", app_version_string="68.9"):
        device = random.choice(DEVICE_PROFILES)
        return (
            f"Mobile Android TAaApp TARX13 "
            f"taAppDeviceFeatures=2293828 "
            f"taAppVersion={app_version} "
            f"appLang=en_US osName='Android' "
            f"deviceName=Google_{device['codename']}_{device['model']} "
            f"osVer={device['osVer']} "
            f"taAppVersionString={app_version_string} "
            f"{device['density']} normal "
            f"mcc= mnc= connectivity=wifi", device['screenSize']
        )

    def _to_absolute_url(self, path):
        if not path:
            return None
        if path.startswith('http'):
            return path
        return self.BASE_URL + path

    def _clean_photo_url(self, url_template):
        if not url_template:
            return None
        return re.sub(r'\?w=\{width\}&h=\{height\}&s=1', '', url_template)

    def _extract_int(self, value_str, default=0):
        if not value_str:
            return default
        digits = re.sub(r'[^\d]', '', value_str)
        return int(digits) if digits else default

    def _extract_action_url(self, review_actions, action_type):
        for action in review_actions or []:
            if action.get('actionType') == action_type:
                return (action.get('webUrl') or {}).get('externalUrl')
        return None

    def _extract_share_url(self, review_actions):
        for action in review_actions or []:
            if action.get('__typename') == 'AppPresentation_ShareLinkAction':
                return self._to_absolute_url(((action.get('link') or {}).get('route') or {}).get('url'))
        return None

    def _extract_person(self, profile, is_owner=False):
        profile = profile or {}
        avatar_template = (((profile.get('avatar') or {}).get('data') or {}).get('photoSizeDynamic') or {}).get(
            'urlTemplate')
        person = {
            'name': profile.get('displayName'),
            'profile_url': self._to_absolute_url(((profile.get('profileLink') or {}).get('route') or {}).get('url')),
            'avatar_url': self._clean_photo_url(avatar_template),
        }
        if is_owner:
            person['position'] = (profile.get('positionAtLocation') or {}).get('string')
        else:
            person['hometown'] = profile.get('hometown')
            person['contributions'] = profile.get('totalContributions')
            person['helpful_votes'] = self._extract_int((profile.get('helpfulVotesCount') or {}).get('string'))
        return person

    def _extract_owner_response(self, owner_response):
        if not owner_response:
            return None
        return {
            'author': self._extract_person(owner_response, is_owner=True),
            'published_date': (owner_response.get('publishedDate') or {}).get('string'),
            'report_url': ((owner_response.get('reportAction') or {}).get('webUrl') or {}).get('externalUrl'),
            'text': owner_response.get('text'),
            'text_clean': clean_text(owner_response.get('text')),
        }

    def _extract_subratings(self, subratings_list):
        result = {}
        for item in subratings_list or []:
            label = (item.get('label') or {}).get('string')
            value_str = (item.get('value') or {}).get('string')
            if label is None:
                continue
            result[label] = self._extract_int(value_str)
        return result

    def _compute_since_date(self, filters: dict):
        """
        Resolve the effective 'since' date string (YYYY-MM-DD).
        sinceDate (exact, user-picked) overrides sincePeriod (relative offset).
        """
        since_date = filters.get('sinceDate')
        if since_date:
            return since_date

        period = filters.get('sincePeriod')
        if not period:
            return None

        days = PERIOD_TO_DAYS.get(period)
        if not days:
            return None

        return (datetime.now(UTC) - timedelta(days=days)).strftime('%Y-%m-%d')

    def _build_filters_payload(self, filters: dict):
        """
        Build the routeParameters.filters list matching Tripadvisor's expected
        shape, from the flat query_filters dict. Only includes filters that
        actually have values.
        """
        result = []

        rating = filters.get('rating')
        if rating:
            result.append({"id": "rating", "value": list(rating)})

        since_date = self._compute_since_date(filters)
        if since_date:
            result.append({"id": "since", "value": [since_date]})

        months = filters.get('months')
        if months:
            result.append({"id": "months", "value": list(months)})

        trip_type = filters.get('type')
        if trip_type:
            result.append({"id": "type", "value": list(trip_type)})

        # language filter is always sent as "all" in the observed payload
        result.append({"id": "language", "value": ["all"]})

        search_term = filters.get('search')
        search_is_local = filters.get('searchIsLocalFilter')
        # if searchIsLocalFilter is on, keyword filtering happens client-side
        # on already-fetched reviews, so we don't send "query" to the server
        if search_term and not search_is_local:
            result.append({"id": "query", "value": [search_term]})

        return result

    def extract_traveler_insights(self, s):
        rt = s.get('ratingText') or {}
        ratings_overall_raw = s.get('ratingCounts') or {}
        ratings_stats = {}
        subratings = {}

        sr = s.get('subRatings') or {}
        for k, v in sr.items():
            if isinstance(v, float):
                subratings[k] = round(v, 1)

        order = ['excellentBar', 'veryGoodBar', 'averageBar', 'poorBar', 'terribleBar']
        for key in order:
            bar = ratings_overall_raw.get(key)
            if not bar:
                continue
            label = (bar.get('label') or {}).get('string')
            count_str = (bar.get('count') or {}).get('string', '0')
            if label is None:
                continue
            ratings_stats[label] = {
                'count': self._extract_int(count_str),
                'percentage': bar.get('percentage'),
            }

        return {
            'reviews_total': s.get('count'),
            'listing_rating': s.get('rating'),
            'listing_rating_text': rt.get('string'),
            'ratings_stats': ratings_stats,
            'subratings_stats': subratings,
        }

    def extract_review(self, s, listing_title, reviews_stats, params: dict):
        review_actions = s.get('reviewActions') or []

        photos = []
        for p in s.get('photos') or []:
            template = ((p.get('cardPhoto') or {}).get('sizes') or {}).get('urlTemplate')
            clean_url = self._clean_photo_url(template)
            if clean_url:
                photos.append(clean_url)

        keyword_match = False
        search_term = (params.get('search') or '').lower()

        if params.get('searchIsLocalFilter') and search_term:
            title = ((s.get('htmlTitle') or {}).get('htmlString') or '').lower()
            text = ((s.get('htmlText') or {}).get('htmlString') or '').lower()
            if search_term in title or search_term in text:
                keyword_match = True
        elif search_term:
            keyword_match = True

        return {
            'listing_title': listing_title,
            'listing_url': params['listing_url'],
            'reviews_stats': reviews_stats,
            'review_id': ((s.get('helpfulVote') or {}).get('helpfulVoteAction') or {}).get('objectId'),
            'rating': (s.get('bubbleRating') or {}).get('rating'),
            'title': (s.get('htmlTitle') or {}).get('htmlString'),
            'text': (s.get('htmlText') or {}).get('htmlString'),
            'text_clean': clean_text((s.get('htmlText') or {}).get('htmlString')),
            'published_date': (s.get('publishedDate') or {}).get('string'),
            'visited_date': (s.get('dateVisitedValue') or {}).get('string'),
            'trip_type': (s.get('tripTypeValue') or {}).get('string'),
            'tip': (s.get('tipText') or {}).get('string'),
            'helpful_votes': self._extract_int(((s.get('helpfulVote') or {}).get('helpfulVotes') or {}).get('string')),
            'photos': photos,
            'review_url': self._extract_share_url(review_actions),
            'report_url': self._extract_action_url(review_actions, 'ReportIAPWebviewAction'),
            'author': self._extract_person(s.get('userProfile')),
            'owner_response': self._extract_owner_response(s.get('ownerResponse')),
            'subratings': self._extract_subratings(s.get('subratings')),
            'keyword_query': search_term,
            'keyword_match': keyword_match,
        }

    def process_reviews(self, reviews_data_raw):
        try:
            sections = reviews_data_raw['data']['AppPresentation_queryPoiReviews'].get('sections', [])
        except (KeyError, TypeError, AttributeError):
            logger.warning('Unexpected response structure, no sections found')
            return []

        reviews = []

        if not sections:
            return reviews

        try:
            listing_title = reviews_data_raw['data']['AppPresentation_queryPoiReviews']['container'].get('navTitle')
        except (KeyError, TypeError, AttributeError):
            listing_title = None

        # ratingCounts/subRatings live in TravelerInsights, scan first so every
        # review below can be stamped with the same stats dict
        reviews_stats = {}
        for s in sections:
            if s.get('__typename') == 'AppPresentation_TravelerInsights':
                reviews_stats = self.extract_traveler_insights(s)
                break

        for s in sections:
            typename = s.get('__typename')

            if typename == 'AppPresentation_UserReviewSection':
                reviews.append(self.extract_review(s, listing_title, reviews_stats, self.query_filters))

        return reviews

    async def fetch_reviews(self, listing_id, content_type, offset=0):
        querystring = {
            "currency": "USD",
            "lang": "en_US"
        }

        route_filters = []
        if not self.FILTERS_ADDED:
            route_filters = self._build_filters_payload(self.query_filters)
            self.FILTERS_ADDED = True

        payload = {
            "operationName": "QueryPoiReviews",
            "variables": {
                "currency": "USD",
                "request": {
                    "debug": [],
                    "routeParameters": {
                        "contentType": f"{content_type}",
                        "detailId": int(listing_id),
                        "filters": route_filters
                    }
                },
                "sessionId": self.session_params['session'],
                "tracking": {
                    "nativeTrackingInputs": {
                        "locationEnabled": self.session_params['locationEnabled'],
                        "locationPermissionType": "NOT_ASKED",
                        "preciseLocationEnabled": self.session_params['preciseLocationEnabled'],
                        "pushNotificationEnabled": self.session_params['pushNotificationEnabled'],
                        "screenSize": self.session_params['screenSize'],
                        "textSize": "100.00%",
                        "viewMode": self.session_params['viewMode']
                    },
                    "pageviewUid": self.session_params['pageview_id'],
                    "screenName": "ShowUserReviews"
                },
                "unitLength": "MILES"
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": self.reviews_hash
                },
                "clientLibrary": {
                    "name": "apollo-kotlin",
                    "version": "5.0.0"
                }
            }
        }

        if self.session_params.get('updateToken', None):
            payload['variables']['request']['updateToken'] = self.session_params.get('updateToken')
            payload['variables']['request']['routeParameters']['pagee'] = str(offset)

        headers = {
            "Host": "api.tripadvisor.com",
            "Connection": "keep-alive",
            "X-APOLLO-OPERATION-NAME": "QueryPoiReviews",
            "X-APOLLO-OPERATION-ID": self.reviews_hash,
            "accept": "multipart/mixed;deferSpec=20220824, application/graphql-response+json, application/json",
            "X-TripAdvisor-API-Key": self.ta_api_key,
            "User-Agent": self.session_params['user_agent'],
            "X-TripAdvisor-UUID": self.session_params['t_uid'],
            "X-TripAdvisor-ClientSessionID": self.session_params['session'],
            "X-TripAdvisor-Currency": "USD",
            "X-TripAdvisor-Distance-Units": "mi",
            "X-Native-Consent": "{\"essential\":true,\"performance\":true,\"functional\":true,\"targeting\":true,\"social\":false}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate, br"
        }

        for attempt in range(5):
            try:
                r = await self.session.post(self.api_url, json=payload, headers=headers, params=querystring,
                                            proxies=self.proxy_formatted, timeout=10)
                if r.status_code < 300:
                    logger.debug(f"Listing {listing_id}, page {int(offset / 20) + 1}: success")
                data = r.json()
                return data
            except Exception as e:
                logger.warning(f"Reviews fetch error: {e}, retry {attempt}, changing proxy")
                self.proxy = random.choice(self.proxies)
                self.proxy_formatted = {
                    "http": f"http://{self.proxy}",
                    "https": f"http://{self.proxy}",
                }
                await asyncio.sleep(random.uniform(1, 3))
        else:
            return None

    @staticmethod
    def extract_listing_id(url: str) -> str | None:
        match = re.search(r'-d(\d+)-', url)
        return match.group(1) if match else None

    @staticmethod
    def extract_content_type(url: str) -> str:
        for prefix, content_type in CONTENT_TYPE_MAP.items():
            if prefix in url:
                return content_type
        return 'hotel'