"""
Unit tests for FetcherService filter logic.
Tests keyword matching, remote/location filtering, and edge cases.
"""
import pytest
from services.fetcher import FetcherService


class TestFilterOffers:
    """Test suite for _filter_offers static method."""
    
    def test_relaxed_keyword_mode_single_match(self):
        """Test relaxed mode requires only 1 keyword match."""
        offers = [
            {
                "title": "Python Developer",
                "description": "We need a Python expert",
                "skills": ["Python"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python", "Java", "Go"],
            keyword_match_mode="relaxed",
            remote=True,
            locations=["Warsaw"]
        )
        
        assert len(result) == 1  # Passes with 1 match
    
    def test_moderate_keyword_mode_40_percent(self):
        """Test moderate mode requires 40% keyword match."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python and Java experience needed",
                "skills": ["Python"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        # 5 keywords, needs 2 matches (40%)
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python", "Java", "Go", "Rust", "C++"],
            keyword_match_mode="moderate",
            remote=True,
            locations=["Warsaw"]
        )
        
        assert len(result) == 1  # Has Python and Java = 2/5 = 40%
    
    def test_strict_keyword_mode_80_percent(self):
        """Test strict mode requires 80% keyword match."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python and Django",
                "skills": ["Python", "Django"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        # 5 keywords, needs 4 matches (80%)
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python", "Django", "Go", "Rust", "C++"],
            keyword_match_mode="strict",
            remote=True,
            locations=["Warsaw"]
        )
        
        assert len(result) == 0  # Only has 2/5 = 40%, needs 80%
    
    def test_remote_filtering_reject_fully_remote(self):
        """Test that remote=False rejects fully remote offers."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "remote",
                "city": None,
                "remote": True
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=False,  # User doesn't want remote
            locations=None
        )
        
        assert len(result) == 0  # Rejected
    
    def test_remote_filtering_accept_hybrid(self):
        """Test that remote=False accepts hybrid offers."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "partly_remote",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=False,
            locations=["Warsaw"]
        )
        
        assert len(result) == 1  # Hybrid is OK
    
    def test_location_filter_with_remote_enabled(self):
        """Test location filter with remote=True accepts remote jobs."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "remote",
                "city": "Berlin",  # Not in location list
                "remote": True
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=True,
            locations=["Warsaw", "London"]
        )
        
        assert len(result) == 1  # Remote jobs pass even if city doesn't match
    
    def test_location_filter_strict_city_match(self):
        """Test strict city matching when remote=False."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "office",
                "city": "Berlin",
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=False,
            locations=["Warsaw", "London"]
        )
        
        assert len(result) == 0  # Berlin not in list, rejected
    
    def test_no_keywords_specified(self):
        """Test that empty keyword list passes all offers."""
        offers = [
            {
                "title": "Any Developer",
                "description": "Description",
                "skills": [],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=None,
            keyword_match_mode="relaxed",
            remote=True,
            locations=["Warsaw"]
        )
        
        assert len(result) == 1  # No keyword filter = pass
    
    def test_no_locations_specified_accepts_all(self):
        """Test that empty location list accepts all cities."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "office",
                "city": "Tokyo",  # Random city
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=True,
            locations=None  # No location filter
        )
        
        assert len(result) == 1  # Any city passes
    
    def test_case_insensitive_keyword_matching(self):
        """Test that keyword matching is case-insensitive."""
        offers = [
            {
                "title": "PYTHON Developer",
                "description": "We need PYTHON",
                "skills": ["python"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],  # Mixed case
            keyword_match_mode="relaxed",
            remote=True,
            locations=["Warsaw"]
        )
        
        assert len(result) == 1  # Case insensitive match
    
    def test_multiple_offers_mixed_results(self):
        """Test filtering multiple offers with mixed pass/fail."""
        offers = [
            {
                "title": "Python Developer",
                "description": "Python",
                "skills": ["Python"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            },
            {
                "title": "Java Developer",
                "description": "Java",
                "skills": ["Java"],
                "workplaceType": "office",
                "city": "Warsaw",
                "remote": False
            },
            {
                "title": "Python and Java Developer",
                "description": "Python and Java",
                "skills": ["Python", "Java"],
                "workplaceType": "remote",
                "city": None,
                "remote": True
            }
        ]
        
        result = FetcherService._filter_offers(
            offers=offers,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=True,
            locations=["Warsaw"]
        )
        
        # Should pass: offers 0 and 2 (both have Python)
        # Should fail: offer 1 (only Java)
        assert len(result) == 2


class TestFetcherServiceAsync:
    """Async tests for FetcherService using mocks."""

    @pytest.mark.asyncio
    async def test_fetch_offers_params_construction(self, mock_settings):
        """Test that fetch_offers constructs categories[] params correctly."""
        from services.fetcher import FetcherService
        from unittest.mock import AsyncMock, patch
        
        async with FetcherService() as fetcher:
            # Mock _fetch_with_retry instead of lower level session to isolate logic
            fetcher._fetch_with_retry = AsyncMock(return_value={
                "data": [{"id": "1", "title": "Test Offer"}],
                "meta": {"totalCount": 1}
            })
            
            await fetcher.fetch_offers(
                category_ids=["5", "1"],
                keywords=["Python"],
                remote=True
            )
            
            # Verify params passed to _fetch_with_retry
            # It should be a list of tuples containing ('categories[]', '5') and ('categories[]', '1')
            args, kwargs = fetcher._fetch_with_retry.call_args
            params = kwargs.get("params")
            
            # Check for multiple categories[] keys
            cat_params = [p for p in params if p[0] == "categories[]"]
            assert len(cat_params) == 2
            assert cat_params[0][1] == "5"
            assert cat_params[1][1] == "1"

    @pytest.mark.asyncio
    async def test_fetch_offers_paging(self, mock_settings):
        """Test that fetch_offers handles multiple pages."""
        from services.fetcher import FetcherService
        from unittest.mock import AsyncMock
        
        async with FetcherService() as fetcher:
            # Mock two pages of results
            mock_data_p1 = {
                "data": [{"id": str(i), "title": f"Offer {i}"} for i in range(100)],
                "meta": {"totalCount": 150}
            }
            mock_data_p2 = {
                "data": [{"id": str(i), "title": f"Offer {i}"} for i in range(100, 150)],
                "meta": {"totalCount": 150}
            }
            
            fetcher._fetch_with_retry = AsyncMock()
            fetcher._fetch_with_retry.side_effect = [mock_data_p1, mock_data_p2]
            
            offers = await fetcher.fetch_offers(keywords=None)
            
            assert len(offers) == 150
            assert fetcher._fetch_with_retry.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

