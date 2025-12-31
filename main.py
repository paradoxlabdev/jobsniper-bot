"""
Main application orchestrator for JobSniper.
Coordinates fetching, matching, and notification services.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import setup_logger, settings
from core.database import db_manager
from models.models import JobOffer, SystemSettings
from services.fetcher import fetcher_service, FetcherService
from services.storage import storage_service
from services.matcher import matcher_service
from services.notification import notification_service
from services.foreign_fetcher import foreign_fetcher
from health_server import health_server

logger = setup_logger(__name__, "main.log")

# Constants for cycle configuration
MAX_OFFERS_PER_ANALYSIS_CYCLE = 50  # Maximum offers to analyze per cycle
AI_ANALYSIS_RATE_LIMIT_DELAY = 1.0  # Delay in seconds between AI analyses
NOTIFICATION_DELAY_SECONDS = 1.0  # Delay in seconds after sending notification


class JobSniper:
    """
    Main application class orchestrating all services.
    
    Workflow:
    1. Fetch new offers from Just Join IT
    2. Store offers in database (upsert)
    3. Analyze unanalyzed offers with AI
    4. Send notifications for high-match offers
    """
    
    def __init__(self):
        self.fetcher: Optional[FetcherService] = None
        self.running = False
        self.force_run_event = asyncio.Event()
        self.next_run_at: Optional[datetime] = None
        self.is_running = False
        self.auto_scan_enabled = True  # Added to control automatic scanning
        self.reset_pending = False
        self.current_task: Optional[asyncio.Task] = None
        self._cycle_lock = asyncio.Lock()  # Protect critical sections from race conditions
        
        # Error recovery with exponential backoff
        self.error_count = 0
        self.max_backoff = 300  # 5 minutes max
        self._initial_backoff_delay = 60  # Start with 60 seconds
        self._current_backoff_delay = 60
        self._max_backoff_delay = 300
    
    async def initialize(self) -> None:
        """Initialize all services."""
        logger.info("Initializing JobSniper...")
        
        try:
            # Initialize database
            await db_manager.initialize()
            
            # Initialize matcher (load CV)
            await matcher_service.initialize()
            
            # Initialize fetcher
            self.fetcher = fetcher_service
            await self.fetcher.initialize()
            
            # Initialize foreign fetcher
            await foreign_fetcher.initialize()
            
            # Initialize notification service (starts Telegram bot)
            await notification_service.initialize()
            notification_service.set_trigger_event(self.force_run_event)
            notification_service.set_next_run_getter(lambda: self.next_run_at)
            notification_service.set_status_getter(lambda: self.is_running)
            notification_service.set_stop_search_handler(self.stop_current_search)
            
            # Helper to trigger reset from notification service if needed
            def trigger_reset():
                self.reset_pending = True
                if self.current_task and not self.current_task.done():
                    logger.info("🛑 Cancelling current cycle due to filter change")
                    self.current_task.cancel()
                # We don't set force_run_event here anymore to avoid auto-restart
                # self.force_run_event.set()
            notification_service.set_reset_trigger(trigger_reset)
            
            # Start polling for user input (CV uploads, commands)
            await notification_service.start_polling()
            
            # Start health check server
            health_server.set_references(self, matcher_service, db_manager)
            asyncio.create_task(health_server.start())
            
            # Test Telegram connection
            telegram_ok = await notification_service.send_test_message()
            if not telegram_ok:
                logger.warning("Telegram test failed, but continuing...")
            
            # Load initial auto-scan state from DB
            sys_settings = await storage_service.get_system_settings()
            self.auto_scan_enabled = sys_settings.auto_scan_enabled
            # Sync notification service flag
            notification_service.search_manually_stopped = not self.auto_scan_enabled
            
            logger.info(f"Loaded auto-scan state: {self.auto_scan_enabled}")
            logger.info("JobSniper initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize JobSniper: {e}", exc_info=True)
            raise
    
    async def stop_current_search(self) -> bool:
        """
        Stop the currently running search cycle.
        
        Returns:
            True if a search was stopped, False if no search was running
        """
        if self.current_task and not self.current_task.done():
            logger.info("🛑 Stopping current search cycle...")
            self.auto_scan_enabled = False # Disable auto-scan when manually stopped
            await storage_service.update_system_settings(auto_scan_enabled=False)
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
            self.is_running = False
            self.current_task = None
            logger.info("✅ Search cycle stopped successfully")
            return True
        else:
            # Even if no task running, ensure auto-scan is disabled
            self.auto_scan_enabled = False
            await storage_service.update_system_settings(auto_scan_enabled=False)
            self.is_running = False
            return True
    
    async def shutdown(self) -> None:
        """Shutdown all services gracefully."""
        logger.info("Shutting down JobSniper...")
        
        self.running = False
        
        # Stop health server
        await health_server.stop()
        
        # Stop Telegram bot first
        await notification_service.stop()
        
        if self.fetcher:
            await self.fetcher.close()
        
        await foreign_fetcher.close()
        await db_manager.close()
        
        logger.info("JobSniper shut down successfully")
    
    async def run_fetch_cycle(self) -> dict:
        """
        Run one fetch cycle: fetch offers and store them.
        
        Returns:
            Dictionary with cycle statistics
        """
        start_time = datetime.now(timezone.utc)
        stats = {
            "fetched": 0,
            "stored": 0,
            "errors": 0,
        }
        
        try:
            logger.info("Starting fetch cycle...")
            
            # Check if we should even start
            if not self.auto_scan_enabled:
                logger.info("🛑 Fetch cycle aborted: search stopped")
                return stats
            
            # Get dynamic settings from DB
            sys_settings = await storage_service.get_system_settings()
            
            # Parse lists from DB strings
            keywords = [k.strip() for k in sys_settings.search_keywords.split(",") if k.strip()]
            locations = [l.strip() for l in sys_settings.locations.split(",") if l.strip()]
            category_ids = [c.strip() for c in sys_settings.category_ids.split(",") if c.strip()]
            enabled_sources = [s.strip() for s in sys_settings.enabled_sources.split(",") if s.strip()]
            keyword_match_mode = getattr(sys_settings, 'keyword_match_mode', 'relaxed')  # Default to relaxed
            
            all_offers = []
            
            # Fetch from JJIT if enabled
            if "jjit" in enabled_sources:
                jjit_offers = await self.fetcher.fetch_offers(
                    keywords=keywords,
                    keyword_match_mode=keyword_match_mode,
                    category_ids=category_ids,
                    locations=locations,
                    remote=sys_settings.include_remote,
                )
                all_offers.extend(jjit_offers)
                logger.info(f"JJIT: fetched {len(jjit_offers)} offers")
            
            # Fetch from foreign sources if any enabled
            foreign_sources = [s for s in enabled_sources if s != "jjit"]
            if foreign_sources:
                try:
                    foreign_offers = await foreign_fetcher.fetch_all(
                        keywords=keywords,
                        enabled_sources=foreign_sources
                    )
                    
                    # Apply filtering to foreign offers
                    foreign_offers = FetcherService._filter_offers(
                        offers=foreign_offers,
                        keywords=keywords,
                        keyword_match_mode=keyword_match_mode,
                        remote=sys_settings.include_remote,
                        locations=locations,
                    )
                    
                    all_offers.extend(foreign_offers)
                    logger.info(f"Foreign boards: fetched {len(foreign_offers)} offers")
                    
                except Exception as e:
                    logger.error(f"Foreign fetcher error: {e}", exc_info=True)
                    # Log to database for tracking
                    await storage_service.log_processing_run(
                        run_type="fetch_foreign",
                        status="error",
                        items_processed=0,
                        items_failed=len(foreign_sources),
                        error_message=str(e)[:500],
                        duration_seconds=0
                    )
            
            stats["fetched"] = len(all_offers)
            
            # Store offers
            if all_offers:
                stored = await storage_service.upsert_offers_batch(all_offers)
                stats["stored"] = stored
            
            # Log processing run
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await storage_service.log_processing_run(
                run_type="fetch",
                status="success",
                items_processed=stats["fetched"],
                items_new=stats["stored"],
                duration_seconds=duration,
            )
            
            logger.info(
                f"Fetch cycle complete: {stats['fetched']} fetched, "
                f"{stats['stored']} stored"
            )
            
        except Exception as e:
            logger.error(f"Fetch cycle failed: {e}", exc_info=True)
            stats["errors"] = 1
            
            # Log error
            await storage_service.log_processing_run(
                run_type="fetch",
                status="error",
                error_message=str(e),
            )
        
        return stats
    
    async def _analyze_offers_batch(
        self, 
        offers: list[JobOffer], 
        sys_settings: SystemSettings
    ) -> list[tuple[JobOffer, float, str, bool]]:
        """
        Analyze multiple offers concurrently with controlled parallelism.
        
        Args:
            offers: List of JobOffer instances to analyze
            sys_settings: System settings for threshold
        
        Returns:
            List of tuples: (offer, score, reason, is_error)
        """
        # Semaphore already exists in matcher_service (5 concurrent max)
        # We'll process in smaller batches to avoid overwhelming the system
        
        async def analyze_one(offer: JobOffer) -> tuple[JobOffer, float, str, bool]:
            """Analyze single offer and return result."""
            try:
                # Re-validate filters before AI analysis
                matches = FetcherService._filter_offers(
                    offers=[{
                        "title": offer.title,
                        "city": offer.city,
                        "workplaceType": offer.remote,
                    }],
                    keywords=sys_settings.search_keywords.split(",") if sys_settings.search_keywords else [],
                    keyword_match_mode=sys_settings.keyword_match_mode,
                    remote=sys_settings.include_remote,
                    locations=sys_settings.locations.split(",") if sys_settings.locations else [],
                )
                
                if not matches:
                    logger.info(f"⏩ Skipping offer {offer.id} - no longer matches filters")
                    await storage_service.update_match_score(
                        offer_id=offer.id,
                        score=-1.0,
                        reason="Skipped: Does not match current Remote/Location settings."
                    )
                    return (offer, -1.0, "Filtered out", False)
                
                # Parse skills
                skills = []
                if offer.skills:
                    try:
                        s_data = json.loads(offer.skills)
                        if isinstance(s_data, list):
                            skills = [s.get("name", s) if isinstance(s, dict) else str(s) for s in s_data]
                    except:
                        pass
                
                # AI Analysis
                score, reason = await matcher_service.analyze_match(
                    job_title=offer.title,
                    job_description=offer.description or "",
                    company_name=offer.company_name,
                    skills=skills,
                )
                
                # Update score in database
                await storage_service.update_match_score(
                    offer_id=offer.id,
                    score=score,
                    reason=reason,
                )
                
                return (offer, score, reason, False)
                
            except Exception as e:
                logger.error(f"Failed to analyze offer {offer.id}: {e}")
                return (offer, 0.0, str(e), True)
        
        # Process all offers concurrently (matcher_service has semaphore to limit)
        results = await asyncio.gather(
            *[analyze_one(offer) for offer in offers],
            return_exceptions=True
        )
        
        # Filter out exceptions and return results
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Batch analysis exception: {result}")
                continue
            processed_results.append(result)
        
        return processed_results
    
    async def run_match_cycle(self) -> dict:
        """
        Run one match cycle: analyze unanalyzed offers.
        
        Returns:
            Dictionary with cycle statistics
        """
        start_time = datetime.now(timezone.utc)
        stats = {
            "analyzed": 0,
            "high_matches": 0,
            "errors": 0,
        }
        
        try:
            logger.info("Starting match cycle with concurrent batch processing...")
            
            # Get dynamic settings
            sys_settings = await storage_service.get_system_settings()
            
            # Get unanalyzed offers
            unanalyzed_offers = await storage_service.get_unanalyzed_offers(limit=MAX_OFFERS_PER_ANALYSIS_CYCLE)
            
            if not unanalyzed_offers:
                logger.info("No unanalyzed offers found")
                return stats
            
            logger.info(f"Found {len(unanalyzed_offers)} unanalyzed offers")
            
            # Process offers in batches for better performance
            BATCH_SIZE = 10  # Process 10 at a time
            
            for i in range(0, len(unanalyzed_offers), BATCH_SIZE):
                batch = unanalyzed_offers[i:i+BATCH_SIZE]
                logger.info(f"Processing batch {i//BATCH_SIZE + 1}/{(len(unanalyzed_offers)-1)//BATCH_SIZE + 1} ({len(batch)} offers)")
                
                # Check if search was stopped while preparing batch
                if not self.auto_scan_enabled or (self.current_task and self.current_task.cancelling()):
                    logger.info("🛑 Match cycle aborted: auto-scan disabled or task cancelled")
                    return stats
                
                # Analyze batch concurrently
                batch_results = await self._analyze_offers_batch(batch, sys_settings)
                
                # Process results and send notifications
                for offer, score, reason, is_error in batch_results:
                    # Check cancellation again before sending each notification
                    if not self.auto_scan_enabled:
                        logger.info("🛑 Notification sending aborted: search stopped")
                        return stats
                    
                    if is_error:
                        stats["errors"] += 1
                        continue
                    
                    stats["analyzed"] += 1
                    
                    # Skip filtered out offers (score = -1)
                    if score < 0:
                        continue
                    
                    # Check if high match
                    if score >= sys_settings.match_threshold:
                        stats["high_matches"] += 1
                        
                        # Extract source from jjit_id
                        source = "JJIT"
                        if offer.jjit_id.startswith("remoteok_"):
                            source = "RemoteOK"
                        elif offer.jjit_id.startswith("remotive_"):
                            source = "Remotive"
                        elif offer.jjit_id.startswith("wwr_"):
                            source = "WWR"
                        elif offer.jjit_id.startswith("arbeitnow_"):
                            source = "Arbeitnow"
                        
                        # 🚀 REAL-TIME NOTIFICATION 🚀
                        try:
                            # Parse skills for notification
                            notify_skills = []
                            if offer.skills:
                                try:
                                    s_data = json.loads(offer.skills)
                                    if isinstance(s_data, list):
                                        notify_skills = [s.get("name", s) if isinstance(s, dict) else str(s) for s in s_data]
                                except:
                                    pass
                            
                            # Atomically check and reserve this offer for notification
                            can_send = await storage_service.mark_as_notified_if_not_sent(offer.id)
                            
                            if not can_send:
                                logger.info(f"⏩ Skipping notification for {offer.id} - already sent or duplicate")
                                continue

                            # Send notification
                            if not self.auto_scan_enabled:
                                logger.info("🛑 Aborting notification - search stopped")
                                return stats

                            success = await notification_service.send_job_alert(
                                job_title=offer.title,
                                company_name=offer.company_name,
                                match_score=score,
                                match_reason=reason or "No reason provided",
                                offer_url=offer.offer_url,
                                source=source,
                                salary_from=offer.salary_from,
                                salary_to=offer.salary_to,
                                salary_currency=offer.salary_currency,
                                remote=offer.remote,
                                city=offer.city,
                                skills=notify_skills[:10],
                            )
                            
                            if success:
                                await asyncio.sleep(NOTIFICATION_DELAY_SECONDS)
                            else:
                                logger.warning(f"Failed to send notification for {offer.id} (success={success})")
                                
                        except Exception as e:
                            logger.error(f"Failed to process notification for {offer.id}: {e}")
                
                # Small delay between batches to avoid overwhelming services
                if i + BATCH_SIZE < len(unanalyzed_offers):
                    await asyncio.sleep(1)
            
            # Log processing run
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await storage_service.log_processing_run(
                run_type="match",
                status="success" if stats["errors"] == 0 else "partial",
                items_processed=stats["analyzed"],
                items_failed=stats["errors"],
                duration_seconds=duration,
            )
            
            logger.info(
                f"Match cycle complete: {stats['analyzed']} analyzed, "
                f"{stats['high_matches']} high matches"
            )
            
        except asyncio.TimeoutError:
            logger.warning(
                f"Match cycle timed out after 180s. "
                f"Processed {stats['analyzed']} offers. "
                f"Remaining offers will be analyzed in next cycle."
            )
            # Log partial completion
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await storage_service.log_processing_run(
                run_type="match",
                status="partial",
                items_processed=stats["analyzed"],
                items_failed=stats["errors"],
                duration_seconds=duration,
                error_message="Timeout after 180s"
            )
            
        except Exception as e:
            logger.error(f"Match cycle failed: {e}", exc_info=True)
            stats["errors"] += 1
            
            await storage_service.log_processing_run(
                run_type="match",
                status="error",
                error_message=str(e),
            )
        
        return stats
    
    # run_notify_cycle removed - notifications are sent in real-time during run_match_cycle
    
    async def run_full_cycle(self) -> None:
        """Run a complete cycle: fetch -> match (with real-time notifications)."""
        logger.info("=" * 60)
        logger.info("Starting full processing cycle")
        logger.info("=" * 60)
        
        # 1. Fetch
        fetch_stats = await self.run_fetch_cycle()
        
        # Check if we should continue to match
        if not self.auto_scan_enabled:
            logger.info("🛑 Skipping match cycle: search was stopped during fetch")
            return
            
        # 2. Match (notifications sent in real-time here)
        match_stats = await self.run_match_cycle()
        
        # Summary
        logger.info("=" * 60)
        logger.info("Cycle Summary:")
        logger.info(f"  Fetched: {fetch_stats['fetched']} offers")
        logger.info(f"  Stored: {fetch_stats['stored']} new offers")
        logger.info(f"  Analyzed: {match_stats['analyzed']} offers")
        logger.info(f"  High matches (notified): {match_stats['high_matches']}")
        logger.info("=" * 60)
        
        # Send summary to Telegram
        try:
            stats = await storage_service.get_statistics()
            await notification_service.send_scan_summary(
                total_offers=stats['total_offers'],
                high_matches=match_stats['high_matches'],
                last_scan_time=stats['last_scan']
            )
        except Exception as e:
            logger.error(f"Failed to send scan summary: {e}")
    
    async def run_continuous(self) -> None:
        """Run continuous monitoring loop."""
        self.running = True
        
        logger.info(f"Starting continuous monitoring (interval: {settings.jjit_fetch_interval}s)")
        
        while self.running:
            try:
                # Check for reset - protected by lock
                if self.reset_pending:
                    logger.info("🧹 Filter change detected - resetting analysis for full re-scan")
                    async with self._cycle_lock:
                        await storage_service.reset_analysis_status()
                    self.reset_pending = False
                    # IMPORTANT: Don't auto-resume if search was manually stopped
                    if self.auto_scan_enabled:
                        logger.info("Resuming auto-scan after filter change")
                    else:
                        logger.info("Filters reset, but auto-scan remains DISABLED (manual stop active)")
                    
                try:
                    # Check if auto-scan is enabled before starting
                    # Check if auto-scan is enabled before starting
                    if self.auto_scan_enabled or self.force_run_event.is_set():
                        # Clear event immediately if set, to capture new events during cycle
                        if self.force_run_event.is_set():
                             self.force_run_event.clear()
                        
                        # Set state BEFORE starting cycle
                        self.is_running = True
                        self.current_task = asyncio.create_task(self.run_full_cycle())
                        
                        try:
                            # Run cycle with global timeout
                            async with asyncio.timeout(300):  # 5 minutes max per cycle
                                await self.current_task
                            
                            # Reset error count on successful cycle
                            self.error_count = 0
                        except asyncio.TimeoutError:
                             logger.error("❌ Cycle timed out globally (300s)!")
                             if not self.current_task.done():
                                 self.current_task.cancel()
                        except asyncio.CancelledError:
                            logger.info("⚡ Cycle cancelled or interrupted.")
                            # Don't re-raise - we want to stay in the loop to wait for triggers
                        finally:
                            # Clean up state
                            self.is_running = False
                            self.current_task = None
                    else:
                        # Auto-scan is disabled, just wait for triggers
                        self.next_run_at = None
                        logger.debug("Auto-scan is disabled. Waiting for manual trigger...")
                except Exception as cycle_error:
                    logger.error(f"Error during cycle initialization: {cycle_error}")
                
                # Wait for next cycle or forced run
                if self.auto_scan_enabled:
                    interval = settings.jjit_fetch_interval
                    self.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=interval)
                    logger.info(f"Waiting {interval} seconds until next cycle (or until triggered)...")
                    
                    try:
                        # Create task for sleep (interval)
                        sleep_task = asyncio.create_task(asyncio.sleep(interval))
                        # Create task for event wait
                        event_task = asyncio.create_task(self.force_run_event.wait())
                        
                        # Wait for whichever comes first
                        done, pending = await asyncio.wait(
                            [sleep_task, event_task],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        
                        # Cancel pending task
                        for task in pending:
                            task.cancel()
                            
                    except Exception as e:
                        logger.error(f"Error in wait loop: {e}")
                        await asyncio.sleep(60)
                else:
                    # Auto-scan disabled - wait indefinitely for manual trigger
                    self.next_run_at = None
                    logger.info("Auto-scan is disabled. Waiting for manual trigger 'Search Now'...")
                    await self.force_run_event.wait()

                # Check if event was triggered
                if self.force_run_event.is_set():
                    logger.info("⚡ Cycle triggered by user event!")
                    self.auto_scan_enabled = True  # Re-enable auto-scan on manual trigger
                    await storage_service.update_system_settings(auto_scan_enabled=True)
                    self.force_run_event.clear()
                
            except Exception as e:
                logger.error(f"Error in continuous loop: {e}", exc_info=True)
                
                # Exponential backoff on errors with jitter
                self.error_count += 1
                backoff_delay = min(60 * (2 ** (self.error_count - 1)), self.max_backoff)
                
                # Add jitter (±20%) to avoid thundering herd
                import random
                jitter = backoff_delay * 0.2 * (2 * random.random() - 1)
                backoff_delay = max(1, backoff_delay + jitter)  # Ensure positive
                
                logger.warning(
                    f"Error #{self.error_count} in main loop. "
                    f"Retrying in {backoff_delay:.1f}s (exponential backoff + jitter)"
                )
                
                # Send error alert
                try:
                    await notification_service.send_error_alert(
                        f"JobSniper error (attempt {self.error_count}): {str(e)[:200]}\n"
                        f"Retrying in {backoff_delay}s..."
                    )
                except:
                    pass
                
                # Wait before retry with exponential backoff
                await asyncio.sleep(backoff_delay)


async def main():
    """Main entry point."""
    sniper = JobSniper()
    
    # Handle signals for graceful shutdown
    import signal
    loop = asyncio.get_running_loop()
    
    def handle_exception(loop, context):
        msg = context.get("message")
        logger.error(f"Uncaught exception: {msg}")

    loop.set_exception_handler(handle_exception)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(sniper.shutdown()))
    
    try:
        # Initialize
        await sniper.initialize()
        
        # Run continuous monitoring
        await sniper.run_continuous()
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await sniper.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
