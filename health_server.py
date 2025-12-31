"""
Health Check HTTP Server for JobSniper.
Provides monitoring endpoint for Docker health checks and external monitoring.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from sqlalchemy import text

from core import setup_logger
from core.circuit_breaker import openai_circuit_breaker

logger = setup_logger(__name__, "main.log")


class HealthServer:
    """Simple HTTP server for health checks."""
    
    def __init__(self):
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.start_time = datetime.now(timezone.utc)
        
        # References to main application state
        self.sniper = None
        self.matcher_service = None
        self.db_manager = None
        self.storage_service = None
    
    def set_references(self, sniper, matcher_service, db_manager=None, storage_service=None):
        """Set references to main application objects."""
        self.sniper = sniper
        self.matcher_service = matcher_service
        self.db_manager = db_manager
        self.storage_service = storage_service
    
    async def _check_database(self) -> dict:
        """Check database connection with timeout."""
        if not self.db_manager or not self.db_manager.engine:
            return {
                "status": "error",
                "response_time_ms": 0,
                "error": "Database manager not initialized"
            }
        
        try:
            start_time = time.time()
            async with asyncio.timeout(2.0):  # 2 second timeout
                async with self.db_manager.engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
            
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "ok",
                "response_time_ms": response_time,
                "error": None
            }
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "response_time_ms": 2000,
                "error": "Database connection timeout (2s)"
            }
        except Exception as e:
            return {
                "status": "error",
                "response_time_ms": 0,
                "error": str(e)[:200]  # Limit error message length
            }
    
    async def _check_redis(self) -> dict:
        """Check Redis connection with timeout."""
        if not self.matcher_service:
            return {
                "status": "error",
                "response_time_ms": 0,
                "error": "Matcher service not initialized"
            }
        
        if not self.matcher_service._redis_enabled:
            return {
                "status": "disabled",
                "response_time_ms": 0,
                "error": None
            }
        
        if not self.matcher_service._redis:
            return {
                "status": "error",
                "response_time_ms": 0,
                "error": "Redis connection not established"
            }
        
        try:
            start_time = time.time()
            async with asyncio.timeout(2.0):  # 2 second timeout
                await self.matcher_service._redis.ping()
            
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "ok",
                "response_time_ms": response_time,
                "error": None
            }
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "response_time_ms": 2000,
                "error": "Redis connection timeout (2s)"
            }
        except Exception as e:
            return {
                "status": "error",
                "response_time_ms": 0,
                "error": str(e)[:200]  # Limit error message length
            }
    
    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint with deep component checks."""
        try:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
            
            # Check all components
            db_status = await self._check_database()
            redis_status = await self._check_redis()
            
            # Determine overall status
            if db_status["status"] == "error":
                overall_status = "unhealthy"
            elif redis_status["status"] == "error" or (
                self.matcher_service and not self.matcher_service.cv_text
            ):
                overall_status = "degraded"
            else:
                overall_status = "healthy"
            
            response_data = {
                "status": overall_status,
                "uptime_seconds": int(uptime),
                "uptime_formatted": self._format_uptime(uptime),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "components": {
                    "database": db_status,
                    "redis": redis_status
                }
            }
            
            # Add CV status if available
            if self.matcher_service:
                response_data["components"]["cv"] = {
                    "status": "loaded" if self.matcher_service.cv_text else "missing",
                    "text_length": len(self.matcher_service.cv_text) if self.matcher_service.cv_text else 0
                }
            
            # Add application state if available
            if self.sniper:
                # is_running means "search cycle in progress", but app is running if self.running is True
                # For health check, we want to know if the app is operational, not just if it's scanning
                app_is_operational = self.sniper.running if hasattr(self.sniper, 'running') else True
                response_data["components"]["application"] = {
                    "is_running": app_is_operational,  # Changed: now shows if app is operational, not just scanning
                    "is_scanning": self.sniper.is_running,  # Added: shows if search cycle is in progress
                    "next_run": self.sniper.next_run_at.isoformat() if self.sniper.next_run_at else None,
                    "error_count": self.sniper.error_count
                }
            
            # Add circuit breaker state
            cb_state = openai_circuit_breaker.get_state()
            response_data["components"]["openai_circuit_breaker"] = {
                "state": cb_state["state"],
                "failure_count": cb_state["failure_count"],
                "last_failure_time": cb_state["last_failure_time"],
                "statistics": cb_state["statistics"]
            }
            
            # Return appropriate HTTP status
            status_code = 200 if overall_status == "healthy" else (503 if overall_status == "unhealthy" else 200)
            
            return web.json_response(response_data, status=status_code)
            
        except Exception as e:
            logger.error(f"Health check error: {e}", exc_info=True)
            return web.json_response(
                {"status": "error", "message": str(e)},
                status=500
            )
    
    async def health_db(self, request: web.Request) -> web.Response:
        """Database-specific health check endpoint."""
        try:
            db_status = await self._check_database()
            status_code = 200 if db_status["status"] == "ok" else 503
            return web.json_response(db_status, status=status_code)
        except Exception as e:
            logger.error(f"Database health check error: {e}")
            return web.json_response(
                {"status": "error", "error": str(e)},
                status=503
            )
    
    async def health_redis(self, request: web.Request) -> web.Response:
        """Redis-specific health check endpoint."""
        try:
            redis_status = await self._check_redis()
            status_code = 200 if redis_status["status"] in ("ok", "disabled") else 503
            return web.json_response(redis_status, status=status_code)
        except Exception as e:
            logger.error(f"Redis health check error: {e}")
            return web.json_response(
                {"status": "error", "error": str(e)},
                status=503
            )
    
    async def readiness_check(self, request: web.Request) -> web.Response:
        """Readiness probe - checks if app is ready to serve requests."""
        try:
            # Check database connection
            db_status = await self._check_database()
            db_ready = db_status["status"] == "ok"
            
            # Check if CV is loaded
            cv_ready = self.matcher_service and bool(self.matcher_service.cv_text)
            
            # Check if main loop is initialized
            app_ready = self.sniper is not None
            
            # Redis is optional, so we don't require it for readiness
            redis_status = await self._check_redis()
            redis_ready = redis_status["status"] in ("ok", "disabled")
            
            if db_ready and cv_ready and app_ready:
                return web.json_response({
                    "status": "ready",
                    "database": db_status["status"],
                    "redis": redis_status["status"],
                    "cv_loaded": cv_ready,
                    "app_initialized": app_ready
                })
            else:
                return web.json_response(
                    {
                        "status": "not_ready",
                        "database": db_status["status"],
                        "redis": redis_status["status"],
                        "cv_loaded": cv_ready,
                        "app_initialized": app_ready
                    },
                    status=503
                )
        except Exception as e:
            logger.error(f"Readiness check error: {e}")
            return web.json_response(
                {"status": "error", "message": str(e)},
                status=503
            )
    
    async def liveness_check(self, request: web.Request) -> web.Response:
        """Liveness probe - checks if app is alive."""
        return web.json_response({"status": "alive"})
    
    async def stats_endpoint(self, request: web.Request) -> web.Response:
        """Statistics endpoint - returns job offer statistics."""
        try:
            if not self.storage_service:
                return web.json_response(
                    {"error": "Storage service not available"},
                    status=503
                )
            
            stats = await self.storage_service.get_statistics()
            
            return web.json_response({
                "total_offers": stats.get("total_offers", 0),
                "analyzed_offers": stats.get("analyzed_offers", 0),
                "sent_notifications": stats.get("sent_notifications", 0),
                "average_score": stats.get("average_score", 0.0),
                "last_scan": stats.get("last_scan").isoformat() if stats.get("last_scan") else None
            })
        except Exception as e:
            logger.error(f"Stats endpoint error: {e}", exc_info=True)
            return web.json_response(
                {"error": str(e)},
                status=500
            )
    
    def _format_uptime(self, seconds: float) -> str:
        """Format uptime in human-readable format."""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")
        
        return " ".join(parts)
    
    async def start(self, host: str = "0.0.0.0", port: int = 8080):
        """Start health check server."""
        try:
            self.app = web.Application()
            
            # Register routes
            self.app.router.add_get('/health', self.health_check)
            self.app.router.add_get('/health/db', self.health_db)
            self.app.router.add_get('/health/redis', self.health_redis)
            self.app.router.add_get('/readiness', self.readiness_check)
            self.app.router.add_get('/liveness', self.liveness_check)
            self.app.router.add_get('/stats', self.stats_endpoint)
            
            # Start server
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, host, port)
            await self.site.start()
            
            logger.info(f"Health check server started on http://{host}:{port}")
            logger.info(f"  - Health: http://{host}:{port}/health")
            logger.info(f"  - Health DB: http://{host}:{port}/health/db")
            logger.info(f"  - Health Redis: http://{host}:{port}/health/redis")
            logger.info(f"  - Readiness: http://{host}:{port}/readiness")
            logger.info(f"  - Liveness: http://{host}:{port}/liveness")
            
        except Exception as e:
            logger.error(f"Failed to start health server: {e}", exc_info=True)
            raise
    
    async def stop(self):
        """Stop health check server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("Health check server stopped")


# Global health server instance
health_server = HealthServer()
