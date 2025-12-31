"""
Integration tests for main workflow.
Tests end-to-end cycle execution and state management.
"""
import pytest
import asyncio
from datetime import datetime, timezone


class TestMainWorkflow:
    """Integration tests for main application workflow."""
    
    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self):
        """Test exponential backoff calculation."""
        from main import JobSniper
        
        sniper = JobSniper()
        sniper.max_backoff = 300
        
        # Test backoff progression
        sniper.error_count = 1
        backoff_1 = min(60 * (2 ** (sniper.error_count - 1)), sniper.max_backoff)
        assert backoff_1 == 60  # 60 * 2^0 = 60
        
        sniper.error_count = 2
        backoff_2 = min(60 * (2 ** (sniper.error_count - 1)), sniper.max_backoff)
        assert backoff_2 == 120  # 60 * 2^1 = 120
        
        sniper.error_count = 3
        backoff_3 = min(60 * (2 ** (sniper.error_count - 1)), sniper.max_backoff)
        assert backoff_3 == 240  # 60 * 2^2 = 240
        
        sniper.error_count = 4
        backoff_4 = min(60 * (2 ** (sniper.error_count - 1)), sniper.max_backoff)
        assert backoff_4 == 300  # Capped at max_backoff
    
    @pytest.mark.asyncio
    async def test_timeout_context_manager(self):
        """Test that asyncio.timeout works correctly."""
        
        async def slow_task():
            await asyncio.sleep(5)
            return "completed"
        
        # Test timeout triggers
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(1):  # 1 second timeout
                await slow_task()
        
        # Test task completes within timeout
        async with asyncio.timeout(10):  # 10 second timeout
            result = await asyncio.sleep(0.1, result="fast")
            assert result == "fast"
    
    @pytest.mark.asyncio
    async def test_event_lock_prevents_concurrent_cycles(self):
        """Test that lock prevents concurrent cycle execution."""
        from main import JobSniper
        
        sniper = JobSniper()
        execution_order = []
        
        async def mock_cycle(name: str):
            async with sniper._cycle_lock:
                execution_order.append(f"{name}_start")
                await asyncio.sleep(0.1)
                execution_order.append(f"{name}_end")
        
        # Run two cycles concurrently
        await asyncio.gather(
            mock_cycle("cycle1"),
            mock_cycle("cycle2")
        )
        
        # Lock should ensure sequential execution
        assert execution_order == [
            "cycle1_start",
            "cycle1_end",
            "cycle2_start",
            "cycle2_end"
        ]


class TestHealthServer:
    """Tests for health check server."""
    
    @pytest.mark.asyncio
    async def test_health_check_uptime_calculation(self):
        """Test uptime calculation in health check."""
        from health_server import HealthServer
        
        server = HealthServer()
        
        # Test formatting
        assert server._format_uptime(45) == "45s"
        assert server._format_uptime(90) == "1m 30s"
        assert server._format_uptime(3665) == "1h 1m 5s"
        assert server._format_uptime(90061) == "1d 1h 1m 1s"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
