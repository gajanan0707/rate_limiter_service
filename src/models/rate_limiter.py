import time
import threading
from collections import defaultdict, deque
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from enum import Enum


class RequestStatus(Enum):
    PROCESSED = "processed"
    QUEUED = "queued"
    REJECTED = "rejected"


@dataclass
class RateLimitResult:
    allowed: bool
    remaining_requests: int
    reset_time_seconds: Optional[int]
    status: RequestStatus


@dataclass
class QueuedRequest:
    tenant_id: str
    client_id: str
    action_type: str
    max_requests: int
    window_duration_seconds: int
    timestamp: float
    result_callback: callable


class SlidingWindowLog:
    """Sliding Window Log algorithm implementation for rate limiting."""

    def __init__(self):
        self._request_logs: Dict[Tuple[str, str, str], deque] = defaultdict(deque)
        self._lock = threading.RLock()

    def check_and_consume(
        self,
        tenant_id: str,
        client_id: str,
        action_type: str,
        max_requests: int,
        window_duration_seconds: int,
    ) -> RateLimitResult:
        """
        Check if request is allowed and consume a token if so.

        Args:
            tenant_id: Tenant identifier
            client_id: Client identifier (user ID, API key, etc.)
            action_type: Type of action (login, api_call, etc.)
            max_requests: Maximum requests allowed in the window
            window_duration_seconds: Window duration in seconds

        Returns:
            RateLimitResult with allowed status and remaining requests
        """
        with self._lock:
            key = (tenant_id, client_id, action_type)
            current_time = time.time()
            window_start = current_time - window_duration_seconds

            # Get or create the request log for this key
            request_log = self._request_logs[key]

            # Remove old timestamps outside the current window
            while request_log and request_log[0] <= window_start:
                request_log.popleft()

            # Check if request is allowed
            current_count = len(request_log)
            if current_count < max_requests:
                # Allow the request and record timestamp
                request_log.append(current_time)
                remaining = max_requests - current_count - 1
                reset_time = int(current_time + window_duration_seconds)
                return RateLimitResult(
                    allowed=True,
                    remaining_requests=remaining,
                    reset_time_seconds=reset_time,
                    status=RequestStatus.PROCESSED,
                )
            else:
                # Request denied - rate limit exceeded
                # Calculate when the oldest request will expire
                oldest_timestamp = request_log[0] if request_log else current_time
                reset_time = int(oldest_timestamp + window_duration_seconds)
                return RateLimitResult(
                    allowed=False,
                    remaining_requests=0,
                    reset_time_seconds=reset_time,
                    status=RequestStatus.PROCESSED,
                )

    def get_status(
        self,
        tenant_id: str,
        client_id: str,
        action_type: str,
        max_requests: int,
        window_duration_seconds: int,
    ) -> Dict:
        """Get current status for debugging purposes."""
        with self._lock:
            key = (tenant_id, client_id, action_type)
            current_time = time.time()
            window_start = current_time - window_duration_seconds

            request_log = self._request_logs[key]

            # Filter timestamps within current window
            valid_timestamps = [ts for ts in request_log if ts > window_start]
            current_count = len(valid_timestamps)
            remaining = max(0, max_requests - current_count)

            return {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "action_type": action_type,
                "current_count": current_count,
                "max_requests": max_requests,
                "remaining_requests": remaining,
                "window_duration_seconds": window_duration_seconds,
                "timestamps": valid_timestamps,
                "window_start": window_start,
                "current_time": current_time,
            }


