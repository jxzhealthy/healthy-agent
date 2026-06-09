"""
Healthy Agent — Start the server.

Usage:
    python src/main.py
    python src/main.py --port 8000 --cores 4 --driver anthropic --model claude-opus-4-6
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from healthy_agent.server import create_app


def main():
    parser = argparse.ArgumentParser(description="Healthy Agent Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument("--cores", "-c", type=int, default=4)
    parser.add_argument("--driver", "-d", default="mock", choices=["mock", "anthropic", "openai", "deepseek", "zhipu", "ollama"])
    parser.add_argument("--model", "-m", default=None)
    args = parser.parse_args()

    import uvicorn
    app = create_app(num_cores=args.cores, driver_name=args.driver, model=args.model)
    print(f"Healthy Agent starting on {args.host}:{args.port}")
    print(f"  Kernel: {args.cores} cores | Driver: {args.driver} | Model: {args.model or 'default'}")
    print(f"  API docs: http://localhost:{args.port}/docs")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
