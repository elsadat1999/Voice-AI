"""Regression tests for OpenAI Realtime "Test Connection" honoring managed secrets.

test_provider_connection() resolves api_key_file / api_key_env into
provider_config["api_key"] before provider branches execute. These tests pin
that openai_realtime uses the resolved key from api_key_file or api_key_env,
falls back to OPENAI_API_KEY from .env, and fails fast without network calls
when no key is configured.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from api import config  # noqa: E402


def _fake_openai_models_client(captured):
    """A fake httpx.AsyncClient whose GET records the headers it was called with."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200

    async def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return fake_resp

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=fake_get)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    return fake_client


def _openai_realtime_request(**extra_config):
    return config.ProviderTestRequest(
        name="openai_realtime",
        config={
            "type": "openai_realtime",
            "realtime_base_url": "wss://api.openai.com/v1/realtime",
            **extra_config,
        },
    )


@pytest.mark.asyncio
async def test_uses_resolved_key_from_api_key_file(monkeypatch, tmp_path):
    """A key delivered through api_key_file reaches OpenAI Authorization header."""
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config.settings, "ENV_PATH", str(env_path))
    monkeypatch.setattr(
        config,
        "_provider_instances_module",
        lambda: {"resolve_secret_value": lambda *a, **k: "key-from-file"},
    )

    request = _openai_realtime_request(api_key_file="/app/project/secrets/providers/openai_realtime/api-key")
    captured = {}

    with patch("httpx.AsyncClient", return_value=_fake_openai_models_client(captured)):
        result = await config.test_provider_connection(request)

    assert result["success"] is True
    assert captured["headers"].get("Authorization") == "Bearer key-from-file"


@pytest.mark.asyncio
async def test_uses_resolved_key_from_api_key_env(monkeypatch, tmp_path):
    """A key delivered through api_key_env reaches OpenAI Authorization header."""
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config.settings, "ENV_PATH", str(env_path))
    monkeypatch.setattr(
        config,
        "_provider_instances_module",
        lambda: {"resolve_secret_value": lambda *a, **k: "key-from-env-ref"},
    )

    request = _openai_realtime_request(api_key_env="MY_OPENAI_KEY_REF")
    captured = {}

    with patch("httpx.AsyncClient", return_value=_fake_openai_models_client(captured)):
        result = await config.test_provider_connection(request)

    assert result["success"] is True
    assert captured["headers"].get("Authorization") == "Bearer key-from-env-ref"


@pytest.mark.asyncio
async def test_falls_back_to_dotenv_when_no_managed_secret_configured(monkeypatch, tmp_path):
    """No api_key_file or api_key_env set: the plain .env OPENAI_API_KEY still works."""
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setattr(config.settings, "ENV_PATH", str(env_path))

    request = _openai_realtime_request()
    captured = {}

    with patch("httpx.AsyncClient", return_value=_fake_openai_models_client(captured)):
        result = await config.test_provider_connection(request)

    assert result["success"] is True
    assert captured["headers"].get("Authorization") == "Bearer dotenv-key"


@pytest.mark.asyncio
async def test_reports_missing_key_without_calling_openai(monkeypatch, tmp_path):
    """Nothing resolves anywhere: fail with the message, never touch the network."""
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config.settings, "ENV_PATH", str(env_path))

    request = _openai_realtime_request()

    with patch("httpx.AsyncClient") as mock_client_cls:
        result = await config.test_provider_connection(request)

    mock_client_cls.assert_not_called()
    assert result == {
        "success": False,
        "message": "No OpenAI API key configured (checked api_key_file/api_key_env and OPENAI_API_KEY in .env)",
    }
