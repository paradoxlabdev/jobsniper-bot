"""
Database models for JobSniper.
Uses SQLAlchemy 2.0 with async support.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, DateTime, Boolean, Float, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class SystemSettings(Base):
    """
    Runtime configuration settings stored in DB.
    Allows changing filters without restart.
    """
    __tablename__ = "system_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Core Filters
    locations: Mapped[str] = mapped_column(String(1000), default="")  # CSV: Warszawa,Krakow
    include_remote: Mapped[bool] = mapped_column(Boolean, default=True)
    search_keywords: Mapped[str] = mapped_column(String(1000), default="Python")
    keyword_match_mode: Mapped[str] = mapped_column(String(20), default="relaxed")  # relaxed, moderate, strict
    category_ids: Mapped[str] = mapped_column(String(500), default="5")  # 5=Python
    match_threshold: Mapped[int] = mapped_column(Integer, default=80)
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Job Sources
    enabled_sources: Mapped[str] = mapped_column(String(500), default="jjit,remoteok,remotive,arbeitnow,weworkremotely")  # CSV: jjit,remoteok,remotive
    
    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<SystemSettings(locations='{self.locations}', remote={self.include_remote})>"


class JobOffer(Base):
    """
    Job offer model storing data from Just Join IT.
    """
    __tablename__ = "job_offers"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Just Join IT specific fields
    jjit_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Job details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_logo_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    
    # Location & Remote
    city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    workplace_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Salary information
    salary_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    
    # Experience & Employment
    experience_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Description & Skills
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skills: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    
    # URLs
    offer_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    apply_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    
    # AI Matching
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Notification tracking
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    notification_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
        comment="Hash of notification content to prevent duplicate alerts"
    )
    
    # Timestamps
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Indexes for performance
    __table_args__ = (
        Index("idx_remote_analyzed", "remote", "analyzed"),
        Index("idx_match_score", "match_score"),
        Index("idx_created_at", "created_at"),
        Index("idx_notified", "notified"),
        Index("idx_unique_offer_identity", "company_name", "title", "city", unique=True),
        Index("idx_company_title", "company_name", "title"),  # For deduplication
        Index("idx_published_at", "published_at"),  # For sorting
        Index("idx_analyzed_score", "analyzed", "match_score"),  # For filtering high matches
    )
    
    def __repr__(self) -> str:
        return f"<JobOffer(id={self.id}, jjit_id='{self.jjit_id}', title='{self.title}', score={self.match_score})>"


class ProcessingLog(Base):
    """
    Log of processing runs for monitoring and debugging.
    """
    __tablename__ = "processing_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Processing details
    run_type: Mapped[str] = mapped_column(String(50), nullable=False)  # fetch, match, notify
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # success, error, partial
    
    # Metrics
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timing
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    __table_args__ = (
        Index("idx_run_type_status", "run_type", "status"),
        Index("idx_started_at", "started_at"),
    )
    
    def __repr__(self) -> str:
        return f"<ProcessingLog(id={self.id}, type='{self.run_type}', status='{self.status}')>"
