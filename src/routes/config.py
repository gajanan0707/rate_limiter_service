from flask import Blueprint, jsonify, request
from src.models.config import ConfigurationManager, RateLimitConfig, LoadManagerConfig
import threading

_config_manager = None
_config_manager_lock = threading.Lock()

def get_config_manager():
    """Get or create the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        with _config_manager_lock:
            if _config_manager is None:
                _config_manager = ConfigurationManager()
    return _config_manager

config_bp = Blueprint('config', __name__)

@config_bp.route('/config', methods=['GET'])
def get_all_config():
    """Get all configuration."""
    try:
        config_manager = get_config_manager()
        return jsonify(config_manager.to_dict()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/global', methods=['GET'])
def get_global_config():
    """Get global load manager configuration."""
    try:
        config_manager = get_config_manager()
        global_config = config_manager.get_global_config()
        return jsonify({
            "max_global_concurrent_requests": global_config.max_global_concurrent_requests,
            "max_tenant_queue_size": global_config.max_tenant_queue_size
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/global', methods=['PUT'])
def set_global_config():
    """
    Set global load manager configuration.
    
    Request Body:
    {
        "max_global_concurrent_requests": 100,
        "max_tenant_queue_size": 50
    }
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json()
        
        if 'max_global_concurrent_requests' not in data or 'max_tenant_queue_size' not in data:
            return jsonify({
                "error": "Both max_global_concurrent_requests and max_tenant_queue_size are required"
            }), 400
        
        try:
            max_global_concurrent = int(data['max_global_concurrent_requests'])
            max_tenant_queue_size = int(data['max_tenant_queue_size'])
        except (ValueError, TypeError):
            return jsonify({
                "error": "max_global_concurrent_requests and max_tenant_queue_size must be integers"
            }), 400
        
        config_manager = get_config_manager()
        global_config = LoadManagerConfig(
            max_global_concurrent_requests=max_global_concurrent,
            max_tenant_queue_size=max_tenant_queue_size
        )
        config_manager.set_global_config(global_config)
        
        return jsonify({"message": "Global configuration updated successfully"}), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/tenant/<tenant_id>', methods=['GET'])
def get_tenant_config(tenant_id):
    """Get configuration for a specific tenant."""
    try:
        config_manager = get_config_manager()
        tenant_config = config_manager.get_tenant_config(tenant_id)
        
        return jsonify({
            "tenant_id": tenant_config.tenant_id,
            "load_manager": {
                "max_global_concurrent_requests": tenant_config.load_manager.max_global_concurrent_requests,
                "max_tenant_queue_size": tenant_config.load_manager.max_tenant_queue_size
            },
            "action_limits": {
                action_type: {
                    "max_requests": config.max_requests,
                    "window_duration_seconds": config.window_duration_seconds
                }
                for action_type, config in tenant_config.action_limits.items()
            },
            "client_limits": {
                client_id: {
                    action_type: {
                        "max_requests": config.max_requests,
                        "window_duration_seconds": config.window_duration_seconds
                    }
                    for action_type, config in client_actions.items()
                }
                for client_id, client_actions in tenant_config.client_limits.items()
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/tenant/<tenant_id>/action/<action_type>', methods=['PUT'])
def set_action_limit(tenant_id, action_type):
    """
    Set rate limit for a specific action type within a tenant.
    
    Request Body:
    {
        "max_requests": 10,
        "window_duration_seconds": 60
    }
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json()
        
        # Validate required fields
        if 'max_requests' not in data or 'window_duration_seconds' not in data:
            return jsonify({
                "error": "Both max_requests and window_duration_seconds are required"
            }), 400
        
        try:
            max_requests = int(data['max_requests'])
            window_duration_seconds = int(data['window_duration_seconds'])
        except (ValueError, TypeError):
            return jsonify({
                "error": "max_requests and window_duration_seconds must be integers"
            }), 400
        
        config_manager = get_config_manager()
        rate_limit_config = RateLimitConfig(
            max_requests=max_requests,
            window_duration_seconds=window_duration_seconds
        )
        config_manager.set_action_limit(tenant_id, action_type, rate_limit_config)
        
        return jsonify({
            "message": f"Action limit for {action_type} in tenant {tenant_id} updated successfully"
        }), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/tenant/<tenant_id>/action/<action_type>', methods=['DELETE'])
def remove_action_limit(tenant_id, action_type):
    """Remove rate limit for a specific action type within a tenant."""
    try:
        config_manager = get_config_manager()
        config_manager.remove_action_limit(tenant_id, action_type)
        
        return jsonify({
            "message": f"Action limit for {action_type} in tenant {tenant_id} removed successfully"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/tenant/<tenant_id>/client/<client_id>/action/<action_type>', methods=['PUT'])
def set_client_limit(tenant_id, client_id, action_type):
    """
    Set rate limit for a specific client and action type within a tenant.
    
    Request Body:
    {
        "max_requests": 5,
        "window_duration_seconds": 60
    }
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json()
        
        if 'max_requests' not in data or 'window_duration_seconds' not in data:
            return jsonify({
                "error": "Both max_requests and window_duration_seconds are required"
            }), 400
        
        try:
            max_requests = int(data['max_requests'])
            window_duration_seconds = int(data['window_duration_seconds'])
        except (ValueError, TypeError):
            return jsonify({
                "error": "max_requests and window_duration_seconds must be integers"
            }), 400
        
        config_manager = get_config_manager()
        rate_limit_config = RateLimitConfig(
            max_requests=max_requests,
            window_duration_seconds=window_duration_seconds
        )
        config_manager.set_client_limit(tenant_id, client_id, action_type, rate_limit_config)
        
        return jsonify({
            "message": f"Client limit for {client_id}/{action_type} in tenant {tenant_id} updated successfully"
        }), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/tenant/<tenant_id>/client/<client_id>/action/<action_type>', methods=['DELETE'])
def remove_client_limit(tenant_id, client_id, action_type):
    """Remove rate limit for a specific client and action type within a tenant."""
    try:
        config_manager = get_config_manager()
        config_manager.remove_client_limit(tenant_id, client_id, action_type)
        
        return jsonify({
            "message": f"Client limit for {client_id}/{action_type} in tenant {tenant_id} removed successfully"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/load', methods=['POST'])
def load_config_from_file():
    """
    Load configuration from a file.
    
    Request Body:
    {
        "file_path": "/path/to/config.json"
    }
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json()
        
        if 'file_path' not in data:
            return jsonify({"error": "file_path is required"}), 400
        
        file_path = str(data['file_path'])
        
        config_manager = get_config_manager()
        config_manager.load_from_file(file_path)
        
        return jsonify({"message": f"Configuration loaded from {file_path} successfully"}), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@config_bp.route('/config/save', methods=['POST'])
def save_config_to_file():
    """
    Save current configuration to a file.
    
    Request Body:
    {
        "file_path": "/path/to/config.json"
    }
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json()
        
        if 'file_path' not in data:
            return jsonify({"error": "file_path is required"}), 400
        
        file_path = str(data['file_path'])
        
        config_manager = get_config_manager()
        config_manager.save_to_file(file_path)
        
        return jsonify({"message": f"Configuration saved to {file_path} successfully"}), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

