import unittest
import time
import threading
from src.models.rate_limiter import TenantLoadManager, QueuedRequest, RequestStatus, RateLimitResult


class TestTenantLoadManager(unittest.TestCase):
    """Unit tests for the TenantLoadManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.load_manager = TenantLoadManager(
            max_global_concurrent_requests=5,
            max_tenant_queue_size=3
        )
    
    def tearDown(self):
        """Clean up after tests."""
        self.load_manager.shutdown()
    
    def test_acquire_and_release_slots(self):
        """Test basic slot acquisition and release."""
        tenant_id = "tenant1"
        
        # Should be able to acquire slots up to the limit
        for i in range(5):
            acquired = self.load_manager.acquire_processing_slot(tenant_id)
            self.assertTrue(acquired, f"Failed to acquire slot {i+1}")
        
        # Should not be able to acquire more slots
        acquired = self.load_manager.acquire_processing_slot(tenant_id)
        self.assertFalse(acquired)
        
        # Release one slot
        self.load_manager.release_processing_slot(tenant_id)
        
        # Should be able to acquire one more slot
        acquired = self.load_manager.acquire_processing_slot(tenant_id)
        self.assertTrue(acquired)
    
    def test_can_process_immediately(self):
        """Test the can_process_immediately method."""
        tenant_id = "tenant1"
        
        # Initially should be able to process
        self.assertTrue(self.load_manager.can_process_immediately(tenant_id))
        
        # Acquire all slots
        for _ in range(5):
            self.load_manager.acquire_processing_slot(tenant_id)
        
        # Should not be able to process immediately
        self.assertFalse(self.load_manager.can_process_immediately(tenant_id))
        
        # Release one slot
        self.load_manager.release_processing_slot(tenant_id)
        
        # Should be able to process immediately again
        self.assertTrue(self.load_manager.can_process_immediately(tenant_id))
    
    def test_queue_request_success(self):
        """Test successful request queuing."""
        tenant_id = "tenant1"
        
        def dummy_callback(result):
            pass
        
        queued_request = QueuedRequest(
            tenant_id=tenant_id,
            client_id="client1",
            action_type="api_call",
            max_requests=10,
            window_duration_seconds=60,
            timestamp=time.time(),
            result_callback=dummy_callback
        )
        
        # Should be able to queue request
        success = self.load_manager.queue_request(queued_request)
        self.assertTrue(success)
        
        # Check queue status
        status = self.load_manager.get_queue_status(tenant_id)
        self.assertEqual(status["queue_length"], 1)
        self.assertEqual(status["max_queue_size"], 3)
    
    def test_queue_request_overflow(self):
        """Test request queuing when queue is full."""
        tenant_id = "tenant1"
        
        def dummy_callback(result):
            pass
        
        # Fill up the queue
        for i in range(3):
            queued_request = QueuedRequest(
                tenant_id=tenant_id,
                client_id=f"client{i}",
                action_type="api_call",
                max_requests=10,
                window_duration_seconds=60,
                timestamp=time.time(),
                result_callback=dummy_callback
            )
            success = self.load_manager.queue_request(queued_request)
            self.assertTrue(success)
        
        # Try to queue one more (should fail)
        overflow_request = QueuedRequest(
            tenant_id=tenant_id,
            client_id="client_overflow",
            action_type="api_call",
            max_requests=10,
            window_duration_seconds=60,
            timestamp=time.time(),
            result_callback=dummy_callback
        )
        success = self.load_manager.queue_request(overflow_request)
        self.assertFalse(success)
        
        # Queue length should still be 3
        status = self.load_manager.get_queue_status(tenant_id)
        self.assertEqual(status["queue_length"], 3)
    
    def test_different_tenant_queues_isolated(self):
        """Test that different tenants have isolated queues."""
        tenant1 = "tenant1"
        tenant2 = "tenant2"
        
        def dummy_callback(result):
            pass
        
        # Fill up tenant1's queue
        for i in range(3):
            queued_request = QueuedRequest(
                tenant_id=tenant1,
                client_id=f"client{i}",
                action_type="api_call",
                max_requests=10,
                window_duration_seconds=60,
                timestamp=time.time(),
                result_callback=dummy_callback
            )
            success = self.load_manager.queue_request(queued_request)
            self.assertTrue(success)
        
        # tenant2 should still be able to queue requests
        queued_request = QueuedRequest(
            tenant_id=tenant2,
            client_id="client1",
            action_type="api_call",
            max_requests=10,
            window_duration_seconds=60,
            timestamp=time.time(),
            result_callback=dummy_callback
        )
        success = self.load_manager.queue_request(queued_request)
        self.assertTrue(success)
        
        # Check queue statuses
        status1 = self.load_manager.get_queue_status(tenant1)
        status2 = self.load_manager.get_queue_status(tenant2)
        
        self.assertEqual(status1["queue_length"], 3)
        self.assertEqual(status2["queue_length"], 1)
    
    def test_queue_processing(self):
        """Test that queued requests are processed when capacity becomes available."""
        tenant_id = "tenant1"
        processed_results = []
        
        def result_callback(result):
            processed_results.append(result)
        
        # Fill up all processing slots
        for _ in range(5):
            self.load_manager.acquire_processing_slot(tenant_id)
        
        # Queue a request
        queued_request = QueuedRequest(
            tenant_id=tenant_id,
            client_id="client1",
            action_type="api_call",
            max_requests=10,
            window_duration_seconds=60,
            timestamp=time.time(),
            result_callback=result_callback
        )
        success = self.load_manager.queue_request(queued_request)
        self.assertTrue(success)
        
        # Release a slot to trigger processing
        self.load_manager.release_processing_slot(tenant_id)
        
        # Wait a bit for background processing
        time.sleep(0.5)
        
        # The queued request should have been processed
        self.assertEqual(len(processed_results), 1)
        
        # Queue should be empty
        status = self.load_manager.get_queue_status(tenant_id)
        self.assertEqual(status["queue_length"], 0)
    
    def test_concurrent_slot_acquisition(self):
        """Test thread safety of slot acquisition."""
        tenant_id = "tenant1"
        successful_acquisitions = []
        failed_acquisitions = []
        
        def try_acquire():
            if self.load_manager.acquire_processing_slot(tenant_id):
                successful_acquisitions.append(threading.current_thread().ident)
            else:
                failed_acquisitions.append(threading.current_thread().ident)
        
        # Create 10 threads trying to acquire slots
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=try_acquire)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have exactly 5 successful acquisitions and 5 failures
        self.assertEqual(len(successful_acquisitions), 5)
        self.assertEqual(len(failed_acquisitions), 5)
        
        # All successful acquisitions should be unique threads
        self.assertEqual(len(set(successful_acquisitions)), 5)
    
    def test_fairness_across_tenants(self):
        """Test that queue processing is fair across tenants."""
        tenant1 = "tenant1"
        tenant2 = "tenant2"
        processed_tenant1 = []
        processed_tenant2 = []
        
        def callback_tenant1(result):
            processed_tenant1.append(result)
        
        def callback_tenant2(result):
            processed_tenant2.append(result)
        
        # Fill up all processing slots
        for _ in range(5):
            self.load_manager.acquire_processing_slot("temp_tenant")
        
        # Queue requests for both tenants
        for i in range(3):
            # Queue for tenant1
            request1 = QueuedRequest(
                tenant_id=tenant1,
                client_id=f"client{i}",
                action_type="api_call",
                max_requests=10,
                window_duration_seconds=60,
                timestamp=time.time(),
                result_callback=callback_tenant1
            )
            self.load_manager.queue_request(request1)
            
            # Queue for tenant2
            request2 = QueuedRequest(
                tenant_id=tenant2,
                client_id=f"client{i}",
                action_type="api_call",
                max_requests=10,
                window_duration_seconds=60,
                timestamp=time.time(),
                result_callback=callback_tenant2
            )
            self.load_manager.queue_request(request2)
        
        # Release all slots to trigger processing
        for _ in range(5):
            self.load_manager.release_processing_slot("temp_tenant")
        
        # Wait for processing
        time.sleep(1.0)
        
        # Both tenants should have had some requests processed
        # (exact fairness depends on timing, but both should get some)
        total_processed = len(processed_tenant1) + len(processed_tenant2)
        self.assertGreater(total_processed, 0)
        
        # If any were processed, both tenants should have gotten some
        if total_processed > 1:
            self.assertGreater(len(processed_tenant1), 0)
            self.assertGreater(len(processed_tenant2), 0)
    
    def test_get_queue_status(self):
        """Test the get_queue_status method."""
        tenant_id = "tenant1"
        
        # Initial status
        status = self.load_manager.get_queue_status(tenant_id)
        self.assertEqual(status["tenant_id"], tenant_id)
        self.assertEqual(status["queue_length"], 0)
        self.assertEqual(status["max_queue_size"], 3)
        self.assertEqual(status["in_flight_requests"], 0)
        self.assertEqual(status["global_in_flight"], 0)
        self.assertEqual(status["max_global_concurrent"], 5)
        
        # Acquire some slots and queue some requests
        self.load_manager.acquire_processing_slot(tenant_id)
        self.load_manager.acquire_processing_slot(tenant_id)
        
        def dummy_callback(result):
            pass
        
        queued_request = QueuedRequest(
            tenant_id=tenant_id,
            client_id="client1",
            action_type="api_call",
            max_requests=10,
            window_duration_seconds=60,
            timestamp=time.time(),
            result_callback=dummy_callback
        )
        self.load_manager.queue_request(queued_request)
        
        # Check updated status
        status = self.load_manager.get_queue_status(tenant_id)
        self.assertEqual(status["queue_length"], 1)
        self.assertEqual(status["in_flight_requests"], 2)
        self.assertEqual(status["global_in_flight"], 2)


if __name__ == '__main__':
    unittest.main()

