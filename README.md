# Distributed Rate Limiter Service

A highly performant and scalable multi-tenant rate limiting service with advanced tenant-level load management.

## Features

- **Sliding Window Log Algorithm**: Precise rate limiting with sub-second accuracy
- **Multi-Tenant Support**: Complete tenant isolation with per-tenant configuration
- **Load Management**: Intelligent queuing and fairness across tenants
- **Dynamic Configuration**: Runtime configuration updates for different tenants, clients, and actions
- **Thread-Safe**: Robust concurrency handling for high-throughput scenarios
- **Graceful Shutdown**: Clean termination with proper resource cleanup

## Quick Start

### Prerequisites

- Python 3.11+
- Virtual environment (recommended)

### Installation

1. Clone or extract the project:
```bash
cd rate_limiter_service
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

### Running the Service

Start the development server:
```bash
python src/main.py
```

The service will be available at `http://localhost:5000`

### API Usage

#### Rate Limiting

Check and consume rate limit tokens:
```bash
curl -X POST http://localhost:5000/api/check_and_consume \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "org_a_123",
    "client_id": "user123",
    "action_type": "api_call",
    "max_requests": 10,
    "window_duration_seconds": 60
  }'
```

Response:
```json
{
  "allowed": true,
  "remaining_requests": 9,
  "reset_time_seconds": 1678886400,
  "status": "processed"
}
```

#### Status Check

Get current rate limit status:
```bash
curl "http://localhost:5000/api/status/org_a_123/user123/api_call?max_requests=10&window_duration_seconds=60"
```

#### Configuration Management

Set tenant-level action limits:
```bash
curl -X PUT http://localhost:5000/api/config/tenant/org_a_123/action/api_call \
  -H "Content-Type: application/json" \
  -d '{
    "max_requests": 100,
    "window_duration_seconds": 3600
  }'
```

Set client-specific limits:
```bash
curl -X PUT http://localhost:5000/api/config/tenant/org_a_123/client/vip_user/action/api_call \
  -H "Content-Type: application/json" \
  -d '{
    "max_requests": 1000,
    "window_duration_seconds": 3600
  }'
```

## Testing

Run the test suite:
```bash
python -m pytest tests/ -v
```

Run specific test categories:
```bash
# Unit tests only
python -m pytest tests/test_sliding_window.py tests/test_config.py -v

# Load manager tests
python -m pytest tests/test_load_manager.py -v

# API tests
python -m pytest tests/test_api_endpoints.py -v
```

## Architecture

The service consists of four main components:

1. **SlidingWindowLog**: Core rate limiting algorithm
2. **TenantLoadManager**: Global load management and queuing
3. **DistributedRateLimiter**: Orchestrates rate limiting and load management
4. **ConfigurationManager**: Dynamic configuration management

See `DESIGN.md` for detailed architecture documentation.

## Configuration

### Global Configuration

Set global load management parameters:
```bash
curl -X PUT http://localhost:5000/api/config/global \
  -H "Content-Type: application/json" \
  -d '{
    "max_global_concurrent_requests": 200,
    "max_tenant_queue_size": 100
  }'
```

### Tenant Configuration

The service supports hierarchical configuration:

1. **Global defaults**: Applied to all tenants
2. **Tenant action limits**: Per-action rate limits for a tenant
3. **Client-specific limits**: Override action limits for specific clients

Client-specific limits take precedence over action limits.

## Production Deployment

### Environment Variables

- `FLASK_ENV`: Set to `production` for production deployment
- `SECRET_KEY`: Set a secure secret key for Flask

### Scaling Considerations

For production deployment, consider:

1. **Load Balancing**: Deploy multiple instances behind a load balancer
2. **Persistent Storage**: Integrate with Redis for distributed state
3. **Monitoring**: Add metrics collection and alerting
4. **Configuration Management**: Use external configuration service

See the "Scalability Considerations" section in `DESIGN.md` for detailed scaling strategies.

## API Reference

### Rate Limiting Endpoints

- `POST /api/check_and_consume`: Check and consume rate limit tokens
- `GET /api/status/{tenant_id}/{client_id}/{action_type}`: Get rate limit status
- `GET /api/health`: Health check endpoint

### Configuration Endpoints

- `GET /api/config`: Get all configuration
- `PUT /api/config/global`: Set global configuration
- `GET /api/config/tenant/{tenant_id}`: Get tenant configuration
- `PUT /api/config/tenant/{tenant_id}/action/{action_type}`: Set action limit
- `DELETE /api/config/tenant/{tenant_id}/action/{action_type}`: Remove action limit
- `PUT /api/config/tenant/{tenant_id}/client/{client_id}/action/{action_type}`: Set client limit
- `DELETE /api/config/tenant/{tenant_id}/client/{client_id}/action/{action_type}`: Remove client limit

## License

