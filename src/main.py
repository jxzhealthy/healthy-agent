"""
Healthy Agent — Start the server.

Usage:
    python src/main.py
    python src/main.py --port 8000 --cores 4 --driver anthropic --model claude-opus-4-6
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))



def main():
    parser = argparse.ArgumentParser(description="Healthy Agent Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument("--cores", "-c", type=int, default=4)
    parser.add_argument("--driver", "-d", default="mock", choices=["mock", "anthropic", "openai", "deepseek", "zhipu", "qwen", "ollama"])
    parser.add_argument("--model", "-m", default=None)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import uvicorn

    os.environ["HA_CORES"] = str(args.cores)
    os.environ["HA_DRIVER"] = args.driver
    if args.model:
        os.environ["HA_MODEL"] = args.model

    uvicorn.run(
        "api.app:app_instance",
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
        reload=True,
        factory=True,
    )


if __name__ == "__main__":
    main()
