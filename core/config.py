"""
Configuration management using Pydantic Settings.
Loads and validates environment variables.
"""
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Database
    postgres_user: str = Field(..., description="PostgreSQL username")
    postgres_password: str = Field(..., description="PostgreSQL password")
    postgres_db: str = Field(..., description="PostgreSQL database name")
    postgres_host: str = Field(default="db", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    database_url: str = Field(..., description="Full database URL")
    
    # Redis Cache
    redis_host: str = Field(default="redis", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_enabled: bool = Field(default=True, description="Enable Redis caching")
    
    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model to use")
    
    # Telegram
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    telegram_chat_id: str = Field(..., description="Telegram chat ID for notifications")
    
    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_key(cls, v: str) -> str:
        """Validate OpenAI API key format."""
        if not v.startswith("sk-"):
            raise ValueError("OpenAI API key must start with 'sk-'")
        return v
    
    # Just Join IT
    jjit_api_url: str = Field(
        default="https://api.justjoin.it/v2/user-panel/offers/by-cursor",
        description="Just Join IT API endpoint (v2)"
    )
    jjit_category_ids: str = Field(
        default="5",
        description="Comma-separated category IDs (5=Python, 1=JavaScript, etc.)"
    )
    jjit_fetch_interval: int = Field(
        default=300,
        description="Fetch interval in seconds"
    )
    jjit_search_keywords: str = Field(
        default="Python,Remote",
        description="Comma-separated search keywords"
    )
    jjit_locations: str = Field(
        default="",
        description="Comma-separated list of preferred cities (e.g. Warszawa,Krakow)"
    )
    
    # Matcher
    match_threshold: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Minimum match score to trigger notification"
    )
    cv_path: str = Field(
        default="/app/data/cv.pdf",
        description="Path to CV PDF file"
    )
    
    # Application
    log_level: str = Field(default="INFO", description="Logging level")
    retry_max_attempts: int = Field(default=3, description="Max retry attempts")
    retry_backoff_factor: int = Field(default=2, description="Retry backoff multiplier")
    
    @field_validator("jjit_search_keywords")
    @classmethod
    def parse_keywords(cls, v: str) -> list[str]:
        """Parse comma-separated keywords into a list."""
        return [kw.strip() for kw in v.split(",") if kw.strip()]
    
    @field_validator("jjit_category_ids")
    @classmethod
    def parse_category_ids(cls, v: str) -> list[str]:
        """Parse comma-separated category IDs into a list."""
        return [cid.strip() for cid in v.split(",") if cid.strip()]
    
    @field_validator("jjit_locations")
    @classmethod
    def parse_locations(cls, v: str) -> list[str]:
        """Parse comma-separated locations into a list."""
        return [loc.strip() for loc in v.split(",") if loc.strip()]


# Global settings instance
settings = Settings()
