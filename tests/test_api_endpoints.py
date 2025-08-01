import unittest
import json
import time
import threading
from src.main import app
from src.routes.rate_limiter import get_rate_limiter


class TestAPIEndpoints(unittest.TestCase):
    """Tests for the Flask API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        rate_limiter = get_rate_limiter()
        rate_limiter.shutdown()

    def test_check_and_consume_success(self):
        """Test successful check_and_consume request."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": 5,
            "window_duration_seconds": 60,
        }

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.data)
        self.assertTrue(response_data["allowed"])
        self.assertEqual(response_data["remaining_requests"], 4)
        self.assertEqual(response_data["status"], "processed")
        self.assertIn("reset_time_seconds", response_data)

    def test_check_and_consume_rate_limit_exceeded(self):
        """Test check_and_consume when rate limit is exceeded."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": 2,
            "window_duration_seconds": 60,
        }

        for i in range(2):
            response = self.client.post(
                "/api/check_and_consume",
                data=json.dumps(data),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            response_data = json.loads(response.data)
            self.assertTrue(response_data["allowed"])

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 429)  # Too Many Requests

        response_data = json.loads(response.data)
        self.assertFalse(response_data["allowed"])
        self.assertEqual(response_data["remaining_requests"], 0)
        self.assertEqual(response_data["status"], "processed")

    def test_check_and_consume_missing_fields(self):
        """Test check_and_consume with missing required fields."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
        }

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("Missing required field", response_data["error"])

    def test_check_and_consume_invalid_data_types(self):
        """Test check_and_consume with invalid data types."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": "invalid",
            "window_duration_seconds": 60,
        }

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("must be integers", response_data["error"])

    def test_check_and_consume_invalid_values(self):
        """Test check_and_consume with invalid values."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": -1,
            "window_duration_seconds": 60,
        }

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("must be positive", response_data["error"])

    def test_check_and_consume_empty_strings(self):
        """Test check_and_consume with empty string values."""
        data = {
            "tenant_id": "",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": 5,
            "window_duration_seconds": 60,
        }

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("cannot be empty", response_data["error"])

    def test_check_and_consume_non_json(self):
        """Test check_and_consume with non-JSON request."""
        response = self.client.post(
            "/api/check_and_consume", data="not json", content_type="text/plain"
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("Request must be JSON", response_data["error"])

    def test_get_status_success(self):
        """Test successful get_status request."""

        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": 5,
            "window_duration_seconds": 60,
        }

        for _ in range(2):
            self.client.post(
                "/api/check_and_consume",
                data=json.dumps(data),
                content_type="application/json",
            )

        response = self.client.get(
            "/api/status/test_tenant/test_client/api_call?max_requests=5&window_duration_seconds=60"
        )

        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.data)
        self.assertIn("rate_limit", response_data)
        self.assertIn("queue", response_data)

        rate_limit = response_data["rate_limit"]
        self.assertEqual(rate_limit["tenant_id"], "test_tenant")
        self.assertEqual(rate_limit["client_id"], "test_client")
        self.assertEqual(rate_limit["action_type"], "api_call")
        self.assertEqual(rate_limit["current_count"], 2)
        self.assertEqual(rate_limit["remaining_requests"], 3)

    def test_get_status_missing_query_params(self):
        """Test get_status with missing query parameters."""
        response = self.client.get("/api/status/test_tenant/test_client/api_call")

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("Query parameters", response_data["error"])

    def test_get_status_invalid_query_params(self):
        """Test get_status with invalid query parameters."""
        response = self.client.get(
            "/api/status/test_tenant/test_client/api_call?max_requests=invalid&window_duration_seconds=60"
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("must be integers", response_data["error"])

    def test_get_status_empty_path_params(self):
        """Test get_status with empty path parameters."""
        response = self.client.get(
            "/api/status/ /test_client/api_call?max_requests=5&window_duration_seconds=60"
        )

        self.assertEqual(response.status_code, 400)

        response_data = json.loads(response.data)
        self.assertIn("error", response_data)
        self.assertIn("cannot be empty", response_data["error"])

    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.data)
        self.assertEqual(response_data["status"], "healthy")
        self.assertEqual(response_data["service"], "distributed-rate-limiter")
        self.assertIn("timestamp", response_data)

    def test_concurrent_api_requests(self):
        """Test concurrent API requests for thread safety."""
        data = {
            "tenant_id": "test_tenant",
            "client_id": "test_client",
            "action_type": "api_call",
            "max_requests": 5,
            "window_duration_seconds": 60,
        }

        responses = []
        threads = []

        def make_request():
            response = self.client.post(
                "/api/check_and_consume",
                data=json.dumps(data),
                content_type="application/json",
            )
            responses.append(response)

        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        success_count = sum(1 for r in responses if r.status_code == 200)
        rate_limited_count = sum(1 for r in responses if r.status_code == 429)

        self.assertEqual(success_count, 5)
        self.assertEqual(rate_limited_count, 5)

        for response in responses:
            response_data = json.loads(response.data)
            if response.status_code == 200:
                self.assertTrue(response_data["allowed"])
                self.assertEqual(response_data["status"], "processed")
            else:
                self.assertFalse(response_data["allowed"])
                self.assertEqual(response_data["remaining_requests"], 0)

    def test_multi_tenant_api_isolation(self):
        """Test that API properly isolates different tenants."""
        tenant1_data = {
            "tenant_id": "tenant1",
            "client_id": "client1",
            "action_type": "api_call",
            "max_requests": 2,
            "window_duration_seconds": 60,
        }

        tenant2_data = {
            "tenant_id": "tenant2",
            "client_id": "client1",
            "action_type": "api_call",
            "max_requests": 2,
            "window_duration_seconds": 60,
        }

        for _ in range(2):
            response = self.client.post(
                "/api/check_and_consume",
                data=json.dumps(tenant1_data),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(tenant1_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)

        response = self.client.post(
            "/api/check_and_consume",
            data=json.dumps(tenant2_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.data)
        self.assertTrue(response_data["allowed"])
        self.assertEqual(response_data["remaining_requests"], 1)


if __name__ == "__main__":
    unittest.main()
