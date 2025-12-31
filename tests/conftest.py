import pytest
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, AsyncMock
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from core import settings

@pytest.fixture(scope="session")
def event_loop():
    """Create a fresh event loop for each test session."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_settings(monkeypatch):
    """Mock environment settings for tests."""
    monkeypatch.setattr(settings, "jjit_api_url", "https://api.justjoin.it/v2/user-panel/offers/by-cursor")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "cv_path", "test_cv.pdf")
    monkeypatch.setattr(settings, "redis_enabled", True)
    monkeypatch.setattr(settings, "redis_host", "localhost")
    monkeypatch.setattr(settings, "redis_port", 6379)
    return settings

@pytest.fixture(autouse=True)
def mock_db_manager(monkeypatch):
    """Mock database manager globally."""
    from core.database import db_manager
    
    # Create a fresh mock session for each test
    session = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)
    session.close = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    
    # Mock context manager for get_session that returns the session
    @asynccontextmanager
    async def mock_get_session():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        
    monkeypatch.setattr(db_manager, "get_session", mock_get_session)
    monkeypatch.setattr(db_manager, "session_factory", MagicMock()) # Truthy for init check
    monkeypatch.setattr(db_manager, "initialize", AsyncMock(return_value=None))
    
    return session

@pytest.fixture
def mock_db_session(mock_db_manager):
    """Fixture to provide the mocked session."""
    return mock_db_manager



@pytest.fixture(autouse=True)
def mock_redis_manager(monkeypatch):
    """Fixture to mock Redis manager."""
    from core.cache import cache_manager
    mock = MagicMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock(return_value=True)
    mock.set = AsyncMock(return_value=True)
    mock.ping = AsyncMock(return_value=True)
    mock.close = AsyncMock(return_value=None)
    
    monkeypatch.setattr(cache_manager, "redis", mock)
    monkeypatch.setattr(cache_manager, "enabled", True)
    return mock

@pytest.fixture
def mock_openai(monkeypatch):
    """Fixture to mock OpenAI API."""
    mock_client = MagicMock()
    
    # Mock chat.completions.create
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Score: 85\nReasoning: Good match."
    
    mock_create = AsyncMock(return_value=mock_response)
    mock_client.chat.completions.create = mock_create
    
    from services.matcher import matcher_service
    monkeypatch.setattr(matcher_service, "client", mock_client)
    return mock_client



