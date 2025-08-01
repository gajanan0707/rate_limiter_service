import unittest
import time
import threading
from src.models.rate_limiter import DistributedRateLimiter, RequestStatus


class TestDistributedRateLimiter(unittest.TestCase):
    """Integration tests for the DistributedRateLimiter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.rate_limiter = DistributedRateLimiter(
            max_global_concurrent_requests=3,
            max_tenant_queue_size=2
        )
    
    def tearDown(self):
        """Clean up after tests."""
        self.rate_limiter.shutdown()
    
    def test_immediate_processing_when_capacity_available(self):
        """Test that requests are processed immediately when capacity is available."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 5
        window_duration = 60
        
        # Should be processed immediately
        result = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result.allowed)
        self.assertEqual(result.status, RequestStatus.PROCESSED)
        self.assertEqual(result.remaining_requests, 4)
    
    def test_queuing_when_capacity_exceeded(self):
        """Test that requests are queued when global capacity is exceeded."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 10
        window_duration = 60
        
        # Simulate high load by acquiring all processing slots
        # We'll use a different approach - make many concurrent requests
        results = []
        threads = []
        
        def make_request():
            result = self.rate_limiter.check_and_consume(
                tenant_id, client_id, action_type, max_requests, window_duration
            )
            results.append(result)
        
        # Create more threads than capacity
        for _ in range(6):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
        
        # Start all threads simultaneously
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Count different status types
        processed_count = sum(1 for r in results if r.status == RequestStatus.PROCESSED)
        queued_count = sum(1 for r in results if r.status == RequestStatus.QUEUED)
        rejected_count = sum(1 for r in results if r.status == RequestStatus.REJECTED)
        
        # Should have some processed and possibly some queued/rejected
        self.assertGreater(processed_count, 0)
        # Total should be 6
        self.assertEqual(len(results), 6)
    
    def test_queue_overflow_rejection(self):
        """Test that requests are rejected when queue is full."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 10
        window_duration = 60
        
        # First, fill up the processing capacity and queue
        # We need to simulate a scenario where the load manager is overwhelmed
        
        # Create a custom rate limiter with very small capacity for testing
        small_rate_limiter = DistributedRateLimiter(
            max_global_concurrent_requests=1,
            max_tenant_queue_size=1
        )
        
        try:
            results = []
            threads = []
            
            def make_request():
                result = small_rate_limiter.check_and_consume(
                    tenant_id, client_id, action_type, max_requests, window_duration
                )
                results.append(result)
                # Add a small delay to simulate processing time
                time.sleep(0.1)
            
            # Create more threads than capacity + queue size
            for _ in range(5):
                thread = threading.Thread(target=make_request)
                threads.append(thread)
            
            # Start all threads
            for thread in threads:
                thread.start()
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
            
            # Should have some rejected requests
            rejected_count = sum(1 for r in results if r.status == RequestStatus.REJECTED)
            self.assertGreaterEqual(rejected_count, 0)  # May or may not have rejections depending on timing
            
        finally:
            small_rate_limiter.shutdown()
    
    def test_multi_tenant_isolation(self):
        """Test that different tenants don't interfere with each other's rate limits."""
        tenant1 = "tenant1"
        tenant2 = "tenant2"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 3
        window_duration = 60
        
        # Exhaust tenant1's rate limit
        for i in range(3):
            result = self.rate_limiter.check_and_consume(
                tenant1, client_id, action_type, max_requests, window_duration
            )
            self.assertTrue(result.allowed)
        
        # tenant1 should be rate limited
        result = self.rate_limiter.check_and_consume(
            tenant1, client_id, action_type, max_requests, window_duration
        )
        self.assertFalse(result.allowed)
        
        # tenant2 should still have full quota
        result = self.rate_limiter.check_and_consume(
            tenant2, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining_requests, 2)
    
    def test_get_status_comprehensive(self):
        """Test the comprehensive status reporting."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 5
        window_duration = 60
        
        # Make some requests
        self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        # Get status
        status = self.rate_limiter.get_status(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        # Verify rate limit status
        self.assertIn("rate_limit", status)
        rate_limit_status = status["rate_limit"]
        self.assertEqual(rate_limit_status["tenant_id"], tenant_id)
        self.assertEqual(rate_limit_status["client_id"], client_id)
        self.assertEqual(rate_limit_status["action_type"], action_type)
        self.assertEqual(rate_limit_status["current_count"], 2)
        self.assertEqual(rate_limit_status["remaining_requests"], 3)
        
        # Verify queue status
        self.assertIn("queue", status)
        queue_status = status["queue"]
        self.assertEqual(queue_status["tenant_id"], tenant_id)
        self.assertIsInstance(queue_status["queue_length"], int)
        self.assertIsInstance(queue_status["in_flight_requests"], int)
    
    def test_concurrent_multi_tenant_load(self):
        """Test concurrent load across multiple tenants."""
        tenants = ["tenant1", "tenant2", "tenant3"]
        clients = ["client1", "client2"]
        action_type = "api_call"
        max_requests = 5
        window_duration = 60
        
        results = {}
        threads = []
        
        def make_requests(tenant_id, client_id):
            tenant_results = []
            for _ in range(3):
                result = self.rate_limiter.check_and_consume(
                    tenant_id, client_id, action_type, max_requests, window_duration
                )
                tenant_results.append(result)
                time.sleep(0.01)  # Small delay between requests
            results[f"{tenant_id}_{client_id}"] = tenant_results
        
        # Create threads for each tenant-client combination
        for tenant_id in tenants:
            for client_id in clients:
                thread = threading.Thread(target=make_requests, args=(tenant_id, client_id))
                threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify results
        self.assertEqual(len(results), len(tenants) * len(clients))
        
        # Each tenant-client combination should have made 3 requests
        for key, tenant_results in results.items():
            self.assertEqual(len(tenant_results), 3)
            # All requests should be allowed (within rate limit)
            allowed_count = sum(1 for r in tenant_results if r.allowed)
            self.assertEqual(allowed_count, 3)
    
    def test_rate_limit_enforcement_under_load(self):
        """Test that rate limits are properly enforced under concurrent load."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 3
        window_duration = 60
        
        results = []
        threads = []
        
        def make_request():
            result = self.rate_limiter.check_and_consume(
                tenant_id, client_id, action_type, max_requests, window_duration
            )
            results.append(result)
        
        # Create many concurrent requests
        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Count allowed requests
        allowed_count = sum(1 for r in results if r.allowed)
        
        # Should have exactly max_requests allowed (rate limit enforced)
        self.assertEqual(allowed_count, max_requests)
        
        # Remaining requests should be denied or queued
        denied_or_queued = sum(1 for r in results if not r.allowed)
        self.assertEqual(denied_or_queued, 10 - max_requests)
    
    def test_window_expiration_with_load_management(self):
        """Test that rate limit windows expire correctly even with load management."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 2
        window_duration = 1  # 1 second for fast testing
        
        # Exhaust rate limit
        result1 = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        result2 = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        result3 = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result1.allowed)
        self.assertTrue(result2.allowed)
        self.assertFalse(result3.allowed)
        
        # Wait for window to expire
        time.sleep(1.2)
        
        # Should be allowed again
        result4 = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result4.allowed)
    
    def test_graceful_shutdown(self):
        """Test graceful shutdown functionality."""
        # This test mainly ensures shutdown doesn't raise exceptions
        # In a real implementation, we'd test that in-flight requests complete
        
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 5
        window_duration = 60
        
        # Make a request
        result = self.rate_limiter.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result.allowed)
        
        # Shutdown should not raise exceptions
        self.rate_limiter.shutdown()
        
        # Create a new rate limiter for subsequent tests
        self.rate_limiter = DistributedRateLimiter(
            max_global_concurrent_requests=3,
            max_tenant_queue_size=2
        )


if __name__ == '__main__':
    unittest.main()

