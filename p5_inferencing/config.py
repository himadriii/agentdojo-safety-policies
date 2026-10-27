"""Explicit, validated configuration for the inference host."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_ENV_FILE = Path(__file__).with_name(".env")


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise ValueError(f"{name} must be true or false.")
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_model: str = "openai/gpt-oss-20b"
    public_model: str = "openai/gpt-oss-20b"
    lm_studio_api_key: str | None = field(default=None, repr=False)
    enable_ngrok: bool = False
    ngrok_auth_token: str | None = field(default=None, repr=False)
    gateway_port: int = 8000
    request_timeout_seconds: float = 600
    queue_timeout_seconds: float = 30
    max_concurrent_requests: int = 2
    max_request_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if len(self.api_key.strip()) < 32 or self.api_key.lower().startswith("change-"):
            raise ValueError("API_KEY must be a unique secret of at least 32 characters.")
        parsed = urlsplit(self.lm_studio_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.rstrip("/").endswith("/v1")
        ):
            raise ValueError("LM_STUDIO_BASE_URL must be an HTTP(S) API URL ending in /v1.")
        if not self.lm_studio_model.strip() or not self.public_model.strip():
            raise ValueError("LM_STUDIO_MODEL and PUBLIC_MODEL must be nonempty.")
        for name, value in (
            ("REQUEST_TIMEOUT_SECONDS", self.request_timeout_seconds),
            ("QUEUE_TIMEOUT_SECONDS", self.queue_timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if not 1 <= self.gateway_port <= 65535:
            raise ValueError("GATEWAY_PORT must be between 1 and 65535.")
        if self.max_concurrent_requests < 1 or self.max_request_bytes < 1:
            raise ValueError("MAX_CONCURRENT_REQUESTS and MAX_REQUEST_BYTES must be positive.")
        if self.enable_ngrok and not self.ngrok_auth_token:
            raise ValueError("NGROK_AUTHTOKEN is required when ENABLE_NGROK=true.")

    @classmethod
    def from_env(cls, env_file: Path | None = DEFAULT_ENV_FILE) -> "Settings":
        # Only this package's file is read; the benchmark's root .env is separate.
        # Explicit process environment values take precedence.
        if env_file is not None:
            load_dotenv(env_file, override=False)
        try:
            return cls(
                api_key=os.getenv("API_KEY", "").strip(),
                lm_studio_base_url=os.getenv(
                    "LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"
                ).strip().rstrip("/"),
                lm_studio_model=os.getenv("LM_STUDIO_MODEL", "openai/gpt-oss-20b").strip(),
                public_model=os.getenv("PUBLIC_MODEL", "openai/gpt-oss-20b").strip(),
                lm_studio_api_key=os.getenv("LM_STUDIO_API_KEY") or None,
                enable_ngrok=_flag("ENABLE_NGROK"),
                ngrok_auth_token=os.getenv("NGROK_AUTHTOKEN") or None,
                gateway_port=int(os.getenv("GATEWAY_PORT", "8000")),
                request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "600")),
                queue_timeout_seconds=float(os.getenv("QUEUE_TIMEOUT_SECONDS", "30")),
                max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")),
                max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", str(2 * 1024 * 1024))),
            )
        except ValueError as exc:
            # Numeric conversion errors can include the original input; keep
            # operator diagnostics useful without reflecting configuration values.
            if str(exc).startswith(("invalid literal", "could not convert")):
                raise ValueError("Gateway port, limits and timeouts must be numeric.") from None
            raise
