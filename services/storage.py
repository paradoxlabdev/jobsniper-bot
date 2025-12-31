"""
Storage Service - Database operations for job offers.
Handles CRUD operations with upsert logic to avoid duplicates.
"""
from typing import Optional, Sequence, TypedDict
from datetime import datetime, timezone
import json
import hashlib

from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from core import setup_logger
from core.database import db_manager
from core.config import settings
from models import JobOffer, ProcessingLog, SystemSettings

logger = setup_logger(__name__, "storage.log")


class Statistics(TypedDict):
    """Type definition for statistics dictionary."""
    total_offers: int
    analyzed_offers: int
    sent_notifications: int
    last_scan: Optional[datetime]
    score_distribution: dict[str, int]
    average_score: float
    top_offers: list[dict]


class StorageService:
    """
    Service for storing and retrieving job offers from PostgreSQL.
    
    Features:
    - Upsert operations (insert or update)
    - Duplicate detection by jjit_id
    - Batch operations
    - Query helpers
    """
    
    async def upsert_offer(self, offer_data: dict) -> JobOffer:
        """
        Insert or update a job offer.
        Uses PostgreSQL's ON CONFLICT to handle duplicates.
        
        Args:
            offer_data: Dictionary with offer data from JJIT API
        
        Returns:
            JobOffer instance (newly created or updated)
        """
        try:
            async with db_manager.get_session() as session:
                # Prepare data for insert
                insert_data = self._prepare_offer_data(offer_data)
                
                # Try upsert by jjit_id first (most common case)
                try:
                    stmt = insert(JobOffer).values(**insert_data)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["jjit_id"],
                        set_={
                            "title": stmt.excluded.title,
                            "description": stmt.excluded.description,
                            "salary_from": stmt.excluded.salary_from,
                            "salary_to": stmt.excluded.salary_to,
                            "skills": stmt.excluded.skills,
                            "workplace_type": stmt.excluded.workplace_type,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    ).returning(JobOffer)
                    
                    result = await session.execute(stmt)
                    offer = result.scalar_one()
                    logger.debug(f"Upserted offer by jjit_id: {offer.jjit_id} - {offer.title}")
                    return offer
                    
                except IntegrityError:
                    # If jjit_id conflict fails, try unique identity conflict
                    # This handles cases where same offer appears from different sources with different jjit_id
                    stmt = insert(JobOffer).values(**insert_data)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["company_name", "title", "city"],  # Handle conflicts on unique identity
                        set_={
                            "jjit_id": stmt.excluded.jjit_id,  # Update jjit_id if different source
                            "slug": stmt.excluded.slug,
                            "description": stmt.excluded.description,
                            "salary_from": stmt.excluded.salary_from,
                            "salary_to": stmt.excluded.salary_to,
                            "skills": stmt.excluded.skills,
                            "workplace_type": stmt.excluded.workplace_type,
                            "offer_url": stmt.excluded.offer_url,  # Update URL if from different source
                            "apply_url": stmt.excluded.apply_url,
                            "published_at": stmt.excluded.published_at,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    ).returning(JobOffer)
                    
                    result = await session.execute(stmt)
                    offer = result.scalar_one()
                    logger.debug(f"Upserted offer by unique identity: {offer.jjit_id} - {offer.title}")
                    return offer
                
        except Exception as e:
            logger.error(f"Failed to upsert offer: {e}", exc_info=True)
            raise
    
    async def upsert_offers_batch(self, offers_data: list[dict]) -> int:
        """
        Batch upsert multiple offers with error isolation.
        Attempts batch insert first, falls back to individual inserts on failure.
        
        Args:
            offers_data: List of offer dictionaries
        
        Returns:
            Number of offers successfully processed
        """
        if not offers_data:
            return 0
        
        # Try batch first for performance
        try:
            async with db_manager.get_session() as session:
                # Deduplicate offers by jjit_id within the batch
                unique_offers = {}
                for offer in offers_data:
                    prepared = self._prepare_offer_data(offer)
                    unique_offers[prepared['jjit_id']] = prepared
                
                prepared_data = list(unique_offers.values())
                
                if not prepared_data:
                    return 0

                # Single batch upsert statement - handle conflicts on unique identity (company_name, title, city)
                # This handles cases where same offer appears from different sources with different jjit_id
                stmt = insert(JobOffer).values(prepared_data)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["company_name", "title", "city"],  # Handle conflicts on unique identity
                    set_={
                        "jjit_id": stmt.excluded.jjit_id,  # Update jjit_id if different source
                        "slug": stmt.excluded.slug,
                        "description": stmt.excluded.description,
                        "salary_from": stmt.excluded.salary_from,
                        "salary_to": stmt.excluded.salary_to,
                        "skills": stmt.excluded.skills,
                        "workplace_type": stmt.excluded.workplace_type,
                        "offer_url": stmt.excluded.offer_url,  # Update URL if from different source
                        "apply_url": stmt.excluded.apply_url,
                        "published_at": stmt.excluded.published_at,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                
                await session.execute(stmt)
                
                logger.info(f"✅ Batch upsert completed: {len(prepared_data)} offers")
                return len(prepared_data)
                
        except Exception as batch_error:
            logger.warning(
                f"⚠️ Batch upsert failed: {batch_error}. "
                f"Falling back to individual inserts for error isolation..."
            )
            
            # Fallback: Insert individually to isolate bad records
            # This is slower but ensures valid offers are saved even if one fails
            logger.info("⚠️ Performance Warning: Switching to slow individual inserts due to batch failure")
            success_count = 0
            failed_offers = []
            
            for offer_data in offers_data:
                try:
                    await self.upsert_offer(offer_data)
                    success_count += 1
                except Exception as e:
                    offer_id = offer_data.get('id', 'unknown')
                    failed_offers.append(offer_id)
                    logger.error(f"❌ Failed to upsert offer {offer_id}: {e}")
            
            if failed_offers:
                logger.warning(
                    f"Individual upsert: {success_count}/{len(offers_data)} successful. "
                    f"Failed IDs: {failed_offers[:10]}{'...' if len(failed_offers) > 10 else ''}"
                )
            else:
                logger.info(f"✅ Individual upsert: {success_count}/{len(offers_data)} successful")
            
            return success_count
    
    async def get_unanalyzed_offers(self, limit: int = 100) -> Sequence[JobOffer]:
        """
        Get offers that haven't been analyzed by AI yet.
        
        Args:
            limit: Maximum number of offers to return
        
        Returns:
            List of JobOffer instances
        """
        async with db_manager.get_session() as session:
            stmt = (
                select(JobOffer)
                .where(JobOffer.analyzed == False)
                .order_by(JobOffer.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            offers = result.scalars().all()
            
            logger.info(f"Retrieved {len(offers)} unanalyzed offers")
            return offers
    
    async def update_match_score(
        self,
        offer_id: int,
        score: float,
        reason: str,
    ) -> None:
        """
        Update offer with AI match score and reason.
        
        Args:
            offer_id: JobOffer ID
            score: Match score (0-100)
            reason: Explanation of the match
        """
        async with db_manager.get_session() as session:
            stmt = (
                update(JobOffer)
                .where(JobOffer.id == offer_id)
                .values(
                    match_score=score,
                    match_reason=reason,
                    analyzed=True,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(stmt)
            
            logger.debug(f"Updated match score for offer {offer_id}: {score}")
    
    async def check_notification_sent(self, offer: JobOffer) -> bool:
        """
        Check if notification was already sent for similar offer.
        
        Args:
            offer: JobOffer instance
        
        Returns:
            True if notification was already sent, False otherwise
        """
        # Generate hash from key fields
        hash_content = f"{offer.title}|{offer.company_name}|{offer.salary_from}|{offer.salary_to}"
        notification_hash = hashlib.sha256(hash_content.encode()).hexdigest()
        
        async with db_manager.get_session() as session:
            # Check if this hash exists in any notified offer
            stmt = (
                select(JobOffer)
                .where(JobOffer.notification_hash == notification_hash)
                .where(JobOffer.notified == True)
                .limit(1)
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.debug(
                    f"Notification already sent for similar offer: "
                    f"{offer.title} at {offer.company_name} (hash: {notification_hash[:8]}...)"
                )
                return True
            
            return False
    
    async def get_high_match_offers(
        self,
        threshold: float,
        unnotified_only: bool = True,
    ) -> Sequence[JobOffer]:
        """
        Get offers with match score above threshold.
        
        Args:
            threshold: Minimum match score (0-100)
            unnotified_only: Only return offers not yet notified
        
        Returns:
            List of high-match JobOffer instances
        """
        # Validate threshold to prevent SQL issues or logic errors
        safe_threshold = max(0, min(100, float(threshold)))
        
        async with db_manager.get_session() as session:
            stmt = (
                select(JobOffer)
                .where(JobOffer.match_score >= safe_threshold)
            )
            
            if unnotified_only:
                stmt = stmt.where(JobOffer.notified == False)
            
            stmt = stmt.order_by(JobOffer.match_score.desc())
            
            result = await session.execute(stmt)
            offers = result.scalars().all()
            
            logger.info(f"Retrieved {len(offers)} high-match offers (>= {threshold})")
            return offers
    
    async def mark_as_notified(self, offer_id: int) -> None:
        """
        Mark offer as notified with notification hash to prevent duplicates.
        
        Args:
            offer_id: JobOffer ID
        """
        async with db_manager.get_session() as session:
            # First, get the offer to generate hash
            offer_stmt = select(JobOffer).where(JobOffer.id == offer_id)
            result = await session.execute(offer_stmt)
            offer = result.scalar_one_or_none()
            
            if not offer:
                logger.warning(f"Offer {offer_id} not found for marking as notified")
                return
            
            # Generate notification hash from key fields
            hash_content = f"{offer.title}|{offer.company_name}|{offer.salary_from}|{offer.salary_to}"
            notification_hash = hashlib.sha256(hash_content.encode()).hexdigest()
            
            # Update offer
            stmt = (
                update(JobOffer)
                .where(JobOffer.id == offer_id)
                .values(
                    notified=True,
                    notified_at=datetime.now(timezone.utc),
                    notification_hash=notification_hash
                )
            )
            await session.execute(stmt)
            
            logger.debug(f"Marked offer {offer_id} as notified with hash {notification_hash[:8]}...")
    
    async def mark_as_notified_if_not_sent(self, offer_id: int) -> bool:
        """
        Atomically check and mark as notified in a single transaction.
        Prevents duplicate notifications via database-level row locking.
        
        Args:
            offer_id: JobOffer ID
        
        Returns:
            True if marked successfully (wasn't sent before), False if already sent
        """
        async with db_manager.get_session() as session:
            # Use SELECT FOR UPDATE to lock the row atomically
            stmt = (
                select(JobOffer)
                .where(JobOffer.id == offer_id)
                .with_for_update()  # Lock row for update - prevents race conditions
            )
            result = await session.execute(stmt)
            offer = result.scalar_one_or_none()
            
            if not offer:
                logger.warning(f"Offer {offer_id} not found")
                return False
            
            # Check if already notified
            if offer.notified:
                logger.debug(f"Offer {offer_id} already notified, skipping")
                return False
            
            # Generate notification hash from key fields
            hash_content = f"{offer.title}|{offer.company_name}|{offer.salary_from}|{offer.salary_to}"
            notification_hash = hashlib.sha256(hash_content.encode()).hexdigest()
            
            # Check if similar notification was sent (by hash)
            hash_check_stmt = (
                select(JobOffer.id)
                .where(JobOffer.notification_hash == notification_hash)
                .where(JobOffer.notified == True)
                .limit(1)
            )
            hash_result = await session.execute(hash_check_stmt)
            if hash_result.scalar_one_or_none():
                logger.debug(f"Similar notification already sent (hash: {notification_hash[:8]}...)")
                # Mark this offer as notified too to avoid re-checking
                offer.notified = True
                offer.notified_at = datetime.now(timezone.utc)
                # Ensure hash is None for duplicates to satisfy UNIQUE constraint
                offer.notification_hash = None
                await session.commit()
                return False
            
            # Mark as notified atomically
            try:
                offer.notified = True
                offer.notified_at = datetime.now(timezone.utc)
                offer.notification_hash = notification_hash
                await session.commit()
                
                logger.debug(f"✅ Atomically marked offer {offer_id} as notified")
                return True
            except IntegrityError:
                # Duplicate notification hash (already sent by another worker)
                logger.info(f"Duplicate notification hash detected for offer {offer_id} during commit")
                offer.notification_hash = None
                return False

    
    async def log_processing_run(
        self,
        run_type: str,
        status: str,
        items_processed: int = 0,
        items_new: int = 0,
        items_failed: int = 0,
        error_message: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> ProcessingLog:
        """
        Log a processing run for monitoring.
        
        Args:
            run_type: Type of run (fetch, match, notify)
            status: Status (success, error, partial)
            items_processed: Number of items processed
            items_new: Number of new items
            items_failed: Number of failed items
            error_message: Optional error message
            duration_seconds: Duration in seconds
        
        Returns:
            ProcessingLog instance
        """
        async with db_manager.get_session() as session:
            log_entry = ProcessingLog(
                run_type=run_type,
                status=status,
                items_processed=items_processed,
                items_new=items_new,
                items_failed=items_failed,
                error_message=error_message,
                duration_seconds=duration_seconds,
                completed_at=datetime.now(timezone.utc),
            )
            session.add(log_entry)
            await session.flush()
            
            logger.info(
                f"Logged {run_type} run: {status} "
                f"({items_processed} processed, {items_new} new, {items_failed} failed)"
            )
            
            return log_entry
            
    async def reset_analysis_status(self) -> int:
        """
        Reset analysis status for ALL offers.
        Used to force re-analysis with new settings/CV.
        
        Returns:
            Number of reset offers
        """
        async with db_manager.get_session() as session:
            stmt = (
                update(JobOffer)
                .values(
                    analyzed=False,
                    match_score=None,
                    match_reason=None,
                    notified=False,
                    notified_at=None,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            result = await session.execute(stmt)
            count = result.rowcount
            
            logger.info(f"Reset analysis status for {count} offers")
            return count
    
    async def get_statistics(self) -> Statistics:
        """
        Get global statistics for the /stats command.
        
        Returns:
            Statistics dictionary with offer counts, distribution, average score, and top offers
        """
        async with db_manager.get_session() as session:
            # Count total offers
            total_offers = await session.scalar(select(func.count(JobOffer.id)))
            
            # Count analyzed offers
            analyzed_offers = await session.scalar(select(func.count(JobOffer.id)).where(JobOffer.analyzed == True))
            
            # Count high matches (sent)
            sent_notifications = await session.scalar(select(func.count(JobOffer.id)).where(JobOffer.notified == True))
            
            # Average score (exclude filtered-out offers with score < 0)
            average_score = await session.scalar(
                select(func.avg(JobOffer.match_score))
                .where(JobOffer.analyzed == True)
                .where(JobOffer.match_score >= 0)
            ) or 0.0
            
            # Score distribution
            score_distribution = {}
            if analyzed_offers > 0:
                # Calculate buckets: 0-10, 10-20, ..., 90-100
                # Exclude offers with score < 0 (filtered out by re-validation)
                bucket_expr = (func.ceil(func.greatest(JobOffer.match_score, 0.1) / 10) * 10).label('bucket')
                stmt = (
                    select(bucket_expr, func.count(JobOffer.id))
                    .where(JobOffer.analyzed == True)
                    .where(JobOffer.match_score >= 0)  # Exclude filtered-out offers
                    .group_by('bucket')
                    .order_by('bucket')
                )
                result = await session.execute(stmt)
                
                # Initialize all buckets with 0 (0-10, 11-20, ..., 91-100)
                for i in range(10):
                    start = i*10 + (1 if i > 0 else 0)
                    end = (i+1)*10
                    score_distribution[f"{start}-{end}"] = 0
                
                # Fill with actual data
                for row in result.all():
                    bucket_val = int(row[0])
                    # bucket_val is 10, 20, ..., 100
                    start = bucket_val - 9 if bucket_val > 10 else 0
                    end = bucket_val
                    label = f"{start}-{end}"
                    score_distribution[label] = int(row[1])
            
            # Top 10 offers by match score
            top_offers = []
            if analyzed_offers > 0:
                stmt = (
                    select(JobOffer.id, JobOffer.title, JobOffer.company_name, JobOffer.match_score, JobOffer.offer_url)
                    .where(JobOffer.analyzed == True)
                    .where(JobOffer.match_score >= 0)
                    .order_by(JobOffer.match_score.desc())
                    .limit(10)
                )
                result = await session.execute(stmt)
                for row in result.all():
                    top_offers.append({
                        'id': row[0],
                        'title': row[1],
                        'company_name': row[2],
                        'match_score': float(row[3]),
                        'offer_url': row[4]
                    })

            # Get last scan time from ProcessingLog
            last_run = await session.execute(
                select(ProcessingLog.completed_at)
                .where(ProcessingLog.run_type == "fetch")
                .order_by(ProcessingLog.completed_at.desc())
                .limit(1)
            )
            last_scan = last_run.scalar_one_or_none()
            
            return {
                "total_offers": total_offers or 0,
                "analyzed_offers": analyzed_offers or 0,
                "sent_notifications": sent_notifications or 0,
                "average_score": float(average_score),
                "last_scan": last_scan,
                "score_distribution": score_distribution,
                "top_offers": top_offers
            }

    async def get_system_settings(self) -> SystemSettings:
        """
        Get current system settings from DB.
        If not exists, create from .env defaults.
        """
        async with db_manager.get_session() as session:
            # Try to get settings (assuming single row with ID=1)
            stmt = select(SystemSettings).order_by(SystemSettings.id).limit(1)
            result = await session.execute(stmt)
            system_settings = result.scalar_one_or_none()
            
            if not system_settings:
                # Initialize with current .env values
                logger.info("Initializing SystemSettings in database from .env")
                # Ensure we pass strings, not lists (Pydantic might have parsed them)
                keywords = settings.jjit_search_keywords
                if isinstance(keywords, list):
                    keywords = ",".join(keywords)
                    
                categories = settings.jjit_category_ids
                if isinstance(categories, list):
                    categories = ",".join(categories)
                
                locations = settings.jjit_locations
                if isinstance(locations, list):
                    locations = ",".join(locations)

                system_settings = SystemSettings(
                    locations=locations,
                    include_remote=True,
                    search_keywords=keywords,
                    category_ids=categories,
                    match_threshold=settings.match_threshold,
                    enabled_sources="jjit,remoteok,remotive,arbeitnow,weworkremotely"
                )
                session.add(system_settings)
                await session.commit()
                # Re-fetch to be safe
                return system_settings
            
            return system_settings

    async def update_system_settings(self, **kwargs) -> SystemSettings:
        """
        Update system settings.
        
        Args:
            **kwargs: Fields to update (locations, include_remote, search_keywords, match_threshold)
        """
        async with db_manager.get_session() as session:
            stmt = select(SystemSettings).order_by(SystemSettings.id).limit(1)
            result = await session.execute(stmt)
            system_settings = result.scalar_one()
            
            # Update fields
            if "locations" in kwargs:
                val = kwargs["locations"]
                system_settings.locations = ",".join(val) if isinstance(val, list) else val
            if "include_remote" in kwargs:
                system_settings.include_remote = kwargs["include_remote"]
            if "search_keywords" in kwargs:
                val = kwargs["search_keywords"]
                system_settings.search_keywords = ",".join(val) if isinstance(val, list) else val
            if "category_ids" in kwargs:
                val = kwargs["category_ids"]
                system_settings.category_ids = ",".join(val) if isinstance(val, list) else val
            if "match_threshold" in kwargs:
                val = float(kwargs["match_threshold"])
                if not (0 <= val <= 100):
                    logger.warning(f"Invalid match_threshold {val}, clamping to 0-100")
                    val = max(0, min(100, val))
                system_settings.match_threshold = val
            if "auto_scan_enabled" in kwargs:
                system_settings.auto_scan_enabled = kwargs["auto_scan_enabled"]
            if "enabled_sources" in kwargs:
                val = kwargs["enabled_sources"]
                system_settings.enabled_sources = ",".join(val) if isinstance(val, list) else val
            
            system_settings.updated_at = datetime.now(timezone.utc)
            await session.commit()
            
            logger.info(f"Updated SystemSettings: {kwargs}")
            return system_settings

    def _prepare_offer_data(self, raw_data: dict) -> dict:
        """
        Transform raw API data into database model format.
        
        Args:
            raw_data: Raw offer data from JJIT API
        
        Returns:
            Dictionary ready for JobOffer model
        """
        # Extract salary info (JJIT API structure may vary)
        salary_from = None
        salary_to = None
        salary_currency = None
        
        if "employmentTypes" in raw_data and raw_data["employmentTypes"]:
            employment = raw_data["employmentTypes"][0]
            if "salary" in employment and employment["salary"]:
                salary_from = employment["salary"].get("from")
                salary_to = employment["salary"].get("to")
                salary_currency = employment["salary"].get("currency")
            # Map employment type from v2 format
            if "type" in employment:
                employment_type = employment["type"]
            else:
                employment_type = None
        else:
            employment_type = raw_data.get("employment_type")
            salary_from = raw_data.get("salary_from")
            salary_to = raw_data.get("salary_to")
            salary_currency = raw_data.get("salary_currency")

        
        # Build offer URL - preserve if already provided (foreign sources), otherwise construct JJIT URL
        if "offer_url" in raw_data and raw_data["offer_url"]:
            offer_url = raw_data["offer_url"]
        else:
            offer_url = f"https://justjoin.it/job-offer/{raw_data.get('slug', raw_data.get('id', ''))}"
        
        # Helper to safely get value from either snake_case (legacy) or camelCase (v2)
        def get_val(key_snake, key_camel, default=None):
            return raw_data.get(key_camel, raw_data.get(key_snake, default))

        def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
            """Parse ISO date string to timezone-aware UTC datetime."""
            if not date_str:
                return None
            try:
                # Handle 'Z' suffix for UTC
                if date_str.endswith('Z'):
                    date_str = date_str[:-1] + '+00:00'
                
                dt = datetime.fromisoformat(date_str)
                
                # Convert to UTC if aware
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc)
                else:
                    # If naive, assume UTC
                    dt = dt.replace(tzinfo=timezone.utc)
                    
                return dt
            except ValueError:
                logger.warning(f"Failed to parse date: {date_str}")
                return None

        return {
            "jjit_id": raw_data.get("jjit_id", raw_data.get("slug", raw_data.get("id", ""))),
            "slug": raw_data.get("slug", ""),
            "title": raw_data.get("title", "Unknown"),
            "company_name": get_val("company_name", "companyName", "Unknown"),
            "company_logo_url": get_val("company_logo_url", "companyLogoUrl"),
            "city": raw_data.get("city"),
            "country_code": get_val("country_code", "countryCode"),
            "workplace_type": get_val("workplace_type", "workplaceType"),
            "remote": raw_data.get("remote", raw_data.get("workplaceType") in ["remote", "partly_remote"]),
            "salary_from": salary_from,
            "salary_to": salary_to,
            "salary_currency": salary_currency,
            "experience_level": get_val("experience_level", "experienceLevel"),
            "employment_type": employment_type,
            "description": raw_data.get("body", raw_data.get("description", "")), # v2 might not have full body in list
            "skills": json.dumps(get_val("skills", "requiredSkills", [])),
            "offer_url": offer_url,
            "apply_url": get_val("apply_url", "applyUrl"),
            "published_at": _parse_date(get_val("published_at", "publishedAt")),
        }


# Global storage service instance
storage_service = StorageService()
