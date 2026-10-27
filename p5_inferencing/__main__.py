"""Run with: python -m p5_inferencing [--env-file PATH]."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .app import create_app
from .config import DEFAULT_ENV_FILE, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the P5 LM Studio inference gateway.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args()
    try:
        settings = Settings.from_env(args.env_file)
    except ValueError as exc:
        parser.error(str(exc))
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    if log_level not in {"critical", "error", "warning", "info", "debug"}:
        parser.error("LOG_LEVEL must be critical, error, warning, info or debug.")
    logging.basicConfig(level=log_level.upper())
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=settings.gateway_port,
        log_level=log_level,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
