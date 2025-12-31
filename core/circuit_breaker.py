"""
Circuit breaker wrapper for async functions with monitoring.
Provides protection against cascading failures in external API calls.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Callable, Optional, TypeVar, Awaitable, Any
from enum import Enum

from openai import RateLimitError, APITimeoutError, APIError

from core import setup_logger

logger = setup_logger(__name__, "main.log")

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class OpenAICircuitBreaker:
    """
    Circuit breaker for OpenAI API calls with async support and monitoring.
    
    Opens circuit after 5 consecutive failures in 60 seconds.
    Half-open after 30 seconds to test recovery.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        # State tracking
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED
        self.state_changed_at = datetime.now(timezone.utc)
        
        # Statistics
        self.total_calls = 0
        self.total_failures = 0
        self.total_circuit_opens = 0
        self.last_success_time: Optional[datetime] = None
    
    def _should_open_circuit(self) -> bool:
        """Check if circuit should be opened."""
        if self.failure_count >= self.failure_threshold:
            # Check if failures are recent (within 60 seconds)
            if self.last_failure_time:
                time_since_last_failure = (
                    datetime.now(timezone.utc) - self.last_failure_time
                ).total_seconds()
                if time_since_last_failure <= 60:
                    return True
            else:
                return True
        return False
    
    def _should_attempt_half_open(self) -> bool:
        """Check if circuit should transition to half-open."""
        if self.state == CircuitState.OPEN:
            time_since_open = (
                datetime.now(timezone.utc) - self.state_changed_at
            ).total_seconds()
            return time_since_open >= self.recovery_timeout
        return False
    
    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to function
        
        Returns:
            Result from function call
        
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Original exception: If function call fails
        """
        self.total_calls += 1
        
        # Check if we should transition to half-open
        if self._should_attempt_half_open():
            logger.info("🔄 Circuit breaker transitioning to HALF_OPEN state")
            self.state = CircuitState.HALF_OPEN
            self.state_changed_at = datetime.now(timezone.utc)
            self.failure_count = 0  # Reset for half-open test
        
        # Check if circuit is open
        if self.state == CircuitState.OPEN:
            if not self._should_attempt_half_open():
                self.total_failures += 1
                error_msg = (
                    f"Circuit breaker is OPEN. "
                    f"Last failure: {self.last_failure_time.isoformat() if self.last_failure_time else 'never'}. "
                    f"Will retry in {self.recovery_timeout}s"
                )
                logger.warning(f"🚫 {error_msg}")
                raise CircuitBreakerOpenError(error_msg)
        
        # Attempt function call
        try:
            result = await func(*args, **kwargs)
            
            # Success - close circuit if it was half-open
            if self.state == CircuitState.HALF_OPEN:
                logger.info("✅ Circuit breaker recovered - transitioning to CLOSED state")
                self.state = CircuitState.CLOSED
                self.state_changed_at = datetime.now(timezone.utc)
            
            # Reset failure count on success
            self.failure_count = 0
            self.last_success_time = datetime.now(timezone.utc)
            
            return result
            
        except self.expected_exception as e:
            # Failure - increment counter
            self.failure_count += 1
            self.total_failures += 1
            self.last_failure_time = datetime.now(timezone.utc)
            
            # Check if we should open circuit
            if self._should_open_circuit() and self.state != CircuitState.OPEN:
                logger.error(
                    f"🔴 Circuit breaker OPENING after {self.failure_count} failures. "
                    f"Will retry in {self.recovery_timeout}s"
                )
                self.state = CircuitState.OPEN
                self.state_changed_at = datetime.now(timezone.utc)
                self.total_circuit_opens += 1
            
            # Re-raise exception
            raise
    
    def get_state(self) -> dict:
        """Get current circuit breaker state and statistics."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "state_changed_at": self.state_changed_at.isoformat(),
            "statistics": {
                "total_calls": self.total_calls,
                "total_failures": self.total_failures,
                "total_circuit_opens": self.total_circuit_opens,
                "success_rate": (
                    (self.total_calls - self.total_failures) / self.total_calls * 100
                    if self.total_calls > 0 else 100.0
                )
            }
        }
    
    def reset(self):
        """Manually reset circuit breaker to closed state."""
        logger.info("🔄 Manually resetting circuit breaker")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.state_changed_at = datetime.now(timezone.utc)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting requests."""
    pass


# Global circuit breaker instance for OpenAI API
openai_circuit_breaker = OpenAICircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30,
    expected_exception=(RateLimitError, APITimeoutError, APIError, Exception)
)
