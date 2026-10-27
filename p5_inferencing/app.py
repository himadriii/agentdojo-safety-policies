"""Authenticated chat-completions proxy with bounded concurrency and SSE support."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import __version__
from .config import Settings

logger = logging.getLogger("p5-inferencing")


def create_app(
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create an app without starting a server, loading a model, or opening a tunnel."""
    config = settings or Settings.from_env()
    request_slots = asyncio.Semaphore(config.max_concurrent_requests)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        headers = {}
        if config.lm_studio_api_key:
            headers["authorization"] = f"Bearer {config.lm_studio_api_key}"
        tunnel = None
        tunnel_config = None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.request_timeout_seconds, connect=10),
            transport=upstream_transport,
            headers=headers,
            follow_redirects=False,
        ) as client:
            application.state.upstream_client = client
            try:
                if config.enable_ngrok:
                    from pyngrok import ngrok
                    from pyngrok.conf import PyngrokConfig

                    # Pass credentials in memory rather than writing a global
                    # ngrok agent configuration file.
                    tunnel_config = PyngrokConfig(auth_token=config.ngrok_auth_token)
                    tunnel = await asyncio.to_thread(
                        ngrok.connect,
                        addr=f"http://127.0.0.1:{config.gateway_port}",
                        proto="http",
                        bind_tls=True,
                        inspect=False,
                        pyngrok_config=tunnel_config,
                    )
                    logger.info("Public API base URL: %s/v1", tunnel.public_url)
                yield
            finally:
                if tunnel is not None:
                    from pyngrok import ngrok

                    await asyncio.to_thread(
                        ngrok.disconnect, tunnel.public_url, pyngrok_config=tunnel_config
                    )

    application = FastAPI(
        title="P5 Inference Gateway",
        description="Authenticated access to a single LM Studio model.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def authorize(request: Request) -> None:
        scheme, separator, token = request.headers.get("authorization", "").partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(
                token.strip().encode("utf-8"), config.api_key.encode("utf-8")
            )
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Process liveness only; does not claim that a model is loaded."""
        return {"status": "ok"}

    @application.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        """Check backend reachability and registration of the configured model."""
        authorize(request)
        try:
            response = await application.state.upstream_client.get(
                f"{config.lm_studio_base_url}/models"
            )
            response.raise_for_status()
            payload = response.json()
            available = {
                item.get("id")
                for item in payload.get("data", [])
                if isinstance(item, dict)
            }
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            raise HTTPException(status_code=503, detail="LM Studio is not ready.") from None
        if config.lm_studio_model not in available:
            raise HTTPException(status_code=503, detail="Configured model is not available.")
        return {"status": "ready", "model": config.public_model}

    @application.get("/v1/models")
    async def models(request: Request) -> JSONResponse:
        authorize(request)
        return JSONResponse(
            {
                "object": "list",
                "data": [{
                    "id": config.public_model,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }],
            },
            headers={"Cache-Control": "no-store"},
        )

    async def read_payload(request: Request) -> dict:
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > config.max_request_bytes:
                raise HTTPException(status_code=413, detail="Request body exceeds the size limit.")
            content.extend(chunk)
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
        return payload

    @application.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        authorize(request)
        payload = await read_payload(request)
        requested_model = payload.get("model", config.public_model)
        if not isinstance(requested_model, str) or requested_model not in {
            config.public_model, config.lm_studio_model
        }:
            raise HTTPException(status_code=400, detail="Requested model is not served by this gateway.")
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise HTTPException(status_code=400, detail="messages must be a nonempty list.")
        if "stream" in payload and not isinstance(payload["stream"], bool):
            raise HTTPException(status_code=400, detail="stream must be a boolean.")
        payload["model"] = config.lm_studio_model
        try:
            await asyncio.wait_for(
                request_slots.acquire(), timeout=config.queue_timeout_seconds
            )
        except TimeoutError:
            raise HTTPException(
                status_code=503,
                detail="Gateway is busy; retry later.",
                headers={"Retry-After": "1"},
            ) from None

        upstream_response = None
        handed_to_stream = False
        try:
            client = application.state.upstream_client
            upstream_request = client.build_request(
                "POST",
                f"{config.lm_studio_base_url}/chat/completions",
                json=payload,
                headers={"accept": request.headers.get("accept", "application/json")},
            )
            upstream_response = await client.send(upstream_request, stream=True)
            response_headers = {
                key: upstream_response.headers[key]
                for key in ("content-type", "cache-control", "x-request-id")
                if key in upstream_response.headers
            }
            if payload.get("stream") is True and upstream_response.is_success:
                async def stream_response() -> AsyncIterator[bytes]:
                    try:
                        async for chunk in upstream_response.aiter_bytes():
                            yield chunk
                    except httpx.RequestError as exc:
                        logger.warning("Upstream stream interrupted (%s).", type(exc).__name__)
                        raise
                    finally:
                        try:
                            await upstream_response.aclose()
                        finally:
                            request_slots.release()

                result = StreamingResponse(
                    stream_response(),
                    status_code=upstream_response.status_code,
                    headers=response_headers,
                )
                handed_to_stream = True
                return result

            content = await upstream_response.aread()
            return Response(
                content=content,
                status_code=upstream_response.status_code,
                headers=response_headers,
            )
        except httpx.RequestError as exc:
            logger.warning("LM Studio request failed (%s).", type(exc).__name__)
            raise HTTPException(status_code=502, detail="LM Studio request failed.") from None
        finally:
            if not handed_to_stream:
                try:
                    if upstream_response is not None:
                        await upstream_response.aclose()
                finally:
                    request_slots.release()

    return application
