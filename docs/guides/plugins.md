# Plugins Guide

## Overview

Plugins extend agent functionality through lifecycle hooks and custom processing. They enable modular, reusable extensions without modifying core code.

## Plugin Base Class

All plugins inherit from the `Plugin` base class:

```python
from healthy_agent import Plugin

class MyPlugin(Plugin):
    name = "my_plugin"
    
    def on_startup(self, agent):
        """Called when agent starts"""
        print(f"{self.name} initialized")
    
    def on_shutdown(self, agent):
        """Called when agent shuts down"""
        print(f"{self.name} cleanup")
    
    def pre_generate(self, prompt, context):
        """Called before LLM generation"""
        # Modify prompt or context
        return prompt, context
    
    def post_generate(self, response):
        """Called after LLM generation"""
        # Process or modify response
        return response
```

### Lifecycle Hooks

- **on_startup**: Initialize resources
- **on_shutdown**: Cleanup resources
- **pre_generate**: Pre-process prompts
- **post_generate**: Post-process responses

## PluginManager

Manages plugin registration and lifecycle:

```python
from healthy_agent import PluginManager

manager = PluginManager()

# Register a plugin
manager.register(my_plugin_instance)

# Unregister a plugin
manager.unregister("plugin_name")

# Get all plugins
plugins = manager.list_plugins()

# Execute lifecycle hooks
manager.on_startup(agent)
manager.pre_generate(prompt, context)
```

## HeadroomPlugin

Rule-based compression plugin that reduces token usage by 60-95%:

```python
from healthy_agent.plugins import HeadroomPlugin

# Configure compression
plugin = HeadroomPlugin(
    target_ratio=0.3,  # Target 30% of original size
    strategies=["remove_whitespace", "compress_keys"]
)

# Automatic compression in pre_generate
compressed_prompt = plugin.pre_generate(long_prompt, context)
```

### Compression Strategies

- Remove unnecessary whitespace
- Compress JSON keys
- Truncate verbose descriptions
- Optimize repetitive patterns

## HeadroomFallbackPlugin

Provides fallback behavior when `headroom-ai` is not installed:

```python
from healthy_agent.plugins import HeadroomFallbackPlugin

# Automatically activates if headroom-ai missing
fallback = HeadroomFallbackPlugin()

# Graceful degradation
plugin.pre_generate(prompt, context)  # Returns original if unavailable
```

## Configuration

Configure plugins in your config file:

```toml
[headroom]
enabled = true
target_ratio = 0.3
strategies = ["remove_whitespace", "compress_keys", "truncate_descriptions"]
```

### Configuration Options

- **enabled**: Enable/disable plugin (boolean)
- **target_ratio**: Compression target (0.0-1.0)
- **strategies**: List of compression strategies

## Example Usage

```python
from healthy_agent import Agent, PluginManager
from healthy_agent.plugins import HeadroomPlugin

# Create plugin manager
manager = PluginManager()

# Add headroom plugin
headroom = HeadroomPlugin(target_ratio=0.3)
manager.register(headroom)

# Create agent with plugins
agent = Agent(plugin_manager=manager)

# Plugins automatically apply during generation
response = agent.generate("Analyze this code...")
```

## Custom Plugin Example

```python
class LoggingPlugin(Plugin):
    name = "logging_plugin"
    
    def pre_generate(self, prompt, context):
        print(f"Generating response for: {prompt[:50]}...")
        return prompt, context
    
    def post_generate(self, response):
        print(f"Generated {len(response)} characters")
        return response

# Register custom plugin
manager.register(LoggingPlugin())
```

Plugins provide a clean extension mechanism for adding cross-cutting concerns like logging, monitoring, compression, and security.
