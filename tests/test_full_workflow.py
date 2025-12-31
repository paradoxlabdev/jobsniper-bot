"""
Integration test for full application lifecycle.
Mocks external APIs (JJIT, OpenAI) to verify end-to-end data flow.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from main import JobSniper

@pytest.mark.asyncio
async def test_full_cycle_integration(mock_settings, mock_redis_manager, mock_openai):
    """Test full processing cycle with mocked external services."""
    from main import storage_service, fetcher_service, matcher_service, notification_service
    from services.fetcher import FetcherService
    from health_server import health_server
    
    # Patch all used async methods on their global instances using patch.object
    with patch.object(storage_service, "get_system_settings", new_callable=AsyncMock) as mock_get_settings, \
         patch.object(storage_service, "get_unanalyzed_offers", new_callable=AsyncMock) as mock_get_unanalyzed, \
         patch.object(storage_service, "upsert_offers_batch", new_callable=AsyncMock) as mock_upsert, \
         patch.object(storage_service, "mark_as_notified_if_not_sent", new_callable=AsyncMock) as mock_mark_notified, \
         patch.object(storage_service, "update_match_score", new_callable=AsyncMock) as mock_update_score, \
         patch.object(storage_service, "get_statistics", new_callable=AsyncMock) as mock_get_stats, \
         patch.object(storage_service, "log_processing_run", new_callable=AsyncMock) as mock_log_run, \
         patch.object(fetcher_service, "fetch_offers", new_callable=AsyncMock) as mock_fetch, \
         patch.object(fetcher_service, "initialize", new_callable=AsyncMock) as mock_fetch_init, \
         patch.object(matcher_service, "initialize", new_callable=AsyncMock) as mock_matcher_init, \
         patch.object(matcher_service, "analyze_match", new_callable=AsyncMock) as mock_analyze, \
         patch.object(notification_service, "initialize", new_callable=AsyncMock) as mock_notify_init, \
         patch.object(notification_service, "start_polling", new_callable=AsyncMock) as mock_polling, \
         patch.object(notification_service, "send_test_message", new_callable=AsyncMock) as mock_test_msg, \
         patch.object(notification_service, "send_job_alert", new_callable=AsyncMock) as mock_notify, \
         patch.object(notification_service, "send_scan_summary", new_callable=AsyncMock) as mock_summary, \
         patch.object(health_server, "start", new_callable=AsyncMock) as mock_health_start, \
         patch.object(health_server, "stop", new_callable=AsyncMock) as mock_health_stop, \
         patch.object(FetcherService, "_filter_offers") as mock_filter:
        
        # Configure return values
        m_settings = MagicMock()
        m_settings.match_threshold = 70.0
        m_settings.auto_scan_enabled = True
        m_settings.search_keywords = "python"
        m_settings.locations = "Remote"
        m_settings.category_ids = "1"
        m_settings.enabled_sources = "jjit"
        m_settings.include_remote = True
        m_settings.keyword_match_mode = "relaxed"
        
        mock_get_settings.return_value = m_settings
        mock_get_stats.return_value = {"total_offers": 100, "last_scan": "recently"}
        mock_test_msg.return_value = True
        mock_mark_notified.return_value = True
        mock_analyze.return_value = (85.0, "Good")
        mock_notify.return_value = True
        mock_filter.return_value = [True] # Return non-empty to pass check
        
        sniper = JobSniper()
        await sniper.initialize()
        
        # Mock fetch data
        mock_fetch.return_value = [{"id": "test-1", "title": "Dev"}]
        mock_upsert.return_value = 1
        
        from models import JobOffer
        mock_offer = JobOffer(id=1, title="Dev", jjit_id="test-1", offer_url="http://ex.com")
        mock_get_unanalyzed.return_value = [mock_offer]
        
        # Run full cycle
        print("Starting run_full_cycle...")
        await sniper.run_full_cycle()
        print("Finished run_full_cycle.")
        
        # Verify
        assert mock_fetch.called, "fetch_offers was not called"
        assert mock_analyze.called, "analyze_match was not called"
        assert mock_notify.called, "send_job_alert was not called"



