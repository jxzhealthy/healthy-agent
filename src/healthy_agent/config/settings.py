"""Configuration system core module - Settings and load_config implementation"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ==================== Nested Dataclasses ====================

@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class KernelConfig:
    """Kernel scheduling configuration"""
    num_cores: int = 4
    max_processes: int = 100
    max_spawn_rate: float = 100.0


@dataclass
class DriverConfig:
    """LLM driver configuration"""
    name: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    timeout: int = 60


@dataclass
class MemoryConfig:
    """Memory system configuration"""
    backend: str = "local"  # local/redis/mem0
    redis_url: str = "redis://localhost:6379"
    ttl: int = 3600


@dataclass
class PersistenceConfig:
    """Persistence configuration"""
    enabled: bool = True
    db_path: str = "./healthy_agent.db"


@dataclass
class ObservabilityConfig:
    """Observability configuration"""
    log_level: str = "INFO"
    log_format: str = "text"  # json/text
    metrics_enabled: bool = False


@dataclass
class AuthConfig:
    """Authentication configuration"""
    enabled: bool = False
    api_keys: list[str] = field(default_factory=list)
    jwt_secret: str = ""


@dataclass
class SkillsConfig:
    """Skills system configuration"""
    directories: list[str] = field(default_factory=lambda: ["./skills"])
    hot_reload: bool = True
    poll_interval: int = 5


@dataclass
class SandboxConfig:
    """Sandbox configuration"""
    enabled: bool = False
    timeout: int = 30
    max_memory_mb: int = 512


@dataclass
class CompressionConfig:
    """Context compression configuration"""
    enabled: bool = True
    max_tokens_threshold: int = 30000
    summary_model: str = ""  # empty = use the main driver model


@dataclass
class HeadroomConfig:
    """Headroom rule-based compression configuration"""
    enabled: bool = True
    compress_tool_outputs: bool = True
    compress_code: bool = True
    compress_json: bool = True
    min_content_length: int = 200
    target_ratio: float = 0.3


@dataclass
class ResilienceConfig:
    """Retry and circuit breaker configuration"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60


# ==================== Main Settings ====================

@dataclass
class Settings:
    """Unified configuration class - contains all configurable items"""
    server: ServerConfig = field(default_factory=ServerConfig)
    kernel: KernelConfig = field(default_factory=KernelConfig)
    driver: DriverConfig = field(default_factory=DriverConfig)
    fallback_driver: DriverConfig = field(default_factory=lambda: DriverConfig(name="fallback"))
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    headroom: HeadroomConfig = field(default_factory=HeadroomConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)


# ==================== Config Loading ====================

def _load_from_toml(path: Path) -> dict[str, Any]:
    """Load configuration from TOML file"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_from_yaml(path: Path) -> dict[str, Any]:
    """Load configuration from YAML file"""
    if not HAS_YAML:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to configuration
    
    Environment variable format: HEALTHY_AGENT_<SECTION>_<KEY>
    Example: HEALTHY_AGENT_DRIVER_NAME=anthropic
    """
    prefix = "HEALTHY_AGENT_"
    
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        
        # Parse env var name: HEALTHY_AGENT_DRIVER_NAME -> driver.name
        parts = env_key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        
        section, key = parts
        
        if section not in config_dict:
            config_dict[section] = {}
        
        # Type conversion
        config_dict[section][key] = _convert_type(env_value)
    
    return config_dict


def _convert_type(value: str) -> Any:
    """Convert string value to appropriate Python type"""
    # Boolean
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    
    # List (comma-separated)
    if "," in value:
        return [item.strip() for item in value.split(",")]
    
    return value


def _merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries"""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_configs(result[key], value)
        else:
            result[key] = value
    
    return result


def _dict_to_settings(config_dict: dict[str, Any]) -> Settings:
    """Convert configuration dictionary to Settings instance"""
    settings = Settings()
    
    section_mapping = {
        "server": ServerConfig,
        "kernel": KernelConfig,
        "driver": DriverConfig,
        "fallback_driver": DriverConfig,
        "memory": MemoryConfig,
        "persistence": PersistenceConfig,
        "observability": ObservabilityConfig,
        "auth": AuthConfig,
        "skills": SkillsConfig,
        "sandbox": SandboxConfig,
        "compression": CompressionConfig,
        "headroom": HeadroomConfig,
        "resilience": ResilienceConfig,
    }
    
    for section_name, section_class in section_mapping.items():
        if section_name in config_dict:
            section_data = config_dict[section_name]
            if isinstance(section_data, dict):
                # Filter out fields that don't exist in dataclass
                valid_fields = {f.name for f in section_class.__dataclass_fields__.values()}
                filtered_data = {k: v for k, v in section_data.items() if k in valid_fields}
                
                # Create new dataclass instance and merge into settings
                new_instance = section_class(**filtered_data)
                setattr(settings, section_name, new_instance)
    
    return settings


def load_config(path: str | Path | None = None) -> Settings:
    """Load configuration
    
    Search order:
    1. Provided path parameter
    2. Environment variable HEALTHY_AGENT_CONFIG
    3. ./healthy_agent.toml
    4. ./healthy_agent.yaml
    5. Default values
    
    Args:
        path: Configuration file path (optional)
    
    Returns:
        Settings instance
    """
    config_paths = []
    
    # 1. Provided path
    if path:
        config_paths.append(Path(path))
    
    # 2. Path specified by environment variable
    env_config_path = os.environ.get("HEALTHY_AGENT_CONFIG")
    if env_config_path:
        config_paths.append(Path(env_config_path))
    
    # 3-4. Default configuration files
    cwd = Path.cwd()
    default_toml = cwd / "healthy_agent.toml"
    default_yaml = cwd / "healthy_agent.yaml"
    
    if default_toml.exists():
        config_paths.append(default_toml)
    if default_yaml.exists():
        config_paths.append(default_yaml)
    
    # Load the first found configuration file
    config_dict: dict[str, Any] = {}
    for config_path in config_paths:
        if not config_path.exists():
            continue
        
        try:
            if config_path.suffix in (".toml",):
                config_dict = _load_from_toml(config_path)
                break
            elif config_path.suffix in (".yaml", ".yml"):
                config_dict = _load_from_yaml(config_path)
                break
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
            continue
    
    # Apply environment variable overrides
    config_dict = _apply_env_overrides(config_dict)
    
    # Convert to Settings instance
    return _dict_to_settings(config_dict)


# ==================== Module-level Singleton ====================

_settings: Settings | None = None


def _get_settings() -> Settings:
    """Lazy load singleton Settings"""
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


# Module-level singleton variable
settings = _get_settings()
