from __future__ import annotations

import asyncio
import json

import click

from healthy_agent import __version__


def _make_driver(name: str):
    if name == "anthropic":
        from healthy_agent.drivers.anthropic import AnthropicDriver
        return AnthropicDriver()
    if name == "openai":
        from healthy_agent.drivers.openai_compat import OpenAIDriver
        return OpenAIDriver()
    if name == "deepseek":
        from healthy_agent.drivers.openai_compat import DeepSeekDriver
        return DeepSeekDriver()
    if name == "zhipu":
        from healthy_agent.drivers.openai_compat import ZhipuDriver
        return ZhipuDriver()
    if name == "qwen":
        from healthy_agent.drivers.openai_compat import QwenDriver
        return QwenDriver()
    if name == "ollama":
        from healthy_agent.drivers.openai_compat import OllamaDriver
        return OllamaDriver()
    return None


@click.group()
@click.version_option(version=__version__, prog_name="healthy_agent")
def main():
    """Healthy Agent — CPU-scheduling-inspired OS for LLM agent workloads"""


@main.command()
@click.argument("task")
@click.option("--cores", "-c", default=4, help="Number of cores (concurrent capacity)")
@click.option("--driver", "-d", default="mock", help="LLM driver: mock, anthropic, openai, deepseek, zhipu, qwen, ollama")
@click.option("--verbose", "-v", is_flag=True, help="Show scheduling events")
def run(task: str, cores: int, driver: str, verbose: bool):
    """Submit a task and run until completion."""
    from healthy_agent.kernel.runtime import Kernel

    async def _run():
        kernel = Kernel(num_cores=cores)

        if verbose:
            def on_event(event_type, process):
                click.echo(f"  [{event_type}] pid={process.pid} type={process.task_type} pri={process.pcb.priority}")
            kernel._on_event = on_event

        async def simple_handler(process, k):
            drv = _make_driver(driver)
            if drv is None:
                return f"[mock] Would process: {task}"
            result = await drv.generate([{"role": "user", "content": task}])
            return result.data.get("text", "") if result.success else result.error

        if verbose:
            click.echo(f"Kernel: {cores} cores | Driver: {driver}")
            click.echo("---")

        pid = kernel.spawn("user_task", {"task": task}, handler=simple_handler)
        result = await kernel.exec(pid)

        click.echo(f"\n=== Result (pid={pid}) ===")
        click.echo(result if isinstance(result, str) else json.dumps(result, indent=2))
        if verbose:
            click.echo("\nProcess table:")
            for row in kernel.ps():
                click.echo(f"  {row}")

    asyncio.run(_run())


@main.command()
@click.option("--cores", "-c", default=4)
def ps(cores: int):
    """Show kernel process table (demo)."""
    from healthy_agent.kernel.runtime import Kernel

    Kernel(num_cores=cores)
    click.echo(f"Kernel: {cores} cores, 0 processes (idle)")
    click.echo("Use 'healthy_agent run' to submit tasks.")


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", "-p", default=8000, help="Bind port")
@click.option("--cores", "-c", default=4, help="Number of kernel cores")
@click.option("--driver", "-d", default="mock", help="LLM driver: mock, anthropic, deepseek, zhipu, ollama")
@click.option("--model", "-m", default=None, help="Model name (defaults per driver)")
def serve(host: str, port: int, cores: int, driver: str, model: str | None):
    """Start the HTTP server (Kernel runs persistently)."""
    import uvicorn
    from api import create_app
    app = create_app(num_cores=cores, driver_name=driver, model=model)
    click.echo(f"Healthy Agent server starting on {host}:{port}")
    click.echo(f"  Kernel: {cores} cores | Driver: {driver} | Model: {model or 'default'}")
    click.echo(f"  Docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")
