from flask import Blueprint, jsonify, request
from src.models.rate_limiter import DistributedRateLimiter, RequestStatus
import threading

# Global rate limiter instance (singleton pattern)
_rate_limiter = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter():
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = DistributedRateLimiter(
                    max_global_concurrent_requests=100, max_tenant_queue_size=50
                )
    return _rate_limiter


rate_limiter_bp = Blueprint("rate_limiter", __name__)


@rate_limiter_bp.route("/check_and_consume", methods=["POST"])
def check_and_consume():
    """
    Main rate limiting endpoint.

    Request Body:
    {
        "tenant_id": "org_a_123",
        "client_id": "user123",
        "action_type": "api_call",
        "max_requests": 10,
        "window_duration_seconds": 60
    }

    Response Body:
    {
        "allowed": true,
        "remaining_requests": 5,
        "reset_time_seconds": 1678886400,
        "status": "processed"  // "processed" or "queued" or "rejected"
    }
    """
    try:
        # Validate request data
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400

        data = request.get_json()

        # Validate required fields
        required_fields = [
            "tenant_id",
            "client_id",
            "action_type",
            "max_requests",
            "window_duration_seconds",
        ]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Validate data types and values
        tenant_id = str(data["tenant_id"])
        client_id = str(data["client_id"])
        action_type = str(data["action_type"])

        try:
            max_requests = int(data["max_requests"])
            window_duration_seconds = int(data["window_duration_seconds"])
        except (ValueError, TypeError):
            return (
                jsonify(
                    {
                        "error": "max_requests and window_duration_seconds must be integers"
                    }
                ),
                400,
            )

        if max_requests <= 0:
            return jsonify({"error": "max_requests must be positive"}), 400

        if window_duration_seconds <= 0:
            return jsonify({"error": "window_duration_seconds must be positive"}), 400

        # Validate string fields are not empty
        if not tenant_id.strip() or not client_id.strip() or not action_type.strip():
            return (
                jsonify(
                    {"error": "tenant_id, client_id, and action_type cannot be empty"}
                ),
                400,
            )

        # Get rate limiter and process request
        rate_limiter = get_rate_limiter()
        result = rate_limiter.check_and_consume(
            tenant_id=tenant_id,
            client_id=client_id,
            action_type=action_type,
            max_requests=max_requests,
            window_duration_seconds=window_duration_seconds,
        )

        # Prepare response
        response_data = {
            "allowed": result.allowed,
            "remaining_requests": result.remaining_requests,
            "status": result.status.value,
        }

        # Include reset_time_seconds only if available
        if result.reset_time_seconds is not None:
            response_data["reset_time_seconds"] = result.reset_time_seconds

        # Set appropriate HTTP status code
        if result.status == RequestStatus.REJECTED:
            return jsonify(response_data), 429  # Too Many Requests
        elif result.status == RequestStatus.QUEUED:
            return jsonify(response_data), 202  # Accepted (queued for processing)
        elif not result.allowed:
            return jsonify(response_data), 429  # Too Many Requests
        else:
            return jsonify(response_data), 200  # OK

    except Exception as e:
        # Log error in production
        print(f"Error in check_and_consume: {e}")
        return jsonify({"error": "Internal server error"}), 500


@rate_limiter_bp.route("/status/<tenant_id>/<client_id>/<action_type>", methods=["GET"])
def get_status(tenant_id, client_id, action_type):
    """
    Get current rate limit status for debugging.

    Query parameters:
    - max_requests: Maximum requests allowed (required)
    - window_duration_seconds: Window duration in seconds (required)

    Response:
    {
        "rate_limit": {
            "tenant_id": "org_a_123",
            "client_id": "user123",
            "action_type": "api_call",
            "current_count": 3,
            "max_requests": 10,
            "remaining_requests": 7,
            "window_duration_seconds": 60,
            "timestamps": [1678886340.123, 1678886350.456, 1678886360.789],
            "window_start": 1678886340.0,
            "current_time": 1678886400.0
        },
        "queue": {
            "tenant_id": "org_a_123",
            "queue_length": 2,
            "max_queue_size": 50,
            "in_flight_requests": 5,
            "global_in_flight": 25,
            "max_global_concurrent": 100
        }
    }
    """
    try:
        # Validate query parameters
        max_requests = request.args.get("max_requests")
        window_duration_seconds = request.args.get("window_duration_seconds")

        if not max_requests or not window_duration_seconds:
            return (
                jsonify(
                    {
                        "error": "Query parameters max_requests and window_duration_seconds are required"
                    }
                ),
                400,
            )

        try:
            max_requests = int(max_requests)
            window_duration_seconds = int(window_duration_seconds)
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "max_requests and window_duration_seconds must be integers"
                    }
                ),
                400,
            )

        if max_requests <= 0 or window_duration_seconds <= 0:
            return (
                jsonify(
                    {
                        "error": "max_requests and window_duration_seconds must be positive"
                    }
                ),
                400,
            )

        # Validate path parameters
        if not tenant_id.strip() or not client_id.strip() or not action_type.strip():
            return (
                jsonify(
                    {"error": "tenant_id, client_id, and action_type cannot be empty"}
                ),
                400,
            )

        # Get status from rate limiter
        rate_limiter = get_rate_limiter()
        status = rate_limiter.get_status(
            tenant_id=tenant_id,
            client_id=client_id,
            action_type=action_type,
            max_requests=max_requests,
            window_duration_seconds=window_duration_seconds,
        )

        return jsonify(status), 200

    except Exception as e:
        # Log error in production
        print(f"Error in get_status: {e}")
        return jsonify({"error": "Internal server error"}), 500


@rate_limiter_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    try:
        rate_limiter = get_rate_limiter()
        return (
            jsonify(
                {
                    "status": "healthy",
                    "service": "distributed-rate-limiter",
                    "timestamp": int(__import__("time").time()),
                }
            ),
            200,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": int(__import__("time").time()),
                }
            ),
            500,
        )


# Graceful shutdown handler
def shutdown_rate_limiter():
    """Shutdown the rate limiter gracefully."""
    global _rate_limiter
    if _rate_limiter:
        _rate_limiter.shutdown()
