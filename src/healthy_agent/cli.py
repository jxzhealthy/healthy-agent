from __future__ import annotations

import asyncio
import json

import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="healthy_agent")
def main():
    """Healthy Agent — CPU-scheduling-inspired OS for LLM agent workloads"""


@main.command()
@click.argument("task")
@click.option("--cores", "-c", default=4, help="Number of cores (concurrent capacity)")
@click.option("--driver", "-d", default="mock", help="LLM driver: mock, anthropic")
@click.option("--verbose", "-v", is_flag=True, help="Show scheduling events")
def run(task: str, cores: int, driver: str, verbose: bool):
    """Submit a task and run until completion."""
    from .kernel.runtime import Kernel

    async def _run():
        kernel = Kernel(num_cores=cores)

        if verbose:
            def on_event(event_type, process):
                click.echo(f"  [{event_type}] pid={process.pid} type={process.task_type} pri={process.pcb.priority}")
            kernel._on_event = on_event

        async def simple_handler(process, k):
            if driver == "anthropic":
                from .drivers.anthropic import AnthropicDriver
                drv = AnthropicDriver()
                result = await drv.generate([{"role": "user", "content": task}])
                return result.data.get("text", "") if result.success else result.error
            return f"[mock] Would process: {task}"

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
    from .kernel.runtime import Kernel

    Kernel(num_cores=cores)
    click.echo(f"Kernel: {cores} cores, 0 processes (idle)")
    click.echo("Use 'healthy_agent run' to submit tasks.")


if __name__ == "__main__":
    main()