class TenantLoadManager:
    """Manages server load across tenants with queuing and fairness."""

    def __init__(
        self, max_global_concurrent_requests: int = 100, max_tenant_queue_size: int = 50
    ):
        self.max_global_concurrent_requests = max_global_concurrent_requests
        self.max_tenant_queue_size = max_tenant_queue_size

        # Track current in-flight requests globally and per tenant
        self._global_in_flight = 0
        self._tenant_in_flight: Dict[str, int] = defaultdict(int)

        # Per-tenant request queues
        self._tenant_queues: Dict[str, deque] = defaultdict(deque)

        # Locks for thread safety
        self._global_lock = threading.RLock()
        self._tenant_locks: Dict[str, threading.RLock] = defaultdict(threading.RLock)

        # Shutdown flag
        self._shutdown = False

        # Background thread for processing queued requests
        self._processing_thread = threading.Thread(
            target=self._process_queued_requests, daemon=True
        )
        self._processing_thread.start()

    def can_process_immediately(self, tenant_id: str) -> bool:
        """Check if a request can be processed immediately without queuing."""
        with self._global_lock:
            return self._global_in_flight < self.max_global_concurrent_requests

    def acquire_processing_slot(self, tenant_id: str) -> bool:
        """Try to acquire a processing slot for immediate execution."""
        with self._global_lock:
            if self._global_in_flight < self.max_global_concurrent_requests:
                self._global_in_flight += 1
                self._tenant_in_flight[tenant_id] += 1
                return True
            return False

    def release_processing_slot(self, tenant_id: str):
        """Release a processing slot after request completion."""
        with self._global_lock:
            if self._global_in_flight > 0:
                self._global_in_flight -= 1
            if self._tenant_in_flight[tenant_id] > 0:
                self._tenant_in_flight[tenant_id] -= 1

    def queue_request(self, queued_request: QueuedRequest) -> bool:
        """Queue a request for later processing. Returns True if queued, False if rejected."""
        tenant_id = queued_request.tenant_id

        with self._tenant_locks[tenant_id]:
            tenant_queue = self._tenant_queues[tenant_id]

            if len(tenant_queue) >= self.max_tenant_queue_size:
                # Queue is full, reject the request
                return False

            tenant_queue.append(queued_request)
            return True

    def _process_queued_requests(self):
        """Background thread to process queued requests when capacity is available."""
        while not self._shutdown:
            try:
                # Check if we have global capacity
                if not self.can_process_immediately(""):
                    time.sleep(0.1)  # Wait before checking again
                    continue

                # Find a tenant with queued requests (round-robin fairness)
                processed_any = False
                for tenant_id in list(self._tenant_queues.keys()):
                    with self._tenant_locks[tenant_id]:
                        tenant_queue = self._tenant_queues[tenant_id]

                        if tenant_queue and self.acquire_processing_slot(tenant_id):
                            queued_request = tenant_queue.popleft()
                            processed_any = True

                            # Process the queued request in a separate thread
                            processing_thread = threading.Thread(
                                target=self._execute_queued_request,
                                args=(queued_request,),
                            )
                            processing_thread.start()
                            break

                if not processed_any:
                    time.sleep(0.1)  # No requests to process, wait

            except Exception as e:
                # Log error in production
                print(f"Error in queue processing: {e}")
                time.sleep(0.1)

    def _execute_queued_request(self, queued_request: QueuedRequest):
        """Execute a queued request and call its callback with the result."""
        try:
            result = RateLimitResult(
                allowed=True,
                remaining_requests=0,  # We don't know the exact remaining without checking
                reset_time_seconds=int(
                    time.time() + queued_request.window_duration_seconds
                ),
                status=RequestStatus.PROCESSED,
            )
            queued_request.result_callback(result)
        except Exception as e:
            # Log error in production
            print(f"Error executing queued request: {e}")
        finally:
            self.release_processing_slot(queued_request.tenant_id)

    def get_queue_status(self, tenant_id: str) -> Dict:
        """Get queue status for a specific tenant."""
        with self._tenant_locks[tenant_id]:
            return {
                "tenant_id": tenant_id,
                "queue_length": len(self._tenant_queues[tenant_id]),
                "max_queue_size": self.max_tenant_queue_size,
                "in_flight_requests": self._tenant_in_flight[tenant_id],
                "global_in_flight": self._global_in_flight,
                "max_global_concurrent": self.max_global_concurrent_requests,
            }

    def shutdown(self):
        """Gracefully shutdown the load manager."""
        self._shutdown = True


class DistributedRateLimiter:
    """Main rate limiter service combining sliding window log and tenant load management."""

    def __init__(
        self, max_global_concurrent_requests: int = 100, max_tenant_queue_size: int = 50
    ):
        self.sliding_window = SlidingWindowLog()
        self.load_manager = TenantLoadManager(
            max_global_concurrent_requests=max_global_concurrent_requests,
            max_tenant_queue_size=max_tenant_queue_size,
        )
        self._pending_results: Dict[str, RateLimitResult] = {}
        self._result_lock = threading.RLock()

    def check_and_consume(
        self,
        tenant_id: str,
        client_id: str,
        action_type: str,
        max_requests: int,
        window_duration_seconds: int,
    ) -> RateLimitResult:
        """
        Main entry point for rate limiting with load management.

        Returns immediately with result if capacity is available,
        otherwise queues the request and returns queued status.
        """
        # Try to acquire processing slot immediately
        if self.load_manager.acquire_processing_slot(tenant_id):
            try:
                # Process immediately
                result = self.sliding_window.check_and_consume(
                    tenant_id,
                    client_id,
                    action_type,
                    max_requests,
                    window_duration_seconds,
                )
                return result
            finally:
                self.load_manager.release_processing_slot(tenant_id)
        else:
            # Need to queue the request
            request_id = f"{tenant_id}_{client_id}_{action_type}_{time.time()}"

            def result_callback(result: RateLimitResult):
                with self._result_lock:
                    self._pending_results[request_id] = result

            queued_request = QueuedRequest(
                tenant_id=tenant_id,
                client_id=client_id,
                action_type=action_type,
                max_requests=max_requests,
                window_duration_seconds=window_duration_seconds,
                timestamp=time.time(),
                result_callback=result_callback,
            )

            if self.load_manager.queue_request(queued_request):
                return RateLimitResult(
                    allowed=False,
                    remaining_requests=0,
                    reset_time_seconds=None,
                    status=RequestStatus.QUEUED,
                )
            else:
                return RateLimitResult(
                    allowed=False,
                    remaining_requests=0,
                    reset_time_seconds=None,
                    status=RequestStatus.REJECTED,
                )

    def get_status(
        self,
        tenant_id: str,
        client_id: str,
        action_type: str,
        max_requests: int,
        window_duration_seconds: int,
    ) -> Dict:
        """Get comprehensive status including rate limit and queue information."""
        rate_limit_status = self.sliding_window.get_status(
            tenant_id, client_id, action_type, max_requests, window_duration_seconds
        )
        queue_status = self.load_manager.get_queue_status(tenant_id)

        return {"rate_limit": rate_limit_status, "queue": queue_status}

    def shutdown(self):
        """Gracefully shutdown the rate limiter."""
        self.load_manager.shutdown()
