"""Configuration never needs a real .env or credentials for testing."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from p5_inferencing.config import Settings

TEST_KEY = "test-only-gateway-key-with-at-least-32-characters"


class ConfigurationTests(unittest.TestCase):
    def test_missing_short_and_placeholder_keys_are_rejected(self):
        for value in ("", "short", "change-this-to-a-long-random-secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Settings(api_key=value)

    def test_secrets_are_not_in_configuration_repr(self):
        settings = Settings(
            api_key=TEST_KEY, lm_studio_api_key="private-upstream", ngrok_auth_token="private-ngrok"
        )
        for secret in (TEST_KEY, "private-upstream", "private-ngrok"):
            self.assertNotIn(secret, repr(settings))

    def test_invalid_limits_urls_and_tunnel_configuration_are_rejected(self):
        settings = Settings(api_key=TEST_KEY)
        overrides = (
            {"request_timeout_seconds": float("inf")},
            {"queue_timeout_seconds": 0},
            {"max_concurrent_requests": 0},
            {"max_request_bytes": 0},
            {"gateway_port": 0},
            {"lm_studio_base_url": "file:///private/v1"},
            {"lm_studio_base_url": "http://user:secret@example.test/v1"},
            {"lm_studio_base_url": "http://example.test/v1?key=secret"},
            {"lm_studio_base_url": "http://example.test"},
            {"enable_ngrok": True},
        )
        for values in overrides:
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(settings, **values)

    def test_environment_values_override_explicit_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(f"API_KEY={TEST_KEY}\nGATEWAY_PORT=8001\n")
            with patch.dict(os.environ, {"GATEWAY_PORT": "8002"}, clear=True):
                settings = Settings.from_env(path)
                self.assertEqual(settings.api_key, TEST_KEY)
                self.assertEqual(settings.gateway_port, 8002)

    def test_environment_loading_can_be_disabled(self):
        with patch.dict(os.environ, {"API_KEY": TEST_KEY}, clear=True):
            self.assertFalse(Settings.from_env(None).enable_ngrok)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Settings.from_env(None)

    def test_invalid_numeric_values_are_not_reflected_in_errors(self):
        with patch.dict(os.environ, {
            "API_KEY": TEST_KEY, "GATEWAY_PORT": "sensitive-invalid-value"
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "must be numeric") as raised:
                Settings.from_env(None)
            self.assertNotIn("sensitive-invalid-value", str(raised.exception))

    def test_tunnel_flag_does_not_silently_accept_a_typo(self):
        with patch.dict(os.environ, {
            "API_KEY": TEST_KEY, "ENABLE_NGROK": "tru"
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "true or false"):
                Settings.from_env(None)


if __name__ == "__main__":
    unittest.main()
