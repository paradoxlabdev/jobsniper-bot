"""
Database connection and session management.
Uses asyncpg with SQLAlchemy 2.0 async engine.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core import setup_logger, settings
from models import Base

logger = setup_logger(__name__, "database.log")


class DatabaseManager:
    """Manages database connections and sessions."""
    
    def __init__(self):
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None
    
    async def initialize(self) -> None:
        """Initialize database engine and create tables."""
        try:
            logger.info(f"Connecting to database: {settings.postgres_db}")
            
            self.engine = create_async_engine(
                settings.database_url,
                echo=False,
                pool_size=10,        # For production: consider 20+ based on concurrent load
                max_overflow=20,     # For production: consider 30+ (50 total connections)
                pool_pre_ping=True,  # Verify connections before using ✅
                pool_recycle=3600,   # Recycle connections every hour
                pool_timeout=30,     # Timeout for acquiring connection from pool
            )
            
            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                
                # Ensure new columns are added if the table already existed
                from sqlalchemy import text
                
                # Add workplace_type column if missing
                await conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN IF NOT EXISTS workplace_type VARCHAR(50)
                """))
                
                # Migrate datetime columns to timezone-aware (idempotent)
                try:
                    await conn.execute(text("""
                        ALTER TABLE job_offers 
                        ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING created_at AT TIME ZONE 'UTC'
                    """))
                    await conn.execute(text("""
                        ALTER TABLE job_offers 
                        ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING updated_at AT TIME ZONE 'UTC'
                    """))
                    await conn.execute(text("""
                        ALTER TABLE job_offers 
                        ALTER COLUMN published_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING published_at AT TIME ZONE 'UTC'
                    """))
                    await conn.execute(text("""
                        ALTER TABLE job_offers 
                        ALTER COLUMN notified_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING notified_at AT TIME ZONE 'UTC'
                    """))
                    
                    # Migrate processing_logs timestamps
                    await conn.execute(text("""
                        ALTER TABLE processing_logs 
                        ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING started_at AT TIME ZONE 'UTC'
                    """))
                    await conn.execute(text("""
                        ALTER TABLE processing_logs 
                        ALTER COLUMN completed_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING completed_at AT TIME ZONE 'UTC'
                    """))
                    
                    # Migrate system_settings timestamp
                    await conn.execute(text("""
                        ALTER TABLE system_settings 
                        ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE 
                        USING updated_at AT TIME ZONE 'UTC'
                    """))
                    
                    logger.info("Timezone-aware datetime migration completed successfully")
                except Exception as e:
                    # Migration may fail if columns are already timezone-aware (idempotent)
                    logger.debug(f"Datetime migration skipped (already applied or error): {e}")
                
                # Add keyword_match_mode column if it doesn't exist
                try:
                    await conn.execute(text("""
                        ALTER TABLE system_settings 
                        ADD COLUMN IF NOT EXISTS keyword_match_mode VARCHAR(20) DEFAULT 'relaxed'
                    """))
                    logger.info("keyword_match_mode column added successfully")
                except Exception as e:
                    logger.debug(f"keyword_match_mode column migration skipped: {e}")
                
                # Add notification_hash column if it doesn't exist
                try:
                    await conn.execute(text("""
                        ALTER TABLE job_offers 
                        ADD COLUMN IF NOT EXISTS notification_hash VARCHAR(64)
                    """))
                    await conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_notification_hash 
                        ON job_offers(notification_hash)
                    """))
                    logger.info("notification_hash column and index added successfully")
                except Exception as e:
                    logger.debug(f"notification_hash column migration skipped: {e}")

                # Add auto_scan_enabled column if it doesn't exist
                try:
                    await conn.execute(text("""
                        ALTER TABLE system_settings 
                        ADD COLUMN IF NOT EXISTS auto_scan_enabled BOOLEAN DEFAULT TRUE
                    """))
                    logger.info("auto_scan_enabled column added successfully")
                except Exception as e:
                    logger.debug(f"auto_scan_enabled column migration skipped: {e}")
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise
    
    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session as an async context manager.
        
        Usage:
            async with db_manager.get_session() as session:
                result = await session.execute(query)
        """
        if not self.session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Global database manager instance
db_manager = DatabaseManager()
