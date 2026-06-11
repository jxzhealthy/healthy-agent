# Skills Guide

## Overview

Skills are LLM-driven capabilities that extend agent functionality through natural language prompts. Unlike tools, skills require LLM interpretation and can handle complex, contextual tasks.

## SkillRegistry

The `SkillRegistry` manages skill registration, discovery, and hot reloading:

```python
from healthy_agent import SkillRegistry

registry = SkillRegistry()

# Register a skill
registry.register("code_review", skill_instance)

# Discover skills
skills = registry.list_skills()

# Hot reload skills from directory
registry.reload()
```

### Key Features

- **Registration**: Add skills programmatically
- **Discovery**: Auto-discover skills from directories
- **Hot Reload**: Update skills without restarting

## Tool vs Skill

| Feature | Tool | Skill |
|---------|------|-------|
| LLM Required | No | Yes |
| Execution | Direct function call | LLM-interpreted prompt |
| Use Case | Simple operations | Complex reasoning |
| Example | File read/write | Code analysis |

Tools are deterministic and fast. Skills are flexible and context-aware.

## Built-in Tools

### file_tools.py

File manipulation utilities:

```python
from healthy_agent.tools import file_tools

# Read file content
content = file_tools.read("path/to/file.txt")

# Write to file
file_tools.write("path/to/file.txt", "content")

# List directory
files = file_tools.list_dir("path/to/dir")

# Search files
results = file_tools.search("pattern", "path/to/dir")
```

### shell_tools.py

Shell command execution:

```python
from healthy_agent.tools import shell_tools

# Execute command
output = shell_tools.exec("ls -la")

# Run in background
process = shell_tools.background("long_running_command")
```

## Custom Skills

Create custom skills using Markdown files (`.md`):

```markdown
# code_review.md

You are a code review expert. Analyze the provided code for:
- Best practices
- Potential bugs
- Performance issues
- Security concerns

Provide actionable feedback with specific examples.
```

Load custom skills:

```python
registry.load_directory("path/to/skills")
```

The `load_directory` method automatically discovers and loads all `.md` files as skills.

## Example Usage

```python
from healthy_agent import Agent, SkillRegistry

# Initialize registry
registry = SkillRegistry()
registry.load_directory("./skills")

# Create agent with skills
agent = Agent(skills=registry)

# Use a skill
result = agent.execute("Review this code", skill="code_review")
```

Skills enable agents to perform sophisticated tasks by combining LLM reasoning with structured prompts.
