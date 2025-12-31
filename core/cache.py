import json
from typing import Any, Optional
import hashlib
from redis import asyncio as aioredis
from core.config import settings
from core import setup_logger

logger = setup_logger(__name__, "cache.log")

class RedisCache:
    """
    Simple async Redis cache wrapper.
    """
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.enabled = settings.redis_enabled
        self.ttl = 300  # Default TTL 5 minutes

    async def initialize(self):
        """Initialize Redis connection if enabled."""
        if not self.enabled:
            return

        try:
            url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
            self.redis = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
            await self.redis.ping()
            logger.info(f"Redis cache initialized at {url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis = None
            self.enabled = False

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")

    def _generate_key(self, prefix: str, *args) -> str:
        """Generate a unique cache key based on args."""
        key_content = f"{prefix}:" + "|".join(str(arg) for arg in args)
        return hashlib.md5(key_content.encode()).hexdigest()

    async def get(self, prefix: str, *args) -> Optional[Any]:
        """Get value from cache."""
        if not self.enabled or not self.redis:
            return None

        key = self._generate_key(prefix, *args)
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT for key: {key}")
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
        
        logger.debug(f"Cache MISS for key: {key}")
        return None

    async def set(self, value: Any, prefix: str, *args, ttl: int = 300):
        """Set value in cache."""
        if not self.enabled or not self.redis:
            return

        key = self._generate_key(prefix, *args)
        try:
            await self.redis.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

# Global cache instance
cache_manager = RedisCache()
