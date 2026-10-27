"""Exercise HTTP behavior against a fake upstream; no model or tunnel is needed."""

import asyncio
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from p5_inferencing.app import create_app
from p5_inferencing.config import Settings

TEST_KEY = "test-only-gateway-key-with-at-least-32-characters"
AUTH = {"Authorization": f"Bearer {TEST_KEY}"}
CHAT = {"model": "public-model", "messages": [{"role": "user", "content": "hello"}]}


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.settings = Settings(
            api_key=TEST_KEY,
            lm_studio_base_url="http://backend.test/v1",
            lm_studio_model="loaded-model",
            public_model="public-model",
            lm_studio_api_key="test-only-backend-token",
            max_concurrent_requests=1,
            queue_timeout_seconds=0.02,
            max_request_bytes=4096,
        )
        await self.open_app(self.settings)

    async def handler(self, request):
        self.requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "loaded-model"}]})
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(
                200,
                content=b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n',
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hello"}}]},
        )

    async def open_app(self, settings, handler=None):
        self.app = create_app(settings, httpx.MockTransport(handler or self.handler))
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://gateway.test"
        )

    async def close_app(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def asyncTearDown(self):
        await self.close_app()

    async def test_liveness_does_not_contact_backend(self):
        response = await self.client.get("/health")
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(self.requests, [])

    async def test_every_inference_route_requires_valid_bearer_auth(self):
        for headers in ({}, {"Authorization": "Basic ignored"},
                        {"Authorization": "Bearer wrong"}, {"Authorization": b"Bearer \xc3\xa9"}):
            for path in ("/v1/models", "/ready"):
                response = await self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
            response = await self.client.post("/v1/chat/completions", headers=headers, json=CHAT)
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.requests, [])

    async def test_public_model_listing_is_configuration_not_a_readiness_claim(self):
        response = await self.client.get("/v1/models", headers=AUTH)
        self.assertEqual(response.json()["data"][0]["id"], "public-model")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.requests, [])

    async def test_readiness_checks_configured_backend_model(self):
        response = await self.client.get("/ready", headers=AUTH)
        self.assertEqual(response.json(), {"status": "ready", "model": "public-model"})
        self.assertEqual(str(self.requests[0].url), "http://backend.test/v1/models")

    async def test_unavailable_model_is_not_ready(self):
        await self.close_app()
        await self.open_app(self.settings, lambda _: httpx.Response(200, json={"data": []}))
        self.assertEqual((await self.client.get("/ready", headers=AUTH)).status_code, 503)

    async def test_unreachable_or_invalid_readiness_response_is_not_ready(self):
        for bad_response in (
            httpx.Response(401, json={"detail": "denied"}),
            httpx.Response(200, content=b"not json"),
            httpx.Response(200, json=[]),
        ):
            await self.close_app()
            await self.open_app(self.settings, lambda _, r=bad_response: r)
            self.assertEqual((await self.client.get("/ready", headers=AUTH)).status_code, 503)

    async def test_chat_maps_model_and_uses_separate_upstream_credentials(self):
        payload = {**CHAT, "tools": [{"type": "function", "function": {"name": "search"}}],
                   "response_format": {"type": "json_object"}, "temperature": 0}
        response = await self.client.post(
            "/v1/chat/completions",
            headers={**AUTH, "X-Forwarded-For": "198.51.100.42"},
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "hello")
        sent = self.requests[0]
        self.assertEqual(str(sent.url), "http://backend.test/v1/chat/completions")
        self.assertEqual(json.loads(sent.content), {**payload, "model": "loaded-model"})
        self.assertEqual(sent.headers["authorization"], "Bearer test-only-backend-token")
        self.assertNotIn(TEST_KEY, str(sent.headers))
        self.assertNotIn("x-forwarded-for", sent.headers)

    async def test_gateway_key_is_not_sent_to_an_unauthenticated_backend(self):
        await self.close_app()
        await self.open_app(replace(self.settings, lm_studio_api_key=None))
        await self.client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
        self.assertNotIn("authorization", self.requests[0].headers)

    async def test_stream_is_forwarded_and_slot_is_reusable(self):
        response = await self.client.post(
            "/v1/chat/completions", headers=AUTH, json={**CHAT, "stream": True}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream")
        self.assertIn(b"data: [DONE]\n\n", response.content)
        again = await self.client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
        self.assertEqual(again.status_code, 200)

    async def test_bad_payloads_do_not_reach_backend(self):
        for payload in ([], {"messages": []}, {**CHAT, "stream": "true"},
                        {**CHAT, "model": "another-model"}, {**CHAT, "model": {}},
                        {**CHAT, "model": None}):
            response = await self.client.post(
                "/v1/chat/completions", headers=AUTH, json=payload
            )
            self.assertEqual(response.status_code, 400)
        for content in (b"{invalid", b"\xff"):
            response = await self.client.post(
                "/v1/chat/completions", headers=AUTH, content=content
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.requests, [])

    async def test_request_size_is_bounded_even_without_content_length(self):
        async def chunks():
            yield b" " * 3000
            yield b" " * 3000
        response = await self.client.post(
            "/v1/chat/completions", headers=AUTH, content=chunks()
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.requests, [])

    async def test_timeout_is_sanitized_and_releases_slot(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadTimeout("sensitive-backend-diagnostic", request=request)
            return await self.handler(request)
        await self.close_app()
        await self.open_app(self.settings, handler)
        response = await self.client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("sensitive-backend-diagnostic", response.text)
        self.assertEqual((await self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        )).status_code, 200)

    async def test_upstream_error_keeps_status_and_body_without_becoming_sse(self):
        await self.close_app()
        await self.open_app(
            self.settings,
            lambda _: httpx.Response(429, json={"error": {"message": "capacity exceeded"}}),
        )
        response = await self.client.post(
            "/v1/chat/completions", headers=AUTH, json={**CHAT, "stream": True}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["message"], "capacity exceeded")

    async def test_cancellation_releases_an_inflight_request_slot(self):
        started = asyncio.Event()
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await asyncio.Event().wait()
            return await self.handler(request)
        await self.close_app()
        await self.open_app(self.settings, handler)
        first = asyncio.create_task(self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual((await self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        )).status_code, 200)

    async def test_interrupted_stream_closes_backend_and_releases_slot(self):
        closed = []
        class InterruptedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"data: first\n\n"
                raise httpx.ReadError("stream interrupted")
            async def aclose(self):
                closed.append(True)
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    200, stream=InterruptedStream(),
                    headers={"content-type": "text/event-stream"},
                )
            return await self.handler(request)
        await self.close_app()
        await self.open_app(self.settings, handler)
        with self.assertRaises(httpx.ReadError):
            await self.client.post(
                "/v1/chat/completions", headers=AUTH, json={**CHAT, "stream": True}
            )
        self.assertTrue(closed)
        self.assertEqual((await self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        )).status_code, 200)

    async def test_capacity_limit_rejects_a_waiting_request_then_recovers(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            started.set()
            await release.wait()
            return await self.handler(request)
        await self.close_app()
        await self.open_app(self.settings, handler)
        first = asyncio.create_task(self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            second = await self.client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
            self.assertEqual(second.status_code, 503)
            self.assertEqual(second.headers["retry-after"], "1")
        finally:
            release.set()
            await first
        self.assertEqual((await self.client.post(
            "/v1/chat/completions", headers=AUTH, json=CHAT
        )).status_code, 200)

    async def test_api_schema_and_interactive_docs_are_not_exposed(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual((await self.client.get(path)).status_code, 404)

    async def test_managed_tunnel_targets_gateway_and_disables_inspection(self):
        await self.close_app()
        with patch("pyngrok.ngrok.connect", return_value=SimpleNamespace(
            public_url="https://gateway.example.test"
        )) as connect, patch("pyngrok.ngrok.disconnect") as disconnect:
            await self.open_app(replace(
                self.settings,
                enable_ngrok=True,
                ngrok_auth_token="test-only-ngrok-token",
                gateway_port=8001,
            ))
            self.assertEqual(connect.call_args.kwargs["addr"], "http://127.0.0.1:8001")
            self.assertIs(connect.call_args.kwargs["inspect"], False)
            self.assertIs(connect.call_args.kwargs["bind_tls"], True)
            await self.close_app()
            disconnect.assert_called_once()
            self.assertEqual(disconnect.call_args.args, ("https://gateway.example.test",))
        # Restore a regular fixture for tearDown.
        await self.open_app(self.settings)


if __name__ == "__main__":
    unittest.main()
