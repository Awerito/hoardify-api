import asyncio
import time
from collections import deque
from threading import Lock

from app.utils.logger import logger


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter for Spotify API requests.

    Tracks requests in a rolling window and provides dynamic interval
    recommendations for the scheduler based on current usage.
    """

    def __init__(
        self,
        window_seconds: int = 30,
        max_requests: int = 90,  # 180/min self-imposed limit (Spotify allows ~180/min)
        min_interval: float = 1.0,
        max_interval: float = 30.0,
        base_interval: float = 5.0,
    ):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.base_interval = base_interval
        self.requests: deque = deque()
        self._lock = Lock()

    def record_requests(self, count: int = 1) -> None:
        """Record N requests to the API."""
        with self._lock:
            now = time.time()
            for _ in range(count):
                self.requests.append(now)
            self._cleanup()
        logger.debug(f"Rate limiter: recorded {count} req, total in window: {len(self.requests)}")

    def _cleanup(self) -> None:
        """Remove requests outside the rolling window."""
        cutoff = time.time() - self.window_seconds
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

    def get_requests_in_window(self) -> int:
        """Get count of requests in current window."""
        with self._lock:
            self._cleanup()
            return len(self.requests)

    def get_usage_ratio(self) -> float:
        """Get current usage as a ratio (0.0 to 1.0+)."""
        return self.get_requests_in_window() / self.max_requests

    def get_next_interval(self) -> float:
        """Calculate next poll interval based on current usage."""
        usage = self.get_usage_ratio()

        if usage > 0.8:  # >80% - go slow
            interval = self.max_interval
        elif usage > 0.5:  # 50-80% - moderate
            interval = self.base_interval * 2
        elif usage > 0.2:  # 20-50% - normal
            interval = self.base_interval
        else:  # <20% - aggressive
            interval = self.min_interval

        logger.debug(
            f"Rate limiter: usage={usage:.1%}, next_interval={interval}s"
        )
        return interval

    async def wait_if_needed(self) -> float:
        """
        Wait if approaching rate limit. Non-blocking (uses asyncio.sleep).
        Returns seconds waited.
        """
        usage = self.get_usage_ratio()

        if usage > 0.9:  # >90% - wait before next batch
            wait_time = 3.0
            logger.info(f"Rate limiter: usage={usage:.1%}, waiting {wait_time}s")
            await asyncio.sleep(wait_time)
            return wait_time
        elif usage > 0.7:  # 70-90% - short wait
            wait_time = 1.0
            logger.info(f"Rate limiter: usage={usage:.1%}, waiting {wait_time}s")
            await asyncio.sleep(wait_time)
            return wait_time

        return 0.0

    def get_stats(self) -> dict:
        """Get current rate limiter stats."""
        count = self.get_requests_in_window()
        return {
            "requests_in_window": count,
            "max_requests": self.max_requests,
            "usage_ratio": count / self.max_requests,
            "window_seconds": self.window_seconds,
            "recommended_interval": self.get_next_interval(),
        }


# Global instance
spotify_rate_limiter = AdaptiveRateLimiter()
