import pytest

from app.core.config import settings
from app.services.llm_service import LLMConfigurationError, LLMService


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, tags_payload=None):
        self.tags_payload = tags_payload or {"models": []}

    async def get(self, endpoint):
        if endpoint == "/api/tags":
            return _FakeResponse(payload=self.tags_payload)
        if endpoint == "/v1/models":
            return _FakeResponse(status_code=200, payload={"data": []})
        return _FakeResponse(status_code=404)


@pytest.mark.asyncio
async def test_resolve_generation_model_raises_when_configured_ollama_model_missing(monkeypatch):
    fake_client = _FakeClient(
        tags_payload={
            "models": [
                {"name": "qwen3:4b"},
                {"name": "llama3.2"},
            ]
        }
    )

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", "Qwen/Qwen3-4B", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    with pytest.raises(LLMConfigurationError):
        await LLMService._resolve_generation_model()


@pytest.mark.asyncio
async def test_generate_uses_resolved_runtime_model(monkeypatch):
    captured_payload = {}

    async def _fake_post(endpoint, payload):
        captured_payload["endpoint"] = endpoint
        captured_payload["payload"] = payload
        return _FakeResponse(payload={"choices": [{"text": "Generated answer"}]})

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return "Qwen/Qwen3-4B"

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_post_with_startup_retry", classmethod(lambda cls, endpoint, payload: _fake_post(endpoint, payload)))

    result = await LLMService.generate(prompt="hello")

    assert result == "Generated answer"
    assert captured_payload["endpoint"] == "/v1/completions"
    assert captured_payload["payload"]["model"] == "Qwen/Qwen3-4B"


@pytest.mark.asyncio
async def test_generate_uses_ollama_native_generate_endpoint(monkeypatch):
    captured_payload = {}

    async def _fake_post(endpoint, payload):
        captured_payload["endpoint"] = endpoint
        captured_payload["payload"] = payload
        return _FakeResponse(payload={"response": "Generated from ollama"})

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return "qwen3:4b"

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_post_with_startup_retry", classmethod(lambda cls, endpoint, payload: _fake_post(endpoint, payload)))

    result = await LLMService.generate(prompt="hello")

    assert result == "Generated from ollama"
    assert captured_payload["endpoint"] == "/api/generate"
    assert captured_payload["payload"]["model"] == "qwen3:4b"
    assert captured_payload["payload"]["think"] is False


def test_prepare_ollama_prompt_adds_no_think_for_qwen3_models():
    prepared = LLMService._prepare_ollama_prompt("qwen3:4b", "What is methane boiling point?")
    assert prepared.startswith("/no_think\n")


def test_prepare_ollama_prompt_leaves_non_qwen_models_unchanged():
    prompt = "What is methane boiling point?"
    prepared = LLMService._prepare_ollama_prompt("llama3.2", prompt)
    assert prepared == prompt


@pytest.mark.asyncio
async def test_lifecycle_status_reports_configured_model_availability(monkeypatch):
    fake_client = _FakeClient(tags_payload={"models": [{"name": "qwen3:4b"}]})

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, endpoint):
            assert endpoint == "/v1/models"
            return _FakeResponse(status_code=200)

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", "Qwen/Qwen3-4B", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    import app.services.llm_service as llm_service_module

    monkeypatch.setattr(llm_service_module.httpx, "AsyncClient", _ProbeClient)

    status = await LLMService.get_lifecycle_status()

    assert status["container_reachable"] is True
    assert status["configured_model"] == "Qwen/Qwen3-4B"
    assert status["configured_model_available"] is False
    assert status["model"] == "Qwen/Qwen3-4B"
    assert status["available_models"] == ["qwen3:4b"]
