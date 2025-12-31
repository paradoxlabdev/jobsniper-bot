import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.matcher import MatcherService

@pytest.fixture
def matcher():
    return MatcherService()

@pytest.mark.asyncio
async def test_matcher_initialization(matcher, mock_settings):
    """Test matcher initialization and CV loading."""
    with patch("services.matcher.PdfReader") as MockPdf:
        # Mock PDF content
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Python Developer CV"
        
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        MockPdf.return_value = mock_reader
        
        with patch("pathlib.Path.exists", return_value=True):
            await matcher.initialize()
            assert matcher.cv_text == "Python Developer CV"

@pytest.mark.asyncio
async def test_extract_keywords(matcher, mock_settings):
    """Test keyword extraction."""
    matcher.cv_text = "Experienced with Python and AWS"
    
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Python, AWS"
    
    matcher.client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    keywords = await matcher.extract_keywords()
    assert keywords == "Python, AWS"

@pytest.mark.asyncio
async def test_analyze_match(matcher, mock_settings):
    """Test match analysis."""
    matcher.cv_text = "Python Developer"
    
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Score: 85\nReasoning: Good match."
    
    matcher.client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    score, reasoning = await matcher.analyze_match(
        job_title="Senior Python Dev",
        job_description="Need Python expert",
        company_name="Tech Co"
    )
    
    assert score == 85.0
    assert reasoning == "Good match."
    
    # Verify caching
    # Call again, should not hit API (if cached)
    # Note: The current implementation has a mock that we can't easily check call count on global client unless we mock it closer.
    # But we can check that _analysis_cache is populated.
    assert len(matcher._analysis_cache) == 1

@pytest.mark.asyncio
async def test_cache_key_includes_version(matcher):
    """Test that cache key include PROMPT_VERSION."""
    key = matcher._get_cache_key("Title", "Desc", "Company")
    assert key.startswith(matcher.PROMPT_VERSION + ":")

@pytest.mark.asyncio
async def test_retry_on_openai_error(matcher, mock_settings):
    """Test that matcher retries on OpenAI API errors."""
    from openai import APIError, RateLimitError
    from unittest.mock import AsyncMock
    
    # Mock failure followed by success
    matcher.client.chat.completions.create = AsyncMock(side_effect=[
        RateLimitError("Rate limit", response=MagicMock(), body=None),
        MagicMock(choices=[MagicMock(message=MagicMock(content="Score: 80\nReasoning: OK"))])
    ])
    
    matcher.cv_text = "Python Developer"
    
    score, _ = await matcher.analyze_match("Title", "Desc", "Company")
    
    assert score == 80.0
    assert matcher.client.chat.completions.create.call_count == 2

@pytest.mark.asyncio
async def test_cv_truncation_limit(matcher):
    """Test that CV is truncated at the correct limit (6000)."""
    matcher.cv_text = "A" * 10000
    
    prompt = matcher._build_prompt("Title", "Desc", "Company", [])
    
    # Check that CV in prompt is truncated
    assert "A" * 6000 in prompt
    assert "[truncated]" in prompt

@pytest.mark.asyncio
async def test_parse_response(matcher):
    """Test parsing logic for OpenAI response."""
    
    # Standard response
    response = "Score: 90\nReasoning: Excellent fit."
    score, reasoning = matcher._parse_response(response)
    assert score == 90.0
    assert reasoning == "Excellent fit."
    
    # Missing score (defaults to 50)
    response = "Reasoning: Uncertain."
    score, reasoning = matcher._parse_response(response)
    assert score == 50.0
    
    # Score out of bounds
    response = "Score: 150\nReasoning: Overqualified"
    score, reasoning = matcher._parse_response(response)
    assert score == 100.0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
