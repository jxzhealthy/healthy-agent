"""Sandbox executor for running code safely."""

import asyncio
import os
import sys
import resource
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class SandboxResult:
    """Result from sandbox execution."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    error: Optional[str] = None


class Sandbox:
    """
    Secure sandbox for executing code.
    
    Provides isolated execution environment with:
    - Timeout control
    - Memory limits (Unix only)
    - Command whitelisting for shell commands
    - Environment variable filtering
    """
    
    def __init__(
        self,
        timeout: int | None = None,
        max_memory_mb: int | None = None,
        allowed_commands: Optional[List[str]] = None
    ):
        if timeout is None or max_memory_mb is None:
            from healthy_agent.config.settings import settings
            timeout = timeout if timeout is not None else settings.sandbox.timeout
            max_memory_mb = max_memory_mb if max_memory_mb is not None else settings.sandbox.max_memory_mb
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allowed_commands = allowed_commands
    
    def _filter_env(self) -> dict:
        """
        Filter environment variables to remove sensitive data.
        
        Only keeps PATH, HOME, LANG and removes all *_KEY, *_SECRET, *_TOKEN vars.
        """
        safe_vars = {'PATH', 'HOME', 'LANG'}
        filtered = {}
        
        for key, value in os.environ.items():
            # Keep only whitelisted vars
            if key in safe_vars:
                filtered[key] = value
            # Remove sensitive vars
            elif any(key.endswith(suffix) for suffix in ['_KEY', '_SECRET', '_TOKEN']):
                continue
            # Optionally keep other non-sensitive vars
            elif not any(c in key for c in ['KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'CREDENTIAL']):
                filtered[key] = value
        
        return filtered
    
    def _set_memory_limit(self):
        """Set memory limit using resource module (Unix only)."""
        if sys.platform != 'win32':
            try:
                limit_bytes = self.max_memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
            except (ValueError, resource.error):
                # Ignore if setting limit fails
                pass
    
    async def run_python(self, code: str) -> SandboxResult:
        """
        Execute Python code in a subprocess.
        
        Args:
            code: Python code to execute
        
        Returns:
            SandboxResult with stdout, stderr, exit_code, etc.
        """
        try:
            # Write code to a temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            try:
                # Prepare environment
                env = self._filter_env()
                
                # Run python subprocess
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    temp_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    preexec_fn=self._set_memory_limit if sys.platform != 'win32' else None
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.timeout
                    )
                    timed_out = False
                except asyncio.TimeoutError:
                    # Kill the process on timeout
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    stdout, stderr = b'', b'Timeout exceeded'
                    timed_out = True
                
                return SandboxResult(
                    stdout=stdout.decode('utf-8', errors='replace'),
                    stderr=stderr.decode('utf-8', errors='replace'),
                    exit_code=process.returncode if not timed_out else -1,
                    timed_out=timed_out
                )
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
        
        except Exception as e:
            return SandboxResult(
                stdout='',
                stderr='',
                exit_code=-1,
                error=str(e)
            )
    
    async def run_shell(self, command: str) -> SandboxResult:
        """
        Execute shell command in a subprocess.
        
        Args:
            command: Shell command to execute
        
        Returns:
            SandboxResult with stdout, stderr, exit_code, etc.
        """
        try:
            # Check command whitelist if configured
            if self.allowed_commands:
                # Extract the base command (first word)
                base_cmd = command.split()[0] if command.split() else ''
                if base_cmd not in self.allowed_commands:
                    return SandboxResult(
                        stdout='',
                        stderr='',
                        exit_code=-1,
                        error=f"Command '{base_cmd}' is not allowed"
                    )
            
            # Prepare environment
            env = self._filter_env()
            
            # Run shell command
            process = await asyncio.create_subprocess_exec(
                '/bin/sh',
                '-c',
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                preexec_fn=self._set_memory_limit if sys.platform != 'win32' else None
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
                timed_out = False
            except asyncio.TimeoutError:
                # Kill the process on timeout
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                stdout, stderr = b'', b'Timeout exceeded'
                timed_out = True
            
            return SandboxResult(
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                exit_code=process.returncode if not timed_out else -1,
                timed_out=timed_out
            )
        
        except Exception as e:
            return SandboxResult(
                stdout='',
                stderr='',
                exit_code=-1,
                error=str(e)
            )
    
    async def run_code(self, language: str, code: str) -> SandboxResult:
        """
        Execute code in specified language.
        
        Args:
            language: Programming language ('python', 'shell')
            code: Code to execute
        
        Returns:
            SandboxResult with execution results
        """
        lang_lower = language.lower()
        
        if lang_lower == 'python':
            return await self.run_python(code)
        elif lang_lower == 'shell':
            return await self.run_shell(code)
        else:
            return SandboxResult(
                stdout='',
                stderr='',
                exit_code=-1,
                error=f"Unsupported language: {language}"
            )
