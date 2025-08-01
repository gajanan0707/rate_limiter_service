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
        with self._lock:
            key = (tenant_id, client_id, action_type)
            current_time = time.time()
            window_start = current_time - window_duration_seconds

            request_log = self._request_logs[key]

            while request_log and request_log[0] <= window_start:
                request_log.popleft()

            current_count = len(request_log)
            if current_count < max_requests:
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
        with self._lock:
            key = (tenant_id, client_id, action_type)
            current_time = time.time()
            window_start = current_time - window_duration_seconds

            request_log = self._request_logs[key]

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

        self._global_in_flight = 0
        self._tenant_in_flight: Dict[str, int] = defaultdict(int)

        self._tenant_queues: Dict[str, deque] = defaultdict(deque)

        self._global_lock = threading.RLock()
        self._tenant_locks: Dict[str, threading.RLock] = defaultdict(threading.RLock)

        self._shutdown = False

        self._processing_thread = threading.Thread(
            target=self._process_queued_requests, daemon=True
        )
        self._processing_thread.start()

    def can_process_immediately(self, tenant_id: str) -> bool:
        with self._global_lock:
            return self._global_in_flight < self.max_global_concurrent_requests

    def acquire_processing_slot(self, tenant_id: str) -> bool:
        with self._global_lock:
            if self._global_in_flight < self.max_global_concurrent_requests:
                self._global_in_flight += 1
                self._tenant_in_flight[tenant_id] += 1
                return True
            return False

    def release_processing_slot(self, tenant_id: str):
        with self._global_lock:
            if self._global_in_flight > 0:
                self._global_in_flight -= 1
            if self._tenant_in_flight[tenant_id] > 0:
                self._tenant_in_flight[tenant_id] -= 1

    def queue_request(self, queued_request: QueuedRequest) -> bool:
        tenant_id = queued_request.tenant_id

        with self._tenant_locks[tenant_id]:
            tenant_queue = self._tenant_queues[tenant_id]

            if len(tenant_queue) >= self.max_tenant_queue_size:
                return False

            tenant_queue.append(queued_request)
            return True

    def _process_queued_requests(self):
        while not self._shutdown:
            try:
                if not self.can_process_immediately(""):
                    time.sleep(0.1)
                    continue

                processed_any = False
                for tenant_id in list(self._tenant_queues.keys()):
                    with self._tenant_locks[tenant_id]:
                        tenant_queue = self._tenant_queues[tenant_id]

                        if tenant_queue and self.acquire_processing_slot(tenant_id):
                            queued_request = tenant_queue.popleft()
                            processed_any = True

                            processing_thread = threading.Thread(
                                target=self._execute_queued_request,
                                args=(queued_request,),
                            )
                            processing_thread.start()
                            break

                if not processed_any:
                    time.sleep(0.1)

            except Exception as e:
                print(f"Error in queue processing: {e}")
                time.sleep(0.1)

    def _execute_queued_request(self, queued_request: QueuedRequest):
        try:
            result = RateLimitResult(
                allowed=True,
                remaining_requests=0,
                reset_time_seconds=int(
                    time.time() + queued_request.window_duration_seconds
                ),
                status=RequestStatus.PROCESSED,
            )
            queued_request.result_callback(result)
        except Exception as e:
            print(f"Error executing queued request: {e}")
        finally:
            self.release_processing_slot(queued_request.tenant_id)

    def get_queue_status(self, tenant_id: str) -> Dict:
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
        if self.load_manager.acquire_processing_slot(tenant_id):
            try:
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
        rate_limit_status = self.sliding_window.get_status(
            tenant_id, client_id, action_type, max_requests, window_duration_seconds
        )
        queue_status = self.load_manager.get_queue_status(tenant_id)

        return {"rate_limit": rate_limit_status, "queue": queue_status}

    def shutdown(self):
        self.load_manager.shutdown()
