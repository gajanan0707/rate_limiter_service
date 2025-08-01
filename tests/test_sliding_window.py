import unittest
import time
import threading
from src.models.rate_limiter import SlidingWindowLog, RequestStatus


class TestSlidingWindowLog(unittest.TestCase):
    """Unit tests for the SlidingWindowLog algorithm."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sliding_window = SlidingWindowLog()
    
    def test_basic_rate_limiting(self):
        """Test basic rate limiting functionality."""
        tenant_id = "test_tenant"
        client_id = "test_client"
        action_type = "api_call"
        max_requests = 3
        window_duration = 60
        
        # First request should be allowed
        result1 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result1.allowed)
        self.assertEqual(result1.remaining_requests, 2)
        self.assertEqual(result1.status, RequestStatus.PROCESSED)
        
        # Second request should be allowed
        result2 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result2.allowed)
        self.assertEqual(result2.remaining_requests, 1)
        
        # Third request should be allowed
        result3 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result3.allowed)
        self.assertEqual(result3.remaining_requests, 0)
        
        # Fourth request should be denied
        result4 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertFalse(result4.allowed)
        self.assertEqual(result4.remaining_requests, 0)
    
    def test_different_tenants_isolated(self):
        """Test that different tenants are isolated from each other."""
        tenant1 = "tenant1"
        tenant2 = "tenant2"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 2
        window_duration = 60
        
        # Consume all requests for tenant1
        result1 = self.sliding_window.check_and_consume(
            tenant1, client_id, action_type, max_requests, window_duration
        )
        result2 = self.sliding_window.check_and_consume(
            tenant1, client_id, action_type, max_requests, window_duration
        )
        result3 = self.sliding_window.check_and_consume(
            tenant1, client_id, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result1.allowed)
        self.assertTrue(result2.allowed)
        self.assertFalse(result3.allowed)  # Should be denied
        
        # tenant2 should still have full quota
        result4 = self.sliding_window.check_and_consume(
            tenant2, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result4.allowed)
        self.assertEqual(result4.remaining_requests, 1)
    
    def test_different_clients_isolated(self):
        """Test that different clients within the same tenant are isolated."""
        tenant_id = "tenant1"
        client1 = "client1"
        client2 = "client2"
        action_type = "api_call"
        max_requests = 2
        window_duration = 60
        
        # Consume all requests for client1
        result1 = self.sliding_window.check_and_consume(
            tenant_id, client1, action_type, max_requests, window_duration
        )
        result2 = self.sliding_window.check_and_consume(
            tenant_id, client1, action_type, max_requests, window_duration
        )
        result3 = self.sliding_window.check_and_consume(
            tenant_id, client1, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result1.allowed)
        self.assertTrue(result2.allowed)
        self.assertFalse(result3.allowed)  # Should be denied
        
        # client2 should still have full quota
        result4 = self.sliding_window.check_and_consume(
            tenant_id, client2, action_type, max_requests, window_duration
        )
        self.assertTrue(result4.allowed)
        self.assertEqual(result4.remaining_requests, 1)
    
    def test_different_action_types_isolated(self):
        """Test that different action types are isolated."""
        tenant_id = "tenant1"
        client_id = "client1"
        action1 = "login"
        action2 = "api_call"
        max_requests = 2
        window_duration = 60
        
        # Consume all requests for action1
        result1 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action1, max_requests, window_duration
        )
        result2 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action1, max_requests, window_duration
        )
        result3 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action1, max_requests, window_duration
        )
        
        self.assertTrue(result1.allowed)
        self.assertTrue(result2.allowed)
        self.assertFalse(result3.allowed)  # Should be denied
        
        # action2 should still have full quota
        result4 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action2, max_requests, window_duration
        )
        self.assertTrue(result4.allowed)
        self.assertEqual(result4.remaining_requests, 1)
    
    def test_window_expiration(self):
        """Test that old requests expire from the window."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 2
        window_duration = 1  # 1 second window for fast testing
        
        # Consume all requests
        result1 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        result2 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        result3 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result1.allowed)
        self.assertTrue(result2.allowed)
        self.assertFalse(result3.allowed)  # Should be denied
        
        # Wait for window to expire
        time.sleep(1.1)
        
        # Should be allowed again
        result4 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result4.allowed)
        self.assertEqual(result4.remaining_requests, 1)
    
    def test_reset_time_calculation(self):
        """Test that reset time is calculated correctly."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 1
        window_duration = 60
        
        start_time = time.time()
        result = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.reset_time_seconds)
        
        # Reset time should be approximately start_time + window_duration
        expected_reset = start_time + window_duration
        self.assertAlmostEqual(result.reset_time_seconds, expected_reset, delta=1)
        
        # Next request should be denied with reset time based on first request
        result2 = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertFalse(result2.allowed)
        self.assertIsNotNone(result2.reset_time_seconds)
        self.assertAlmostEqual(result2.reset_time_seconds, expected_reset, delta=1)
    
    def test_get_status(self):
        """Test the get_status method."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 3
        window_duration = 60
        
        # Make some requests
        self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        status = self.sliding_window.get_status(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        
        self.assertEqual(status["tenant_id"], tenant_id)
        self.assertEqual(status["client_id"], client_id)
        self.assertEqual(status["action_type"], action_type)
        self.assertEqual(status["current_count"], 2)
        self.assertEqual(status["max_requests"], max_requests)
        self.assertEqual(status["remaining_requests"], 1)
        self.assertEqual(status["window_duration_seconds"], window_duration)
        self.assertEqual(len(status["timestamps"]), 2)
    
    def test_concurrent_access(self):
        """Test thread safety with concurrent access."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 10
        window_duration = 60
        
        results = []
        threads = []
        
        def make_request():
            result = self.sliding_window.check_and_consume(
                tenant_id, client_id, action_type, max_requests, window_duration
            )
            results.append(result)
        
        # Create 20 threads to make concurrent requests
        for _ in range(20):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Count allowed and denied requests
        allowed_count = sum(1 for result in results if result.allowed)
        denied_count = sum(1 for result in results if not result.allowed)
        
        # Should have exactly max_requests allowed and the rest denied
        self.assertEqual(allowed_count, max_requests)
        self.assertEqual(denied_count, 20 - max_requests)
    
    def test_edge_case_zero_window(self):
        """Test edge case with very small window duration."""
        tenant_id = "tenant1"
        client_id = "client1"
        action_type = "api_call"
        max_requests = 5
        window_duration = 0.1  # 100ms window
        
        # Make rapid requests
        results = []
        for _ in range(10):
            result = self.sliding_window.check_and_consume(
                tenant_id, client_id, action_type, max_requests, window_duration
            )
            results.append(result)
        
        # Some should be allowed, some denied
        allowed_count = sum(1 for result in results if result.allowed)
        self.assertLessEqual(allowed_count, max_requests)
        
        # Wait for window to expire
        time.sleep(0.2)
        
        # Should be allowed again
        result = self.sliding_window.check_and_consume(
            tenant_id, client_id, action_type, max_requests, window_duration
        )
        self.assertTrue(result.allowed)


if __name__ == '__main__':
    unittest.main()

