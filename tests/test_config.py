import unittest
import tempfile
import os
import json
from src.models.config import ConfigurationManager, RateLimitConfig, LoadManagerConfig, TenantConfig


class TestConfigurationManager(unittest.TestCase):
    """Tests for the ConfigurationManager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = ConfigurationManager()
    
    def test_rate_limit_config_validation(self):
        """Test RateLimitConfig validation."""
        # Valid config
        config = RateLimitConfig(max_requests=10, window_duration_seconds=60)
        self.assertEqual(config.max_requests, 10)
        self.assertEqual(config.window_duration_seconds, 60)
        
        # Invalid max_requests
        with self.assertRaises(ValueError):
            RateLimitConfig(max_requests=0, window_duration_seconds=60)
        
        with self.assertRaises(ValueError):
            RateLimitConfig(max_requests=-1, window_duration_seconds=60)
        
        # Invalid window_duration_seconds
        with self.assertRaises(ValueError):
            RateLimitConfig(max_requests=10, window_duration_seconds=0)
        
        with self.assertRaises(ValueError):
            RateLimitConfig(max_requests=10, window_duration_seconds=-1)
    
    def test_load_manager_config_validation(self):
        """Test LoadManagerConfig validation."""
        # Valid config
        config = LoadManagerConfig(max_global_concurrent_requests=100, max_tenant_queue_size=50)
        self.assertEqual(config.max_global_concurrent_requests, 100)
        self.assertEqual(config.max_tenant_queue_size, 50)
        
        # Invalid max_global_concurrent_requests
        with self.assertRaises(ValueError):
            LoadManagerConfig(max_global_concurrent_requests=0, max_tenant_queue_size=50)
        
        # Invalid max_tenant_queue_size
        with self.assertRaises(ValueError):
            LoadManagerConfig(max_global_concurrent_requests=100, max_tenant_queue_size=0)
    
    def test_get_tenant_config_creates_default(self):
        """Test that getting a non-existent tenant creates default config."""
        tenant_id = "new_tenant"
        config = self.config_manager.get_tenant_config(tenant_id)
        
        self.assertEqual(config.tenant_id, tenant_id)
        self.assertEqual(config.load_manager.max_global_concurrent_requests, 100)
        self.assertEqual(config.load_manager.max_tenant_queue_size, 50)
        self.assertEqual(len(config.action_limits), 0)
        self.assertEqual(len(config.client_limits), 0)
    
    def test_set_and_get_global_config(self):
        """Test setting and getting global configuration."""
        new_config = LoadManagerConfig(max_global_concurrent_requests=200, max_tenant_queue_size=100)
        self.config_manager.set_global_config(new_config)
        
        retrieved_config = self.config_manager.get_global_config()
        self.assertEqual(retrieved_config.max_global_concurrent_requests, 200)
        self.assertEqual(retrieved_config.max_tenant_queue_size, 100)
    
    def test_set_action_limit(self):
        """Test setting action-level rate limits."""
        tenant_id = "test_tenant"
        action_type = "api_call"
        rate_limit = RateLimitConfig(max_requests=10, window_duration_seconds=60)
        
        self.config_manager.set_action_limit(tenant_id, action_type, rate_limit)
        
        retrieved_config = self.config_manager.get_rate_limit_config(tenant_id, "any_client", action_type)
        self.assertEqual(retrieved_config.max_requests, 10)
        self.assertEqual(retrieved_config.window_duration_seconds, 60)
    
    def test_set_client_limit(self):
        """Test setting client-level rate limits."""
        tenant_id = "test_tenant"
        client_id = "test_client"
        action_type = "api_call"
        rate_limit = RateLimitConfig(max_requests=5, window_duration_seconds=30)
        
        self.config_manager.set_client_limit(tenant_id, client_id, action_type, rate_limit)
        
        retrieved_config = self.config_manager.get_rate_limit_config(tenant_id, client_id, action_type)
        self.assertEqual(retrieved_config.max_requests, 5)
        self.assertEqual(retrieved_config.window_duration_seconds, 30)
    
    def test_client_limit_overrides_action_limit(self):
        """Test that client-specific limits override action-level limits."""
        tenant_id = "test_tenant"
        client_id = "test_client"
        action_type = "api_call"
        
        # Set action-level limit
        action_limit = RateLimitConfig(max_requests=10, window_duration_seconds=60)
        self.config_manager.set_action_limit(tenant_id, action_type, action_limit)
        
        # Set client-level limit (should override)
        client_limit = RateLimitConfig(max_requests=5, window_duration_seconds=30)
        self.config_manager.set_client_limit(tenant_id, client_id, action_type, client_limit)
        
        # Client should get client-specific limit
        retrieved_config = self.config_manager.get_rate_limit_config(tenant_id, client_id, action_type)
        self.assertEqual(retrieved_config.max_requests, 5)
        self.assertEqual(retrieved_config.window_duration_seconds, 30)
        
        # Different client should get action-level limit
        other_client_config = self.config_manager.get_rate_limit_config(tenant_id, "other_client", action_type)
        self.assertEqual(other_client_config.max_requests, 10)
        self.assertEqual(other_client_config.window_duration_seconds, 60)
    
    def test_remove_action_limit(self):
        """Test removing action-level rate limits."""
        tenant_id = "test_tenant"
        action_type = "api_call"
        rate_limit = RateLimitConfig(max_requests=10, window_duration_seconds=60)
        
        # Set and verify
        self.config_manager.set_action_limit(tenant_id, action_type, rate_limit)
        config = self.config_manager.get_rate_limit_config(tenant_id, "any_client", action_type)
        self.assertIsNotNone(config)
        
        # Remove and verify
        self.config_manager.remove_action_limit(tenant_id, action_type)
        config = self.config_manager.get_rate_limit_config(tenant_id, "any_client", action_type)
        self.assertIsNone(config)
    
    def test_remove_client_limit(self):
        """Test removing client-level rate limits."""
        tenant_id = "test_tenant"
        client_id = "test_client"
        action_type = "api_call"
        rate_limit = RateLimitConfig(max_requests=5, window_duration_seconds=30)
        
        # Set and verify
        self.config_manager.set_client_limit(tenant_id, client_id, action_type, rate_limit)
        config = self.config_manager.get_rate_limit_config(tenant_id, client_id, action_type)
        self.assertIsNotNone(config)
        
        # Remove and verify
        self.config_manager.remove_client_limit(tenant_id, client_id, action_type)
        config = self.config_manager.get_rate_limit_config(tenant_id, client_id, action_type)
        self.assertIsNone(config)
    
    def test_save_and_load_from_file(self):
        """Test saving and loading configuration from file."""
        # Set up some configuration
        self.config_manager.set_global_config(
            LoadManagerConfig(max_global_concurrent_requests=200, max_tenant_queue_size=100)
        )
        
        tenant_id = "test_tenant"
        self.config_manager.set_action_limit(
            tenant_id, "api_call", RateLimitConfig(max_requests=10, window_duration_seconds=60)
        )
        self.config_manager.set_client_limit(
            tenant_id, "vip_client", "api_call", RateLimitConfig(max_requests=20, window_duration_seconds=60)
        )
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_file = f.name
        
        try:
            self.config_manager.save_to_file(temp_file)
            
            # Create new config manager and load
            new_config_manager = ConfigurationManager()
            new_config_manager.load_from_file(temp_file)
            
            # Verify global config
            global_config = new_config_manager.get_global_config()
            self.assertEqual(global_config.max_global_concurrent_requests, 200)
            self.assertEqual(global_config.max_tenant_queue_size, 100)
            
            # Verify action limit
            action_config = new_config_manager.get_rate_limit_config(tenant_id, "any_client", "api_call")
            self.assertEqual(action_config.max_requests, 10)
            self.assertEqual(action_config.window_duration_seconds, 60)
            
            # Verify client limit
            client_config = new_config_manager.get_rate_limit_config(tenant_id, "vip_client", "api_call")
            self.assertEqual(client_config.max_requests, 20)
            self.assertEqual(client_config.window_duration_seconds, 60)
            
        finally:
            os.unlink(temp_file)
    
    def test_load_from_invalid_file(self):
        """Test loading from invalid file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            temp_file = f.name
        
        try:
            with self.assertRaises(ValueError):
                self.config_manager.load_from_file(temp_file)
        finally:
            os.unlink(temp_file)
    
    def test_load_from_nonexistent_file(self):
        """Test loading from non-existent file."""
        with self.assertRaises(ValueError):
            self.config_manager.load_from_file("/nonexistent/file.json")
    
    def test_to_dict(self):
        """Test converting configuration to dictionary."""
        # Set up some configuration
        self.config_manager.set_global_config(
            LoadManagerConfig(max_global_concurrent_requests=150, max_tenant_queue_size=75)
        )
        
        tenant_id = "test_tenant"
        self.config_manager.set_action_limit(
            tenant_id, "login", RateLimitConfig(max_requests=5, window_duration_seconds=300)
        )
        self.config_manager.set_client_limit(
            tenant_id, "premium_client", "api_call", RateLimitConfig(max_requests=100, window_duration_seconds=60)
        )
        
        # Convert to dict
        config_dict = self.config_manager.to_dict()
        
        # Verify structure
        self.assertIn('global', config_dict)
        self.assertIn('tenants', config_dict)
        
        # Verify global config
        global_config = config_dict['global']
        self.assertEqual(global_config['max_global_concurrent_requests'], 150)
        self.assertEqual(global_config['max_tenant_queue_size'], 75)
        
        # Verify tenant config
        self.assertIn(tenant_id, config_dict['tenants'])
        tenant_config = config_dict['tenants'][tenant_id]
        
        self.assertIn('load_manager', tenant_config)
        self.assertIn('action_limits', tenant_config)
        self.assertIn('client_limits', tenant_config)
        
        # Verify action limits
        self.assertIn('login', tenant_config['action_limits'])
        login_limit = tenant_config['action_limits']['login']
        self.assertEqual(login_limit['max_requests'], 5)
        self.assertEqual(login_limit['window_duration_seconds'], 300)
        
        # Verify client limits
        self.assertIn('premium_client', tenant_config['client_limits'])
        client_limits = tenant_config['client_limits']['premium_client']
        self.assertIn('api_call', client_limits)
        api_call_limit = client_limits['api_call']
        self.assertEqual(api_call_limit['max_requests'], 100)
        self.assertEqual(api_call_limit['window_duration_seconds'], 60)
    
    def test_tenant_config_get_rate_limit_config(self):
        """Test TenantConfig.get_rate_limit_config method."""
        tenant_config = TenantConfig(tenant_id="test_tenant")
        
        # No limits set - should return None
        config = tenant_config.get_rate_limit_config("client1", "api_call")
        self.assertIsNone(config)
        
        # Set action limit
        action_limit = RateLimitConfig(max_requests=10, window_duration_seconds=60)
        tenant_config.action_limits["api_call"] = action_limit
        
        config = tenant_config.get_rate_limit_config("client1", "api_call")
        self.assertEqual(config.max_requests, 10)
        
        # Set client-specific limit (should override)
        client_limit = RateLimitConfig(max_requests=20, window_duration_seconds=30)
        tenant_config.client_limits["client1"] = {"api_call": client_limit}
        
        config = tenant_config.get_rate_limit_config("client1", "api_call")
        self.assertEqual(config.max_requests, 20)
        self.assertEqual(config.window_duration_seconds, 30)
        
        # Different client should still get action limit
        config = tenant_config.get_rate_limit_config("client2", "api_call")
        self.assertEqual(config.max_requests, 10)
        self.assertEqual(config.window_duration_seconds, 60)


if __name__ == '__main__':
    unittest.main()

