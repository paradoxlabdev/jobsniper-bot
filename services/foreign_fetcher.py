"""
Foreign Job Board Fetcher Service.
Aggregates offers from international job boards:
- RemoteOK
- Remotive
- We Work Remotely
- Arbeitnow
"""
import asyncio
import logging
from typing import Optional

import httpx
import feedparser
from circuitbreaker import circuit

from core import setup_logger

logger = setup_logger(__name__, "foreign_fetcher.log")


class ForeignFetcher:
    """Fetches job offers from international boards."""
    
    def __init__(self):
        self.timeout = httpx.Timeout(30.0)
        
    async def initialize(self) -> None:
        """Initialize the fetcher."""
        logger.info("ForeignFetcher initialized")
    
    async def close(self) -> None:
        """Cleanup resources."""
        logger.info("ForeignFetcher closed")
    
    async def fetch_all(
        self,
        keywords: Optional[list[str]] = None,
        enabled_sources: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Fetch offers from all enabled sources in parallel.
        
        Args:
            keywords: Optional keywords to filter by
            enabled_sources: List of enabled source IDs (e.g., ['remoteok', 'remotive'])
        
        Returns:
            List of normalized job offers
        """
        if not enabled_sources:
            logger.info("No foreign sources enabled, skipping")
            return []
        
        logger.info(f"Fetching from sources: {enabled_sources}")
        
        # Build task map with source identification
        task_map = {}
        if 'remoteok' in enabled_sources:
            task_map['remoteok'] = self._fetch_remoteok(keywords)
        if 'remotive' in enabled_sources:
            task_map['remotive'] = self._fetch_remotive(keywords)
        if 'arbeitnow' in enabled_sources:
            task_map['arbeitnow'] = self._fetch_arbeitnow(keywords)
        
        # Execute async tasks in parallel
        tasks = list(task_map.values())
        source_names = list(task_map.keys())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results with source identification
        all_offers = []
        for source_name, result in zip(source_names, results):
            if isinstance(result, Exception):
                logger.error(f"[{source_name}] Fetch failed: {result}", exc_info=True)
            elif isinstance(result, list):
                logger.info(f"[{source_name}] Successfully fetched {len(result)} offers")
                all_offers.extend(result)
            else:
                logger.warning(f"[{source_name}] Unexpected result type: {type(result)}")
        
        # WWR is RSS (needs thread pool), run separately
        wwr_offers = []
        if 'weworkremotely' in enabled_sources:
            try:
                wwr_offers = await self._fetch_wwr(keywords)
                logger.info(f"[weworkremotely] Successfully fetched {len(wwr_offers)} offers")
                all_offers.extend(wwr_offers)
            except Exception as e:
                logger.error(f"[weworkremotely] WWR fetch failed: {e}", exc_info=True)
        
        logger.info(f"Total foreign offers fetched: {len(all_offers)} from {len(enabled_sources)} sources")
        return all_offers
    
    @circuit(failure_threshold=5, recovery_timeout=300, expected_exception=Exception)
    async def _fetch_remoteok(self, keywords: Optional[list[str]] = None) -> list[dict]:
        """Fetch from RemoteOK.com."""
        url = "https://remoteok.com/api"
        
        # Add tag filtering if keywords provided
        if keywords and len(keywords) > 0:
            # RemoteOK supports ?tag=python format
            url += f"?tag={keywords[0].lower()}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers={"User-Agent": "JobSniper/1.0"})
                resp.raise_for_status()
                data = resp.json()
                
                # First element is legal notice, skip it
                offers = []
                for job in data[1:]:
                    offers.append({
                        "source": "RemoteOK",
                        "jjit_id": f"remoteok_{job.get('id')}",
                        "slug": job.get('slug', ''),
                        "title": job.get('position', 'N/A'),
                        "company_name": job.get('company', 'Unknown'),
                        "company_logo_url": job.get('company_logo'),
                        "city": None,  # Remote jobs
                        "country_code": None,
                        "remote": True,
                        "salary_from": job.get('salary_min'),
                        "salary_to": job.get('salary_max'),
                        "salary_currency": "USD",
                        "description": job.get('description', ''),
                        "skills": ",".join(job.get('tags', [])),
                        "offer_url": job.get('url', ''),
                    })
                
                logger.info(f"RemoteOK: fetched {len(offers)} offers")
                return offers
            except Exception as e:
                logger.error(f"RemoteOK error: {e}", exc_info=True)
                return []
    
    @circuit(failure_threshold=5, recovery_timeout=300, expected_exception=Exception)
    async def _fetch_remotive(self, keywords: Optional[list[str]] = None) -> list[dict]:
        """Fetch from Remotive.com."""
        url = "https://remotive.com/api/remote-jobs?category=software-dev"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                
                offers = []
                for job in data.get('jobs', []):
                    offers.append({
                        "source": "Remotive",
                        "jjit_id": f"remotive_{job.get('id')}",
                        "slug": job.get('slug', ''),
                        "title": job.get('title', 'N/A'),
                        "company_name": job.get('company_name', 'Unknown'),
                        "company_logo_url": job.get('company_logo'),
                        "city": None,
                        "country_code": None,
                        "remote": True,
                        "salary_from": None,
                        "salary_to": None,
                        "salary_currency": "USD",
                        "description": job.get('description', ''),
                        "skills": ",".join(job.get('tags', [])),
                        "offer_url": job.get('url', ''),
                    })
                
                logger.info(f"Remotive: fetched {len(offers)} offers")
                return offers
            except Exception as e:
                logger.error(f"Remotive error: {e}", exc_info=True)
                return []
    
    @circuit(failure_threshold=5, recovery_timeout=300, expected_exception=Exception)
    async def _fetch_arbeitnow(self, keywords: Optional[list[str]] = None) -> list[dict]:
        """Fetch from Arbeitnow.com (European focus)."""
        url = "https://www.arbeitnow.com/api/job-board-api"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                
                offers = []
                for job in data.get('data', []):
                    offers.append({
                        "source": "Arbeitnow",
                        "jjit_id": f"arbeitnow_{job.get('slug')}",
                        "slug": job.get('slug', ''),
                        "title": job.get('title', 'N/A'),
                        "company_name": job.get('company_name', 'Unknown'),
                        "company_logo_url": None,
                        "city": job.get('location'),
                        "country_code": None,
                        "remote": job.get('remote', False),
                        "salary_from": None,
                        "salary_to": None,
                        "salary_currency": "EUR",
                        "description": job.get('description', ''),
                        "skills": ",".join(job.get('tags', [])),
                        "offer_url": job.get('url', ''),
                    })
                
                logger.info(f"Arbeitnow: fetched {len(offers)} offers")
                return offers
            except Exception as e:
                logger.error(f"Arbeitnow error: {e}", exc_info=True)
                return []
    
    async def _fetch_wwr(self, keywords: Optional[list[str]] = None) -> list[dict]:
        """
        Fetch from We Work Remotely (RSS feed).
        Uses thread pool executor to avoid blocking event loop.
        """
        url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
        
        try:
            # Run blocking feedparser in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            
            offers = []
            for entry in feed.entries:
                # Extract company from title (format: "Company: Job Title")
                title_parts = entry.title.split(":", 1)
                company = title_parts[0].strip() if len(title_parts) > 1 else "Unknown"
                job_title = title_parts[1].strip() if len(title_parts) > 1 else entry.title
                
                # Extract slug from URL for unique ID
                # entry.link format: https://weworkremotely.com/remote-jobs/company-title-hash
                url_parts = entry.link.rstrip('/').split('/')
                slug = url_parts[-1] if url_parts else entry.id
                
                offers.append({
                    "source": "WWR",
                    "jjit_id": f"wwr_{slug}",
                    "slug": slug,
                    "title": job_title,
                    "company_name": company,
                    "company_logo_url": None,
                    "city": None,
                    "country_code": None,
                    "remote": True,
                    "salary_from": None,
                    "salary_to": None,
                    "salary_currency": "USD",
                    "description": entry.get('description', entry.get('summary', '')),
                    "skills": "",  # RSS doesn't have tags
                    "offer_url": entry.link,
                })
            
            logger.info(f"WWR: fetched {len(offers)} offers")
            return offers
        except Exception as e:
            logger.error(f"WWR error: {e}", exc_info=True)
            return []


# Global instance
foreign_fetcher = ForeignFetcher()
