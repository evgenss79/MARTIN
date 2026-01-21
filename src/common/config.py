"""
Configuration loader for MARTIN.

Loads config from config/config.json, validates against schema,
and allows environment variable overrides.
"""

import json
import os
from pathlib import Path
from typing import Any

import jsonschema


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


class Config:
    """
    Configuration manager for MARTIN.
    
    Loads configuration from JSON file, validates against schema,
    and provides access to configuration values.
    """
    
    def __init__(self, config_path: str | None = None, schema_path: str | None = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to config.json (default: config/config.json)
            schema_path: Path to config.schema.json (default: config/config.schema.json)
        """
        self._base_dir = Path(__file__).parent.parent.parent
        self._config_path = Path(config_path) if config_path else self._base_dir / "config" / "config.json"
        self._schema_path = Path(schema_path) if schema_path else self._base_dir / "config" / "config.schema.json"
        self._config: dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        """Load and validate configuration."""
        # Load config file
        if not self._config_path.exists():
            raise ConfigError(f"Configuration file not found: {self._config_path}")
        
        try:
            with open(self._config_path, "r") as f:
                self._config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in config file: {e}")
        
        # Load schema and validate
        if self._schema_path.exists():
            try:
                with open(self._schema_path, "r") as f:
                    schema = json.load(f)
                jsonschema.validate(self._config, schema)
            except jsonschema.ValidationError as e:
                raise ConfigError(f"Configuration validation failed: {e.message}")
            except json.JSONDecodeError as e:
                raise ConfigError(f"Invalid JSON in schema file: {e}")
        
        # Apply environment variable overrides
        self._apply_env_overrides()
    
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        # LOG_LEVEL override
        if log_level := os.environ.get("LOG_LEVEL"):
            self._config["app"]["log_level"] = log_level
        
        # TIMEZONE override
        if timezone := os.environ.get("TIMEZONE"):
            self._config["app"]["timezone"] = timezone
        
        # EXECUTION_MODE override
        if exec_mode := os.environ.get("EXECUTION_MODE"):
            self._config["execution"]["mode"] = exec_mode
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-separated path.
        
        Args:
            path: Dot-separated path (e.g., "app.timezone")
            default: Default value if path not found
            
        Returns:
            Configuration value or default
        """
        keys = path.split(".")
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def __getitem__(self, path: str) -> Any:
        """Get configuration value by path, raises KeyError if not found."""
        value = self.get(path)
        if value is None:
            raise KeyError(f"Configuration key not found: {path}")
        return value
    
    @property
    def app(self) -> dict[str, Any]:
        """Get app configuration section."""
        return self._config.get("app", {})
    
    @property
    def trading(self) -> dict[str, Any]:
        """Get trading configuration section."""
        return self._config.get("trading", {})
    
    @property
    def day_night(self) -> dict[str, Any]:
        """Get day/night configuration section."""
        return self._config.get("day_night", {})
    
    @property
    def ta(self) -> dict[str, Any]:
        """Get TA configuration section."""
        return self._config.get("ta", {})
    
    @property
    def apis(self) -> dict[str, Any]:
        """Get APIs configuration section."""
        return self._config.get("apis", {})
    
    @property
    def telegram(self) -> dict[str, Any]:
        """Get Telegram configuration section."""
        return self._config.get("telegram", {})
    
    @property
    def storage(self) -> dict[str, Any]:
        """Get storage configuration section."""
        return self._config.get("storage", {})
    
    @property
    def risk(self) -> dict[str, Any]:
        """Get risk configuration section."""
        return self._config.get("risk", {})
    
    @property
    def execution(self) -> dict[str, Any]:
        """Get execution configuration section."""
        return self._config.get("execution", {})
    
    @property
    def rolling_quantile(self) -> dict[str, Any]:
        """Get rolling quantile configuration section."""
        return self._config.get("rolling_quantile", {})
    
    def to_dict(self) -> dict[str, Any]:
        """Return the full configuration as a dictionary."""
        return self._config.copy()


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    Returns:
        Config: The configuration instance
        
    Raises:
        ConfigError: If configuration has not been initialized
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def init_config(config_path: str | None = None, schema_path: str | None = None) -> Config:
    """
    Initialize the global configuration.
    
    Args:
        config_path: Path to config.json
        schema_path: Path to config.schema.json
        
    Returns:
        Config: The initialized configuration instance
    """
    global _config
    _config = Config(config_path, schema_path)
    return _config
