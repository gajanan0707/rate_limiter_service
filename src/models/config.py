import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
import json
import os


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting rules."""

    max_requests: int
    window_duration_seconds: int

    def __post_init__(self):
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.window_duration_seconds <= 0:
            raise ValueError("window_duration_seconds must be positive")


@dataclass
class LoadManagerConfig:
    """Configuration for load management."""

    max_global_concurrent_requests: int = 100
    max_tenant_queue_size: int = 50

    def __post_init__(self):
        if self.max_global_concurrent_requests <= 0:
            raise ValueError("max_global_concurrent_requests must be positive")
        if self.max_tenant_queue_size <= 0:
            raise ValueError("max_tenant_queue_size must be positive")


@dataclass
class TenantConfig:
    """Configuration for a specific tenant."""

    tenant_id: str
    load_manager: LoadManagerConfig = field(default_factory=LoadManagerConfig)
    # Per-action-type rate limits
    action_limits: Dict[str, RateLimitConfig] = field(default_factory=dict)
    # Per-client-id rate limits (overrides action limits)
    client_limits: Dict[str, Dict[str, RateLimitConfig]] = field(default_factory=dict)

    def get_rate_limit_config(
        self, client_id: str, action_type: str
    ) -> Optional[RateLimitConfig]:
        """Get rate limit configuration for a specific client and action."""
        # Check client-specific limits first
        if (
            client_id in self.client_limits
            and action_type in self.client_limits[client_id]
        ):
            return self.client_limits[client_id][action_type]

        # Fall back to action-type limits
        if action_type in self.action_limits:
            return self.action_limits[action_type]

        return None


class ConfigurationManager:
    """Manages dynamic configuration for the rate limiter service."""

    def __init__(self, config_file_path: Optional[str] = None):
        self.config_file_path = config_file_path
        self._tenant_configs: Dict[str, TenantConfig] = {}
        self._global_config = LoadManagerConfig()
        self._lock = threading.RLock()

        # Load configuration from file if provided
        if config_file_path and os.path.exists(config_file_path):
            self.load_from_file(config_file_path)

    def get_tenant_config(self, tenant_id: str) -> TenantConfig:
        """Get configuration for a specific tenant."""
        with self._lock:
            if tenant_id not in self._tenant_configs:
                # Create default configuration for new tenant
                self._tenant_configs[tenant_id] = TenantConfig(
                    tenant_id=tenant_id, load_manager=LoadManagerConfig()
                )
            return self._tenant_configs[tenant_id]

    def set_tenant_config(self, tenant_config: TenantConfig):
        """Set configuration for a specific tenant."""
        with self._lock:
            self._tenant_configs[tenant_config.tenant_id] = tenant_config

    def get_global_config(self) -> LoadManagerConfig:
        """Get global load manager configuration."""
        with self._lock:
            return self._global_config

    def set_global_config(self, config: LoadManagerConfig):
        """Set global load manager configuration."""
        with self._lock:
            self._global_config = config

    def get_rate_limit_config(
        self, tenant_id: str, client_id: str, action_type: str
    ) -> Optional[RateLimitConfig]:
        """Get rate limit configuration for a specific tenant, client, and action."""
        tenant_config = self.get_tenant_config(tenant_id)
        return tenant_config.get_rate_limit_config(client_id, action_type)

    def set_action_limit(
        self, tenant_id: str, action_type: str, config: RateLimitConfig
    ):
        """Set rate limit for a specific action type within a tenant."""
        with self._lock:
            tenant_config = self.get_tenant_config(tenant_id)
            tenant_config.action_limits[action_type] = config

    def set_client_limit(
        self, tenant_id: str, client_id: str, action_type: str, config: RateLimitConfig
    ):
        """Set rate limit for a specific client and action type within a tenant."""
        with self._lock:
            tenant_config = self.get_tenant_config(tenant_id)
            if client_id not in tenant_config.client_limits:
                tenant_config.client_limits[client_id] = {}
            tenant_config.client_limits[client_id][action_type] = config

    def remove_action_limit(self, tenant_id: str, action_type: str):
        """Remove rate limit for a specific action type within a tenant."""
        with self._lock:
            tenant_config = self.get_tenant_config(tenant_id)
            tenant_config.action_limits.pop(action_type, None)

    def remove_client_limit(self, tenant_id: str, client_id: str, action_type: str):
        """Remove rate limit for a specific client and action type within a tenant."""
        with self._lock:
            tenant_config = self.get_tenant_config(tenant_id)
            if client_id in tenant_config.client_limits:
                tenant_config.client_limits[client_id].pop(action_type, None)
                if not tenant_config.client_limits[client_id]:
                    del tenant_config.client_limits[client_id]

    def load_from_file(self, file_path: str):
        """Load configuration from a JSON file."""
        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            with self._lock:
                # Load global configuration
                if "global" in data:
                    global_data = data["global"]
                    self._global_config = LoadManagerConfig(
                        max_global_concurrent_requests=global_data.get(
                            "max_global_concurrent_requests", 100
                        ),
                        max_tenant_queue_size=global_data.get(
                            "max_tenant_queue_size", 50
                        ),
                    )

                # Load tenant configurations
                if "tenants" in data:
                    for tenant_id, tenant_data in data["tenants"].items():
                        tenant_config = TenantConfig(tenant_id=tenant_id)

                        # Load tenant load manager config
                        if "load_manager" in tenant_data:
                            lm_data = tenant_data["load_manager"]
                            tenant_config.load_manager = LoadManagerConfig(
                                max_global_concurrent_requests=lm_data.get(
                                    "max_global_concurrent_requests", 100
                                ),
                                max_tenant_queue_size=lm_data.get(
                                    "max_tenant_queue_size", 50
                                ),
                            )

                        # Load action limits
                        if "action_limits" in tenant_data:
                            for action_type, limit_data in tenant_data[
                                "action_limits"
                            ].items():
                                tenant_config.action_limits[action_type] = (
                                    RateLimitConfig(
                                        max_requests=limit_data["max_requests"],
                                        window_duration_seconds=limit_data[
                                            "window_duration_seconds"
                                        ],
                                    )
                                )

                        # Load client limits
                        if "client_limits" in tenant_data:
                            for client_id, client_data in tenant_data[
                                "client_limits"
                            ].items():
                                tenant_config.client_limits[client_id] = {}
                                for action_type, limit_data in client_data.items():
                                    tenant_config.client_limits[client_id][
                                        action_type
                                    ] = RateLimitConfig(
                                        max_requests=limit_data["max_requests"],
                                        window_duration_seconds=limit_data[
                                            "window_duration_seconds"
                                        ],
                                    )

                        self._tenant_configs[tenant_id] = tenant_config

        except Exception as e:
            raise ValueError(f"Failed to load configuration from {file_path}: {e}")

    def save_to_file(self, file_path: str):
        """Save current configuration to a JSON file."""
        try:
            with self._lock:
                data = {
                    "global": {
                        "max_global_concurrent_requests": self._global_config.max_global_concurrent_requests,
                        "max_tenant_queue_size": self._global_config.max_tenant_queue_size,
                    },
                    "tenants": {},
                }

                for tenant_id, tenant_config in self._tenant_configs.items():
                    tenant_data = {
                        "load_manager": {
                            "max_global_concurrent_requests": tenant_config.load_manager.max_global_concurrent_requests,
                            "max_tenant_queue_size": tenant_config.load_manager.max_tenant_queue_size,
                        },
                        "action_limits": {},
                        "client_limits": {},
                    }

                    # Save action limits
                    for action_type, config in tenant_config.action_limits.items():
                        tenant_data["action_limits"][action_type] = {
                            "max_requests": config.max_requests,
                            "window_duration_seconds": config.window_duration_seconds,
                        }

                    # Save client limits
                    for (
                        client_id,
                        client_actions,
                    ) in tenant_config.client_limits.items():
                        tenant_data["client_limits"][client_id] = {}
                        for action_type, config in client_actions.items():
                            tenant_data["client_limits"][client_id][action_type] = {
                                "max_requests": config.max_requests,
                                "window_duration_seconds": config.window_duration_seconds,
                            }

                    data["tenants"][tenant_id] = tenant_data

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            raise ValueError(f"Failed to save configuration to {file_path}: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary format."""
        with self._lock:
            result = {
                "global": {
                    "max_global_concurrent_requests": self._global_config.max_global_concurrent_requests,
                    "max_tenant_queue_size": self._global_config.max_tenant_queue_size,
                },
                "tenants": {},
            }

            for tenant_id, tenant_config in self._tenant_configs.items():
                result["tenants"][tenant_id] = {
                    "load_manager": {
                        "max_global_concurrent_requests": tenant_config.load_manager.max_global_concurrent_requests,
                        "max_tenant_queue_size": tenant_config.load_manager.max_tenant_queue_size,
                    },
                    "action_limits": {
                        action_type: {
                            "max_requests": config.max_requests,
                            "window_duration_seconds": config.window_duration_seconds,
                        }
                        for action_type, config in tenant_config.action_limits.items()
                    },
                    "client_limits": {
                        client_id: {
                            action_type: {
                                "max_requests": config.max_requests,
                                "window_duration_seconds": config.window_duration_seconds,
                            }
                            for action_type, config in client_actions.items()
                        }
                        for client_id, client_actions in tenant_config.client_limits.items()
                    },
                }

            return result
