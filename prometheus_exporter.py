"""
Prometheus metrics exporter for JobSniper health checks.
Converts health check JSON to Prometheus metrics.
"""
import asyncio
import json
from aiohttp import web
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Gauge, Histogram
from prometheus_client.core import CollectorRegistry, REGISTRY
import httpx

# Create custom registry
registry = CollectorRegistry()

# Define metrics
health_status = Gauge(
    'jobsniper_health_status',
    'Overall health status (1=healthy, 0.5=degraded, 0=unhealthy)',
    ['component'],
    registry=registry
)

component_status = Gauge(
    'jobsniper_component_status',
    'Component status (1=ok, 0=error)',
    ['component', 'type'],
    registry=registry
)

response_time_ms = Histogram(
    'jobsniper_response_time_ms',
    'Response time in milliseconds',
    ['component'],
    registry=registry,
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000]
)

uptime_seconds = Gauge(
    'jobsniper_uptime_seconds',
    'Application uptime in seconds',
    registry=registry
)

circuit_breaker_state = Gauge(
    'jobsniper_circuit_breaker_state',
    'Circuit breaker state (1=closed, 0.5=half_open, 0=open)',
    ['service'],
    registry=registry
)

circuit_breaker_failures = Gauge(
    'jobsniper_circuit_breaker_failures',
    'Circuit breaker failure count',
    ['service'],
    registry=registry
)

circuit_breaker_total_calls = Gauge(
    'jobsniper_circuit_breaker_total_calls',
    'Total circuit breaker calls',
    ['service'],
    registry=registry
)

circuit_breaker_total_failures = Gauge(
    'jobsniper_circuit_breaker_total_failures',
    'Total circuit breaker failures',
    ['service'],
    registry=registry
)

# Statistics metrics
total_offers = Gauge(
    'jobsniper_total_offers',
    'Total number of job offers in database',
    registry=registry
)

analyzed_offers = Gauge(
    'jobsniper_analyzed_offers',
    'Number of offers analyzed by AI',
    registry=registry
)

sent_notifications = Gauge(
    'jobsniper_sent_notifications',
    'Number of notifications sent',
    registry=registry
)

average_match_score = Gauge(
    'jobsniper_average_match_score',
    'Average AI match score',
    registry=registry
)


async def fetch_health_data():
    """Fetch health data from JobSniper health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://app:8080/health")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error fetching health data: {e}")
        return None


async def fetch_stats_data():
    """Fetch statistics data from JobSniper stats endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://app:8080/stats")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error fetching stats data: {e}")
        return None


def update_metrics(health_data: dict):
    """Update Prometheus metrics from health data."""
    if not health_data:
        return
    
    # Overall status
    status_map = {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0, "error": 0.0}
    health_status.labels(component="overall").set(
        status_map.get(health_data.get("status", "error"), 0.0)
    )
    
    # Uptime
    uptime_seconds.set(health_data.get("uptime_seconds", 0))
    
    # Components
    components = health_data.get("components", {})
    
    # Database
    db = components.get("database", {})
    db_status_val = 1.0 if db.get("status") == "ok" else 0.0
    component_status.labels(component="database", type="status").set(db_status_val)
    if db.get("response_time_ms") is not None:
        response_time_ms.labels(component="database").observe(db.get("response_time_ms"))
    
    # Redis
    redis = components.get("redis", {})
    redis_status_val = 1.0 if redis.get("status") in ("ok", "disabled") else 0.0
    component_status.labels(component="redis", type="status").set(redis_status_val)
    if redis.get("response_time_ms") is not None:
        response_time_ms.labels(component="redis").observe(redis.get("response_time_ms"))
    
    # CV
    cv = components.get("cv", {})
    cv_status_val = 1.0 if cv.get("status") == "loaded" else 0.0
    component_status.labels(component="cv", type="status").set(cv_status_val)
    
    # Application
    app = components.get("application", {})
    # is_running now represents if app is operational (not just scanning)
    app_running = 1.0 if app.get("is_running", False) else 0.0
    component_status.labels(component="application", type="running").set(app_running)
    # Also track if actively scanning
    app_scanning = 1.0 if app.get("is_scanning", False) else 0.0
    component_status.labels(component="application", type="scanning").set(app_scanning)
    
    # Circuit Breaker
    cb = components.get("openai_circuit_breaker", {})
    state_map = {"closed": 1.0, "half_open": 0.5, "open": 0.0}
    circuit_breaker_state.labels(service="openai").set(
        state_map.get(cb.get("state", "closed"), 0.0)
    )
    circuit_breaker_failures.labels(service="openai").set(
        cb.get("failure_count", 0)
    )
    
    stats = cb.get("statistics", {})
    circuit_breaker_total_calls.labels(service="openai").set(stats.get("total_calls", 0))
    circuit_breaker_total_failures.labels(service="openai").set(stats.get("total_failures", 0))


def update_stats_metrics(stats_data: dict):
    """Update Prometheus metrics from stats data."""
    if not stats_data:
        return
    
    total_offers.set(stats_data.get("total_offers", 0))
    analyzed_offers.set(stats_data.get("analyzed_offers", 0))
    sent_notifications.set(stats_data.get("sent_notifications", 0))
    average_match_score.set(stats_data.get("average_score", 0.0))


async def metrics_task():
    """Background task to periodically update metrics."""
    while True:
        health_data = await fetch_health_data()
        if health_data:
            update_metrics(health_data)
        
        stats_data = await fetch_stats_data()
        if stats_data:
            update_stats_metrics(stats_data)
        
        await asyncio.sleep(10)  # Update every 10 seconds


async def metrics_handler(request):
    """Handler for /metrics endpoint."""
    try:
        metrics_data = generate_latest(registry)
        # generate_latest returns bytes
        # Use body parameter for bytes, not text
        return web.Response(
            body=metrics_data,
            content_type='text/plain'
        )
    except Exception as e:
        print(f"Error in metrics_handler: {e}", flush=True)
        import traceback
        traceback.print_exc()
        error_msg = f"Error generating metrics: {str(e)}"
        return web.Response(
            text=error_msg,
            status=500,
            content_type='text/plain'
        )


async def init_app():
    """Initialize the exporter app."""
    app = web.Application()
    app.router.add_get('/metrics', metrics_handler)
    
    # Start background task
    asyncio.create_task(metrics_task())
    
    return app


async def main():
    """Main entry point."""
    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 9091)
    await site.start()
    
    print("Prometheus exporter started on http://0.0.0.0:9091/metrics")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
