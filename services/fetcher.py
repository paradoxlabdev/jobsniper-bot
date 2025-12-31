"""
Fetcher Service - Async client for Just Join IT API.
Handles rate limiting, retries, and error recovery.
"""
import asyncio
from typing import Any, Optional
from datetime import datetime

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from circuitbreaker import circuit

from core import setup_logger, settings
from core.cache import cache_manager

logger = setup_logger(__name__, "fetcher.log")


class FetcherService:
    """
    Async service for fetching job offers from Just Join IT API.
    
    Features:
    - Async HTTP requests with aiohttp
    - Automatic retry with exponential backoff
    - Rate limiting protection
    - Error handling and logging
    """
    
    def __init__(self):
        self.api_url = settings.jjit_api_url
        self.session: Optional[aiohttp.ClientSession] = None
        self._headers = {
            "User-Agent": "JobSniper/1.0 (Automated Job Monitoring)",
            "Accept": "application/json",
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        await cache_manager.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        await cache_manager.close()
    
    async def initialize(self) -> None:
        """Initialize HTTP session."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=timeout,
            )
            logger.info("Fetcher service initialized")
    
    async def close(self) -> None:
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("Fetcher service closed")
    
    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_backoff_factor,
            min=1,
            max=10
        ),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str, params: Optional[dict] = None) -> dict[str, Any]:
        """
        Fetch data from URL with automatic retry.
        
        Args:
            url: API endpoint URL
            params: Optional query parameters
        
        Returns:
            JSON response as dictionary
        
        Raises:
            aiohttp.ClientError: On HTTP errors
            asyncio.TimeoutError: On timeout
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        logger.debug(f"Fetching: {url} with params: {params}")
        
        # Try cache first
        cache_key = f"{url}:{str(params)}"
        cached_data = await cache_manager.get(cache_key)
        if cached_data:
            return cached_data

        async with self.session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            logger.debug(f"Fetched {len(data) if isinstance(data, list) else 1} items")
            
            # Cache success response
            await cache_manager.set(data, cache_key, ttl=300)
            return data
    
    @circuit(failure_threshold=5, recovery_timeout=300, expected_exception=Exception)
    async def fetch_offers(
        self,
        keywords: Optional[list[str]] = None,
        keyword_match_mode: str = "relaxed",  # New parameter
        category_ids: Optional[list[str]] = None,
        remote: bool = True,
        locations: Optional[list[str]] = None,
        items_count: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch job offers from Just Join IT API v2.
        
        Args:
            keywords: List of keywords to filter by (e.g., ["Python", "Remote"])
            category_ids: List of category IDs (e.g., ["5"] for Python)
            remote: Filter for remote positions only
            locations: List of preferred cities (e.g., ["Warszawa", "Krakow"])
            items_count: Number of items per request (max 100)
        
        Returns:
            List of job offer dictionaries
        
        Raises:
            Exception: On fetch failure after retries
        """
        try:
            logger.info("Starting fetch from Just Join IT API v2")
            
            # Build base query parameters for v2 API
            base_params = {
                "itemsCount": 100,  # API limit per page
                "sortBy": "published",
                "orderBy": "DESC",
                "currency": "pln",
            }
            
            # Add category filters
            if category_ids:
                # Use list of tuples for multiple values with same key
                # API expects categories[]=5&categories[]=1
                if isinstance(category_ids, str):
                    category_ids = [cid.strip() for cid in category_ids.split(",")]
                
                # We need to reconstruct params as a list of tuples to support multiple keys
                # OR rely on aiohttp supporting dict values as lists (which it does, but user requested explicit list)
                # Ideally, we should convert the whole params dict to a list of tuples if we want mixed types
                
                # However, to be cleaner and safer, let's keep base params separate
                # and merge them when making the request.
                pass  # We will handle this inside the loop construction
            
            # Pagination: Fetch multiple pages up to max limit
            all_offers = []
            page = 0
            max_pages = 5  # Reduced from 10 to improve performance (500 offers max)
            
            while page < max_pages:
                # Construct query parameters properly
                params = list(base_params.items())
                
                # Add categories as repeated tuples
                if category_ids:
                    for cat_id in category_ids:
                        params.append(("categories[]", cat_id))
                
                # Add 'from' offset
                params.append(("from", page * 100))
                
                # Fetch offers from v2 API
                response_data = await self._fetch_with_retry(self.api_url, params=params)
                
                # v2 API returns {data: [...], meta: {...}}
                if not isinstance(response_data, dict):
                    logger.warning(f"Unexpected response format: {type(response_data)}")
                    break
                
                offers = response_data.get("data", [])
                
                if not isinstance(offers, list):
                    logger.warning(f"Unexpected offers format: {type(offers)}")
                    break
                
                if not offers:
                    logger.info(f"No more offers on page {page}")
                    break
                
                all_offers.extend(offers)
                logger.info(f"Fetched page {page + 1}: {len(offers)} offers")
                
                # Check if we've reached the end
                meta = response_data.get("meta", {})
                total_count = meta.get("totalCount", 0)
                
                if (page + 1) * 100 >= total_count:
                    logger.info(f"Reached end of results (total: {total_count})")
                    break
                
                page += 1
                
                # Small delay between pages to avoid rate limiting
                await asyncio.sleep(0.5)
            
            # Filter all collected offers
            filtered_offers = FetcherService._filter_offers(
                all_offers, keywords, keyword_match_mode, remote, locations
            )
            
            meta = response_data.get("meta", {}) if response_data else {}
            total_count = meta.get("totalCount", len(all_offers))
            
            logger.info(
                f"Fetched {len(all_offers)} offers from API across {page + 1} pages, "
                f"{len(filtered_offers)} match criteria "
                f"(total available: {total_count})"
            )
            
            return filtered_offers
            
        except Exception as e:
            logger.error(f"Failed to fetch offers: {e}", exc_info=True)
            raise
    
    
    @staticmethod
    def _filter_offers(
        offers: list[dict[str, Any]],
        keywords: Optional[list[str]],
        keyword_match_mode: str,
        remote: bool,
        locations: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Filter offers based on criteria.
        
        Keyword Match Modes:
        - relaxed: At least 1 keyword must match (OR logic)
        - moderate: At least 40% of keywords must match (flexible AND)
        - strict: At least 80% of keywords must match (strict AND)
        """
        filtered = []
        
        for offer in offers:
            # 1. Remote and Location Processing
            workplace_type = str(offer.get("workplaceType", offer.get("workplace_type", ""))).lower()
            is_remote_offer = workplace_type == "remote" or offer.get("remote") is True
            is_partly_remote = workplace_type == "partly_remote"
            
            # City matching
            city = str(offer.get("city", "")).lower()
            city_match = False
            if locations:
                city_match = any(loc.lower() == city for loc in locations)

            # Filtering logic:
            # If user disabled remote, reject strictly remote offers
            if not remote and is_remote_offer:
                continue

            # If locations are specified, apply geographic filters
            if locations:
                if remote:
                    # Pass if it matches a city OR is a remote offer
                    if not (city_match or is_remote_offer or is_partly_remote):
                        continue
                else:
                    # Strict city match required, and fully remote is already excluded above
                    if not city_match:
                        continue
            else:
                # No locations specified (All Cities)
                # If Remote is NO, we still want to excludes fully remote jobs
                if not remote and is_remote_offer:
                    continue
                # Otherwise, all jobs pass (Remote, Hybrid, Office)
            
            # 2. Keyword Filter
            if keywords:
                # Build searchable text using helper method
                offer_text = FetcherService._build_searchable_text(offer)
                
                # Calculate threshold based on match mode
                num_keywords = len(keywords)
                matches = sum(1 for kw in keywords if kw.lower() in offer_text)
                
                if keyword_match_mode == "relaxed":
                    # Relaxed: At least 1 keyword must match
                    threshold = 1
                elif keyword_match_mode == "strict":
                    # Strict: At least 80% of keywords must match
                    threshold = max(1, int(num_keywords * 0.8))
                else:  # moderate (default)
                    # Moderate: At least 40% of keywords must match
                    threshold = max(1, int(num_keywords * 0.4))
                
                if matches < threshold:
                    continue
            
            filtered.append(offer)
        
        return filtered
    
    @staticmethod
    def _build_searchable_text(offer: dict) -> str:
        """
        Build searchable text from offer fields.
        Centralizes text extraction logic for keyword matching.
        
        Args:
            offer: Offer dictionary
        
        Returns:
            Lowercase searchable text
        """
        parts = [
            str(offer.get("title", "")),
            str(offer.get("workplaceType", offer.get("workplace_type", ""))),
            str(offer.get("city", "")),
            str(offer.get("body", offer.get("description", ""))),
        ]
        
        # Extract skills
        skills = offer.get("requiredSkills", offer.get("skills", []))
        if isinstance(skills, str):
            parts.append(skills)
        elif isinstance(skills, list):
            for skill in skills:
                if isinstance(skill, dict):
                    parts.append(str(skill.get("name", "")))
                else:
                    parts.append(str(skill))
        
        return " ".join(parts).lower()
    
    async def test_connection(self) -> bool:
        """
        Test API connectivity.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            await self._fetch_with_retry(self.api_url)
            logger.info("API connection test successful")
            return True
        except Exception as e:
            logger.error(f"API connection test failed: {e}")
            return False


# Global fetcher service instance
fetcher_service = FetcherService()


# Example usage
async def main():
    """Example usage of FetcherService."""
    async with FetcherService() as fetcher:
        # Test connection
        if await fetcher.test_connection():
            # Fetch offers with category IDs
            offers = await fetcher.fetch_offers(
                keywords=settings.jjit_search_keywords,
                category_ids=settings.jjit_category_ids,
                remote=True,
            )
            print(f"Found {len(offers)} matching offers")
            
            # Print first offer as example
            if offers:
                print("\nExample offer:")
                print(f"Title: {offers[0].get('title')}")
                print(f"Company: {offers[0].get('companyName')}")
                print(f"Workplace: {offers[0].get('workplaceType')}")
                print(f"ID: {offers[0].get('id')}")


if __name__ == "__main__":
    asyncio.run(main())
