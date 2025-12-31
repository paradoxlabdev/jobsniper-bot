"""
Matcher Service - AI-powered CV matching using OpenAI.
Analyzes job descriptions against CV and provides match scores.
"""
import asyncio
from pathlib import Path
from typing import Optional
from collections import OrderedDict
import re
import hashlib
import json

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError
from pypdf import PdfReader
import redis.asyncio as aioredis
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from core import setup_logger, settings
from core.circuit_breaker import openai_circuit_breaker, CircuitBreakerOpenError

logger = setup_logger(__name__, "matcher.log")


class MatcherService:
    """
    Service for matching job offers against CV using OpenAI.
    
    Features:
    - PDF CV parsing
    - GPT-4o-mini analysis
    - Structured scoring (0-100)
    - Match reasoning
    - LRU cache with size limit
    """
    
    PROMPT_VERSION = "v1.0"  # Bump this when prompt logic changes to invalidate cache
    MAX_CACHE_SIZE = 1000  # Maximum entries in RAM cache (LRU eviction)
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.cv_text: Optional[str] = None
        self._analysis_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()  # LRU cache
        self._openai_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent OpenAI requests
        self._redis: Optional[aioredis.Redis] = None  # Redis connection
        self._redis_enabled = settings.redis_enabled
    
    async def initialize(self) -> None:
        """Initialize service by loading CV and connecting to Redis."""
        try:
            # Load CV
            self.cv_text = self._load_cv(settings.cv_path)
            logger.info(f"CV loaded: {len(self.cv_text)} characters")
        except FileNotFoundError:
            logger.warning("CV file not found. Waiting for user to upload via Telegram.")
            self.cv_text = None
        except Exception as e:
            logger.error(f"Failed to load CV: {e}", exc_info=True)
            self.cv_text = None
        
        # Initialize Redis connection if enabled
        if self._redis_enabled:
            try:
                self._redis = await aioredis.from_url(
                    f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                # Test connection
                await self._redis.ping()
                logger.info("Redis cache connected successfully")
                
                # CACHE WARMING: Load existing cache entries from Redis to RAM
                try:
                    cursor = 0
                    loaded = 0
                    logger.info("Starting cache warm-up from Redis...")
                    
                    while True:
                        cursor, keys = await self._redis.scan(cursor, match="ai_cache:*", count=100)
                        for key in keys:
                            try:
                                cached_data = await self._redis.get(key)
                                if cached_data:
                                    result = json.loads(cached_data)
                                    # Extract cache key (remove "ai_cache:" prefix)
                                    cache_key = key.replace("ai_cache:", "")
                                    self._analysis_cache[cache_key] = (
                                        float(result["score"]), 
                                        str(result["reasoning"])
                                    )
                                    loaded += 1
                            except Exception as e:
                                logger.warning(f"Failed to load cache key {key}: {e}")
                        
                        if cursor == 0:
                            break
                    
                    logger.info(f"✅ Cache warmed up: {loaded} entries loaded from Redis to RAM")
                except Exception as e:
                    logger.warning(f"Cache warm-up failed: {e}. Starting with empty cache.")
                    
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}. Using in-memory cache only.")
                self._redis = None
                self._redis_enabled = False
            
    async def reload_cv(self) -> bool:
        """
        Reload CV from disk. Called after new upload.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.cv_text = self._load_cv(settings.cv_path)
            
            # CRITICAL: Clear both in-memory and Redis cache when CV changes
            self._analysis_cache.clear()
            
            if self._redis_enabled and self._redis:
                try:
                    # Clear all AI cache keys in Redis (they start with "ai_cache:")
                    cursor = 0
                    while True:
                        cursor, keys = await self._redis.scan(cursor, match="ai_cache:*", count=100)
                        if keys:
                            await self._redis.delete(*keys)
                        if cursor == 0:
                            break
                    logger.info("Redis cache cleared after CV reload")
                except Exception as e:
                    logger.warning(f"Failed to clear Redis cache: {e}")
            
            logger.info("CV reloaded successfully and all caches cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to reload CV: {e}")
            return False

    async def clear_cv(self) -> bool:
        """
        Delete CV file and clear in-memory text.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            path = Path(settings.cv_path)
            if path.exists():
                path.unlink()
                logger.info(f"CV file deleted: {path}")
            
            self.cv_text = None
            return True
        except Exception as e:
            logger.error(f"Failed to clear CV: {e}")
            return False
            
    def _load_cv(self, cv_path: str) -> str:
        """
        Load and parse CV from PDF file.
        
        Args:
            cv_path: Path to CV PDF file
        
        Returns:
            Extracted text from CV
        
        Raises:
            FileNotFoundError: If CV file doesn't exist
            Exception: On PDF parsing errors
        """
        path = Path(cv_path)
        
        if not path.exists():
            raise FileNotFoundError(f"CV file not found: {cv_path}")
        
        try:
            reader = PdfReader(path)
            text_parts = []
            
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            full_text = "\n".join(text_parts)
            
            # Clean up text
            full_text = re.sub(r'\s+', ' ', full_text)
            full_text = full_text.strip()
            
            if not full_text:
                raise ValueError("CV PDF appears to be empty")
            
            logger.debug(f"Extracted {len(full_text)} characters from CV")
            return full_text
            
        except Exception as e:
            logger.error(f"Failed to parse CV PDF: {e}", exc_info=True)
            raise
    
    def _get_cache_key(self, job_title: str, job_description: str, company_name: str) -> str:
        """
        Generate cache key for analysis results.
        Includes PROMPT_VERSION to invalidate cache when prompt changes.
        """
        # Use first 500 chars of description to avoid huge keys
        content = f"{job_title}:{company_name}:{job_description[:500]}"
        hash_val = hashlib.md5(content.encode()).hexdigest()
        # Prefix with version for easy visibility and management
        return f"{self.PROMPT_VERSION}:{hash_val}"
    
    async def extract_keywords(self, cv_text: Optional[str] = None) -> str:
        """
        Use AI to extract core technical keywords from the CV.
        
        Returns:
            Comma-separated list of keywords or empty string
        """
        text = cv_text or self.cv_text
        if not text:
            return ""
            
        try:
            logger.info("Extracting keywords from CV using AI...")
            
            # Add timeout to prevent hanging
            try:
                async with asyncio.timeout(30):  # 30 second timeout
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "You are a technical recruiter. Extract the 5-10 most important technical keywords (languages, frameworks, tools) from the following CV. Output ONLY the keywords separated by commas, no other text."},
                            {"role": "user", "content": text[:8000]} # Limit characters
                        ],
                        temperature=0.3,
                    )
            except asyncio.TimeoutError:
                logger.error("OpenAI API timeout (30s) during keyword extraction")
                return ""
            
            keywords = response.choices[0].message.content.strip()
            # Basic validation: ensure it's not a sentence
            if "." in keywords and " " in keywords and len(keywords.split()) > 20:
                logger.warning(f"AI returned unexpected keyword format: {keywords}")
                return ""
                
            logger.info(f"Extracted keywords: {keywords}")
            return keywords
            
        except Exception as e:
            logger.error(f"Failed to extract keywords: {e}")
            return ""

    async def analyze_match(
        self,
        job_title: str,
        job_description: str,
        company_name: str,
        skills: Optional[list[str]] = None,
        source: str = "Unknown",
    ) -> tuple[float, str]:
        """
        Analyze how well a job matches the CV.
        Uses Redis cache if available, falls back to in-memory cache.
        """
        if not self.cv_text:
            return 0.0, "CV not loaded yet. Waiting for upload."
        
        # Generate cache key
        cache_key = self._get_cache_key(job_title, job_description, company_name)
        
        # Try Redis cache first
        if self._redis_enabled and self._redis:
            try:
                cached_data = await self._redis.get(f"ai_cache:{cache_key}")
                if cached_data:
                    result = json.loads(cached_data)
                    logger.debug(f"Redis cache hit for {job_title} at {company_name}")
                    return result["score"], result["reasoning"]
            except Exception as e:
                logger.warning(f"Redis cache read error: {e}")
        
        # Try in-memory cache
        if cache_key in self._analysis_cache:
            logger.debug(f"In-memory cache hit for {job_title} at {company_name}")
            return self._analysis_cache[cache_key]
        
        try:
            # Build prompt
            prompt = self._build_prompt(
                job_title=job_title,
                job_description=job_description,
                company_name=company_name,
                skills=skills,
            )
            
            # Log analysis details
            skills_str = ", ".join(skills[:5]) if skills else "None"
            if skills and len(skills) > 5:
                skills_str += f" +{len(skills)-5} more"
            desc_preview = job_description[:200] + "..." if job_description and len(job_description) > 200 else (job_description or "")
            
            logger.info(
                f"🔍 Analyzing [{source}]: {job_title} @ {company_name}\n"
                f"   Skills: {skills_str}\n"
                f"   Description: {desc_preview}"
            )
            
            # Call OpenAI API with rate limiting, timeout, and circuit breaker
            async with self._openai_semaphore:
                try:
                    response = await openai_circuit_breaker.call(
                        self._call_openai_with_retry,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert recruiter and career advisor. "
                                    "Analyze job offers against candidate CVs and provide "
                                    "accurate match scores with clear reasoning."
                                )
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        temperature=0.3,
                        max_tokens=500
                    )
                except CircuitBreakerOpenError:
                    # Circuit breaker is open - graceful degradation
                    logger.warning(
                        f"⚠️ Circuit breaker OPEN for OpenAI API. "
                        f"Skipping analysis for {job_title} @ {company_name}. "
                        f"Using cached results only."
                    )
                    return (
                        0.0,
                        "AI analysis temporarily unavailable due to API issues. "
                        "Please try again later or check cached results."
                    )
            
            # Parse response
            content = response.choices[0].message.content
            score, reasoning = self._parse_response(content)
            
            logger.info(
                f"✅ Match analysis complete: {job_title} - Score: {score}/100\n"
                f"   Reasoning: {reasoning[:150]}{'...' if len(reasoning) > 150 else ''}"
            )
            
            # Cache the result in both stores
            result = (score, reasoning)
            
            # Store in Redis with adaptive TTL based on score
            if self._redis_enabled and self._redis:
                try:
                    cache_data = json.dumps({"score": score, "reasoning": reasoning})
                    
                    # Adaptive TTL: High scores cache longer, low scores shorter
                    if score >= 80:
                        ttl = 604800  # 7 days - high matches are valuable, cache longer
                    elif score >= 50:
                        ttl = 86400   # 24 hours - medium scores, standard cache
                    else:
                        ttl = 21600   # 6 hours - low scores may improve with CV update
                    
                    await self._redis.set(
                        f"ai_cache:{cache_key}",
                        cache_data,
                        ex=ttl
                    )
                    logger.debug(f"Cached in Redis: {job_title} (TTL: {ttl//3600}h, score: {score})")
                except Exception as e:
                    logger.warning(f"Redis cache write error: {e}")
            
            # Store in memory as fallback with LRU eviction
            self._analysis_cache[cache_key] = result
            self._analysis_cache.move_to_end(cache_key)  # Mark as recently used
            
            # Trim cache if too large (LRU eviction)
            if len(self._analysis_cache) > self.MAX_CACHE_SIZE:
                # Remove oldest (first) item
                evicted_key = next(iter(self._analysis_cache))
                self._analysis_cache.pop(evicted_key)
                logger.debug(f"LRU cache evicted oldest entry (size: {len(self._analysis_cache)}/{self.MAX_CACHE_SIZE})")
            
            logger.debug(f"Cached in memory: {job_title} (cache size: {len(self._analysis_cache)})")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to analyze match: {e}", exc_info=True)
            raise
    
    def _build_prompt(
        self,
        job_title: str,
        job_description: str,
        company_name: str,
        skills: Optional[list[str]],
    ) -> str:
        """
        Build analysis prompt for OpenAI.
        
        Args:
            job_title: Job title
            job_description: Job description
            company_name: Company name
            skills: Required skills
        
        Returns:
            Formatted prompt string
        """
        skills_text = ", ".join(skills) if skills else "Not specified"
        
        # Truncate CV and description if too long
        max_cv_length = 6000  # Increased limit for detailed CVs
        max_desc_length = 3000
        
        cv_text = self.cv_text[:max_cv_length]
        if len(self.cv_text) > max_cv_length:
            cv_text += "... [truncated]"
        
        desc_text = job_description[:max_desc_length] if job_description else "Not provided"
        if job_description and len(job_description) > max_desc_length:
            desc_text += "... [truncated]"
        
        prompt = f"""
Analyze how well this job offer matches the candidate's CV.

**CANDIDATE CV:**
{cv_text}

**JOB OFFER:**
- Title: {job_title}
- Company: {company_name}
- Required Skills: {skills_text}
- Description: {desc_text}

**TASK:**
Provide a match score from 0-100 and a brief explanation (2-3 sentences).

**SCORING CRITERIA:**
- 90-100: Perfect match - candidate meets all requirements and has relevant experience
- 70-89: Strong match - candidate meets most requirements with minor gaps
- 50-69: Moderate match - candidate has some relevant skills but significant gaps
- 30-49: Weak match - limited overlap in skills/experience
- 0-29: Poor match - minimal or no relevant experience

**IMPORTANT - INTERNATIONAL OFFERS:**
- If salary is in YEARLY format (e.g., "$120k/yr", "$100,000-150,000"), note it in reasoning
- Check description for timezone/location restrictions:
  * "US Only", "North America Only", "EST/PST timezone required" → If candidate is in Europe (Poland), reduce score significantly or set to 0
  * "Remote worldwide", "Europe-friendly", "Async work" → No penalty
- Consider visa sponsorship if mentioned (positive factor)

**OUTPUT FORMAT:**
Score: [number 0-100]
Reasoning: [2-3 sentence explanation focusing on key matches or gaps, mention any location/timezone concerns]

Be objective and specific. Focus on technical skills, experience level, and job requirements.
"""
        return prompt.strip()
    
    def _parse_response(self, response: str) -> tuple[float, str]:
        """
        Parse OpenAI response to extract score and reasoning.
        
        Args:
            response: Raw response from OpenAI
        
        Returns:
            Tuple of (score, reasoning)
        """
        try:
            # Extract score
            score_match = re.search(r'Score:\s*(\d+)', response, re.IGNORECASE)
            if score_match:
                score = float(score_match.group(1))
                score = max(0, min(100, score))  # Clamp to 0-100
            else:
                logger.warning("Could not parse score from response, defaulting to 50")
                score = 50.0
            
            # Extract reasoning
            reasoning_match = re.search(
                r'Reasoning:\s*(.+)',
                response,
                re.IGNORECASE | re.DOTALL
            )
            if reasoning_match:
                reasoning = reasoning_match.group(1).strip()
                # Limit reasoning length
                reasoning = reasoning[:500]
            else:
                reasoning = response[:500]  # Use full response if no "Reasoning:" found
            
            return score, reasoning
            
        except Exception as e:
            logger.error(f"Failed to parse response: {e}", exc_info=True)
            return 50.0, "Failed to parse AI response"


    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        reraise=True
    )
    async def _call_openai_with_retry(self, messages: list, temperature: float = 0.3, max_tokens: int = 500):
        """Helper to call OpenAI with retry logic."""
        return await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=30  # 30s timeout per attempt
        )


# Global matcher service instance
matcher_service = MatcherService()
