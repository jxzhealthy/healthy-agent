from __future__ import annotations

import asyncio
import json

import click
from dotenv import load_dotenv

from healthy_agent import __version__

load_dotenv()


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
@click.option("--driver", "-d", default="mock", help="LLM driver")
@click.option("--model", "-m", default=None, help="Model name")
@click.option("--system", "-s", default=None, help="System prompt")
def chat(driver: str, model: str | None, system: str | None):
    """Interactive chat mode (terminal REPL)."""

    async def _chat():
        drv = _make_driver(driver)
        if not drv:
            click.echo("Driver 'mock' does not support chat. Use --driver anthropic/deepseek/etc.")
            return

        sys_prompt = system or "You are a helpful assistant."
        messages: list[dict] = []
        click.echo(f"Healthy Agent Chat | Driver: {driver} | Model: {model or 'default'}")
        click.echo("Type 'exit' or Ctrl+C to quit. Type '/clear' to reset.\n")

        while True:
            try:
                user_input = click.prompt(click.style("You", fg="cyan"), prompt_suffix="> ")
            except (EOFError, click.Abort):
                click.echo("\nBye!")
                break

            if not user_input.strip():
                continue
            if user_input.strip().lower() in ("exit", "quit", "/exit"):
                click.echo("Bye!")
                break
            if user_input.strip() == "/clear":
                messages.clear()
                click.echo("(conversation cleared)")
                continue

            messages.append({"role": "user", "content": user_input})

            try:
                chunks = []
                click.echo(click.style("Assistant", fg="green") + "> ", nl=False)
                async for chunk in drv.stream(messages, system=sys_prompt):
                    click.echo(chunk, nl=False)
                    chunks.append(chunk)
                click.echo()  # newline after stream
                full_response = "".join(chunks)
                messages.append({"role": "assistant", "content": full_response})
            except Exception:
                # Fallback to non-streaming
                result = await drv.generate(messages, system=sys_prompt)
                if result.success:
                    text = result.data.get("text", "")
                    click.echo(click.style("Assistant", fg="green") + f"> {text}")
                    messages.append({"role": "assistant", "content": text})
                else:
                    click.echo(click.style(f"Error: {result.error}", fg="red"))

    asyncio.run(_chat())


@main.command()
@click.option("--cores", "-c", default=4)
def ps(cores: int):
    """Show kernel process table (demo)."""
    from healthy_agent.kernel.runtime import Kernel

    Kernel(num_cores=cores)
    click.echo(f"Kernel: {cores} cores, 0 processes (idle)")
    click.echo("Use 'healthy_agent run' to submit tasks.")


@main.command()
@click.option("--host", default=None, help="Bind host (default from config)")
@click.option("--port", "-p", default=None, type=int, help="Bind port (default from config)")
@click.option("--cores", "-c", default=None, type=int, help="Number of kernel cores")
@click.option("--driver", "-d", default=None, help="LLM driver: mock, anthropic, deepseek, zhipu, ollama")
@click.option("--model", "-m", default=None, help="Model name (defaults per driver)")
@click.option("--skills-dir", default=None, help="Skills directory (default: ./skills)")
@click.option("--config", "-f", default=None, help="Config file path (healthy_agent.toml)")
def serve(host: str | None, port: int | None, cores: int | None, driver: str | None,
          model: str | None, skills_dir: str | None, config: str | None):
    """Start the HTTP server (Kernel runs persistently)."""
    import uvicorn
    from api import create_app
    app = create_app(
        num_cores=cores, driver_name=driver, model=model,
        skills_dir=skills_dir, config_path=config,
    )
    cfg = app.state.settings
    bind_host = host or cfg.server.host
    bind_port = port or cfg.server.port
    click.echo(f"Healthy Agent server starting on {bind_host}:{bind_port}")
    click.echo(f"  Kernel: {cfg.kernel.num_cores} cores | Driver: {cfg.driver.name} | Model: {cfg.driver.model}")
    click.echo(f"  Config: {config or 'auto-detect'}")
    click.echo(f"  Docs: http://{bind_host}:{bind_port}/docs")
    uvicorn.run(app, host=bind_host, port=bind_port, log_level=cfg.observability.log_level.lower(), log_config=None)
