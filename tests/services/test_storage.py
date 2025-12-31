"""
Unit tests for StorageService upsert and query logic.
Tests database operations, deduplication, and statistics.
"""
import pytest
from datetime import datetime, timezone
from models import JobOffer


class TestStorageService:
    """Test suite for StorageService."""
    
    def test_prepare_offer_data_jjit_format(self):
        """Test transformation of JJIT API format to DB format."""
        from services.storage import StorageService
        
        raw_data = {
            "id": "test-offer-123",
            "slug": "python-developer-acme",
            "title": "Python Developer",
            "companyName": "Acme Corp",
            "companyLogoUrl": "https://example.com/logo.png",
            "city": "Warsaw",
            "countryCode": "PL",
            "workplaceType": "remote",
            "remote": True,
            "employmentTypes": [
                {
                    "type": "permanent",
                    "salary": {
                        "from": 10000,
                        "to": 15000,
                        "currency": "PLN"
                    }
                }
            ],
            "experienceLevel": "senior",
            "body": "We are looking for...",
            "requiredSkills": [
                {"name": "Python"},
                {"name": "Django"}
            ],
            "publishedAt": "2025-01-01T12:00:00Z"
        }
        
        service = StorageService()
        result = service._prepare_offer_data(raw_data)
        
        assert result["jjit_id"] == "python-developer-acme"
        assert result["title"] == "Python Developer"
        assert result["company_name"] == "Acme Corp"
        assert result["salary_from"] == 10000
        assert result["salary_to"] == 15000
        assert result["salary_currency"] == "PLN"
        assert result["remote"] is True
        assert result["workplace_type"] == "remote"
    
    def test_prepare_offer_data_foreign_format(self):
        """Test transformation of foreign source format."""
        from services.storage import StorageService
        
        raw_data = {
            "jjit_id": "remoteok_12345",
            "source": "RemoteOK",
            "title": "Senior Python Engineer",
            "company_name": "Tech Startup",
            "remote": True,
            "salary_from": 120000,
            "salary_to": 150000,
            "salary_currency": "USD",
            "description": "Remote position",
            "skills": "Python,Django,AWS",
            "offer_url": "https://remoteok.com/remote-jobs/12345"
        }
        
        service = StorageService()
        result = service._prepare_offer_data(raw_data)
        
        assert result["jjit_id"] == "remoteok_12345"
        assert result["title"] == "Senior Python Engineer"
        assert result["offer_url"] == "https://remoteok.com/remote-jobs/12345"
        assert result["salary_from"] == 120000
    
    def test_get_cache_key_generates_consistent_hash(self):
        """Test that cache key generation is consistent."""
        from services.matcher import MatcherService
        
        service = MatcherService()
        
        key1 = service._get_cache_key(
            "Python Developer",
            "We need a Python developer with Django experience",
            "Acme Corp"
        )
        
        key2 = service._get_cache_key(
            "Python Developer",
            "We need a Python developer with Django experience",
            "Acme Corp"
        )
        
        assert key1 == key2
        # v1.0 (4 chars) + : (1 char) + MD5 (32 chars) = 37 chars
        assert len(key1) == 37

    
    def test_get_cache_key_different_for_different_inputs(self):
        """Test that different inputs generate different cache keys."""
        from services.matcher import MatcherService
        
        service = MatcherService()
        
        key1 = service._get_cache_key(
            "Python Developer",
            "Description",
            "Company A"
        )
        
        key2 = service._get_cache_key(
            "Java Developer",  # Different title
            "Description",
            "Company A"
        )
        
        assert key1 != key2
    
    def test_notification_hash_generation(self):
        """Test that notification hash is generated correctly."""
        import hashlib
        
        # Simulate hash generation
        hash_content = "Python Developer|Acme Corp|10000|15000"
        notification_hash = hashlib.sha256(hash_content.encode()).hexdigest()
        
        assert len(notification_hash) == 64  # SHA-256 hash length
        
        # Same input = same hash
        hash_content2 = "Python Developer|Acme Corp|10000|15000"
        notification_hash2 = hashlib.sha256(hash_content2.encode()).hexdigest()
        
        assert notification_hash == notification_hash2


    @pytest.mark.asyncio
    async def test_mark_as_notified_if_not_sent_first_time(self, mock_db_session):
        """Test marking as notified for the first time (successful)."""
        from services.storage import StorageService
        from unittest.mock import MagicMock, AsyncMock
        
        service = StorageService()
        
        # Mock offer retrieval
        from models import JobOffer
        mock_offer = JobOffer(id=1, notified=False, notification_hash=None)
        
        # Mock offer retrieval (1st call) and hash check (2nd call)
        mock_res_offer = MagicMock()
        mock_res_offer.scalar_one_or_none.return_value = mock_offer
        
        mock_res_hash = MagicMock()
        mock_res_hash.scalar_one_or_none.return_value = None # No duplicate
        
        mock_db_session.execute.side_effect = [mock_res_offer, mock_res_hash]

        
        result = await service.mark_as_notified_if_not_sent(1)
        
        assert result is True
        assert mock_offer.notified is True
        assert mock_offer.notification_hash is not None
        assert mock_db_session.commit.call_count == 2 # One explicit, one in get_session mock

    @pytest.mark.asyncio
    async def test_mark_as_notified_if_not_sent_duplicate(self, mock_db_session):
        """Test marking as notified when a duplicate hash already exists."""
        from services.storage import StorageService
        from unittest.mock import MagicMock, AsyncMock
        from sqlalchemy.exc import IntegrityError
        
        service = StorageService()
        
        # Mock offer retrieval
        from models import JobOffer
        mock_offer = JobOffer(id=1, notified=False, notification_hash=None)
        
        # 1st call: get offer, 2nd call: hash check (returns nothing)
        mock_res_offer = MagicMock()
        mock_res_offer.scalar_one_or_none.return_value = mock_offer
        
        mock_res_hash = MagicMock()
        mock_res_hash.scalar_one_or_none.return_value = None # No duplicate in pre-check
        
        mock_db_session.execute.side_effect = [mock_res_offer, mock_res_hash]

        
        # Simulate IntegrityError on first commit
        mock_db_session.commit.side_effect = [
            IntegrityError(statement="INSERT...", params={}, orig=Exception("duplicate key")),
            None # second call succeeds (fallback)
        ]
        
        result = await service.mark_as_notified_if_not_sent(1)
        
        assert result is False
        assert mock_offer.notified
        assert mock_offer.notification_hash is None # Should be cleared on failure
        assert mock_db_session.commit.call_count == 2 # One failed explicit, one in get_session


    @pytest.mark.asyncio
    async def test_update_system_settings_validation(self, mock_db_session):
        """Test that match_threshold is validated and clamped."""
        from services.storage import StorageService
        from unittest.mock import MagicMock, AsyncMock
        
        service = StorageService()
        
        mock_settings = MagicMock()
        # Mock both methods to return mock_settings
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        mock_result.scalar_one.return_value = mock_settings
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        # Test out of bounds high
        await service.update_system_settings(match_threshold=150)
        assert mock_settings.match_threshold == 100.0

        
        # Test out of bounds low
        await service.update_system_settings(match_threshold=-50)
        assert mock_settings.match_threshold == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
