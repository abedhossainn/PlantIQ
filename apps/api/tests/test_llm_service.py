import pytest

from app.core.config import settings
from app.services.llm_service import LLMConfigurationError, LLMService


OLLAMA_MODEL = "qwen3:4b"
VLLM_MODEL = "Qwen/Qwen3-4B"


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
                {"name": OLLAMA_MODEL},
                {"name": "llama3.2"},
            ]
        }
    )

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", VLLM_MODEL, raising=False)
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
        return VLLM_MODEL

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_post_with_startup_retry", classmethod(lambda cls, endpoint, payload: _fake_post(endpoint, payload)))

    result = await LLMService.generate(prompt="hello")

    assert result == "Generated answer"
    assert captured_payload["endpoint"] == "/v1/completions"
    assert captured_payload["payload"]["model"] == VLLM_MODEL


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
        return OLLAMA_MODEL

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_post_with_startup_retry", classmethod(lambda cls, endpoint, payload: _fake_post(endpoint, payload)))

    result = await LLMService.generate(prompt="hello")

    assert result == "Generated from ollama"
    assert captured_payload["endpoint"] == "/api/generate"
    assert captured_payload["payload"]["model"] == OLLAMA_MODEL
    assert captured_payload["payload"]["think"] is False


def test_prepare_ollama_prompt_adds_no_think_for_qwen3_models():
    prepared = LLMService._prepare_ollama_prompt(OLLAMA_MODEL, "What is methane boiling point?")
    assert prepared.startswith("/no_think\n")


def test_prepare_ollama_prompt_leaves_non_qwen_models_unchanged():
    prompt = "What is methane boiling point?"
    prepared = LLMService._prepare_ollama_prompt("llama3.2", prompt)
    assert prepared == prompt


@pytest.mark.asyncio
async def test_lifecycle_status_reports_configured_model_availability(monkeypatch):
    fake_client = _FakeClient(tags_payload={"models": [{"name": OLLAMA_MODEL}]})

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            self._args = args
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, endpoint):
            assert endpoint == "/v1/models"
            return _FakeResponse(status_code=200)

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", VLLM_MODEL, raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    import app.services.llm_service as llm_service_module

    monkeypatch.setattr(llm_service_module.httpx, "AsyncClient", _ProbeClient)

    status = await LLMService.get_lifecycle_status()

    assert status["container_reachable"] is True
    assert status["configured_model"] == VLLM_MODEL
    assert status["configured_model_available"] is False
    assert status["model"] == VLLM_MODEL
    assert status["available_models"] == [OLLAMA_MODEL]


# ---------------------------------------------------------------------------
# _extract_completion_text
# ---------------------------------------------------------------------------

def test_extract_completion_text_success():
    result = {"choices": [{"text": "Hello world"}]}
    assert LLMService._extract_completion_text(result) == "Hello world"


def test_extract_completion_text_empty_text_raises():
    from app.services.llm_service import LLMUnavailableError
    with pytest.raises(LLMUnavailableError):
        LLMService._extract_completion_text({"choices": [{"text": ""}]})


def test_extract_completion_text_no_choices_raises():
    from app.services.llm_service import LLMUnavailableError
    with pytest.raises(LLMUnavailableError):
        LLMService._extract_completion_text({})


def test_extract_completion_text_empty_choices_raises():
    from app.services.llm_service import LLMUnavailableError
    with pytest.raises(LLMUnavailableError):
        LLMService._extract_completion_text({"choices": []})


# ---------------------------------------------------------------------------
# _parse_ollama_stream_line
# ---------------------------------------------------------------------------

import json as _json


def test_parse_ollama_stream_line_token():
    line = _json.dumps({"response": "hello", "done": False})
    token, is_done = LLMService._parse_ollama_stream_line(line)
    assert token == "hello"
    assert is_done is False


def test_parse_ollama_stream_line_done_flag():
    line = _json.dumps({"response": "", "done": True})
    _, is_done = LLMService._parse_ollama_stream_line(line)
    assert is_done is True


def test_parse_ollama_stream_line_empty_string():
    token, is_done = LLMService._parse_ollama_stream_line("")
    assert token == ""
    assert is_done is False


def test_parse_ollama_stream_line_invalid_json():
    token, is_done = LLMService._parse_ollama_stream_line("not-json")
    assert token == ""
    assert is_done is False


# ---------------------------------------------------------------------------
# _parse_openai_stream_line
# ---------------------------------------------------------------------------

def test_parse_openai_stream_line_no_prefix():
    token, is_done = LLMService._parse_openai_stream_line("plain line")
    assert token == ""
    assert is_done is False


def test_parse_openai_stream_line_done():
    token, is_done = LLMService._parse_openai_stream_line("data: [DONE]")
    assert token == ""
    assert is_done is True


def test_parse_openai_stream_line_with_text():
    data = _json.dumps({"choices": [{"text": "world"}]})
    token, is_done = LLMService._parse_openai_stream_line(f"data: {data}")
    assert token == "world"
    assert is_done is False


def test_parse_openai_stream_line_empty_choices():
    data = _json.dumps({"choices": []})
    token, is_done = LLMService._parse_openai_stream_line(f"data: {data}")
    assert token == ""
    assert is_done is False


def test_parse_openai_stream_line_invalid_json():
    token, is_done = LLMService._parse_openai_stream_line("data: {bad-json}")
    assert token == ""
    assert is_done is False


# ---------------------------------------------------------------------------
# _resolve_generation_overrides
# ---------------------------------------------------------------------------

def test_resolve_generation_overrides_uses_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_TOKENS", 1000, raising=False)
    monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.8, raising=False)
    monkeypatch.setattr(settings, "LLM_TOP_P", 0.9, raising=False)
    mt, temp, tp = LLMService._resolve_generation_overrides(None, None, None)
    assert mt == 1000
    assert temp == 0.8
    assert tp == 0.9


def test_resolve_generation_overrides_uses_explicit():
    mt, temp, tp = LLMService._resolve_generation_overrides(256, 0.3, 0.5)
    assert mt == 256
    assert temp == 0.3
    assert tp == 0.5


# ---------------------------------------------------------------------------
# _build_ollama_generate_payload
# ---------------------------------------------------------------------------

def test_build_ollama_generate_payload_structure():
    payload = LLMService._build_ollama_generate_payload(
        model="qwen3-4b",
        prompt="Test",
        max_tokens=512,
        temperature=0.7,
        top_p=0.95,
        stream=False,
    )
    assert payload["model"] == "qwen3-4b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 512


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_returns_true(monkeypatch):
    from unittest.mock import AsyncMock
    fake_client = AsyncMock()
    fake_client.get.return_value = _FakeResponse(status_code=200)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    result = await LLMService.health_check()
    assert result is True


@pytest.mark.asyncio
async def test_health_check_non_200_returns_false(monkeypatch):
    from unittest.mock import AsyncMock
    fake_client = AsyncMock()
    fake_client.get.return_value = _FakeResponse(status_code=503)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    result = await LLMService.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_health_check_exception_returns_false(monkeypatch):
    from unittest.mock import AsyncMock
    fake_client = AsyncMock()
    fake_client.get.side_effect = Exception("connect error")
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    result = await LLMService.health_check()
    assert result is False


# ---------------------------------------------------------------------------
# _resolve_generation_model — ollama variants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_generation_model_ollama_no_models_raises(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", "qwen3-4b", raising=False)
    fake_client = _FakeClient(tags_payload={"models": []})
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    with pytest.raises(LLMConfigurationError, match="no local models"):
        await LLMService._resolve_generation_model()


# ---------------------------------------------------------------------------
# _request_started / _request_finished counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_counter_increments_and_decrements(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LLM_DEMAND_HEARTBEAT_FILE", str(tmp_path / "hb"), raising=False)
    monkeypatch.setattr(settings, "LLM_UNLOAD_AFTER_REQUEST", False, raising=False)
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)

    LLMService._active_requests = 0
    await LLMService._request_started()
    assert LLMService._active_requests == 1
    await LLMService._request_finished()
    assert LLMService._active_requests == 0


@pytest.mark.asyncio
async def test_request_finished_clamps_at_zero(monkeypatch):
    monkeypatch.setattr(settings, "LLM_UNLOAD_AFTER_REQUEST", False, raising=False)
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    LLMService._active_requests = 0
    await LLMService._request_finished()
    assert LLMService._active_requests == 0


@pytest.mark.asyncio
async def test_post_with_startup_retry_retries_then_succeeds(monkeypatch):
    import httpx
    from unittest.mock import AsyncMock

    class _Resp:
        def raise_for_status(self):
            return None

    request = httpx.Request("POST", "http://localhost/v1/completions")
    attempts = {"n": 0}

    async def _post(_endpoint, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("down", request=request)
        return _Resp()

    fake_client = AsyncMock()
    fake_client.post.side_effect = _post
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))
    monkeypatch.setattr(settings, "LLM_STARTUP_WAIT_SECONDS", 1, raising=False)
    monkeypatch.setattr(settings, "LLM_RETRY_INTERVAL_SECONDS", 0.01, raising=False)

    async def _nosleep(_):
        return None

    import app.services.llm_service as llm_module
    monkeypatch.setattr(llm_module.asyncio, "sleep", _nosleep)

    out = await LLMService._post_with_startup_retry("/v1/completions", {"x": 1})
    assert out is not None
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_wait_or_raise_stream_retry_raises_after_deadline():
    from app.services.llm_service import LLMUnavailableError

    with pytest.raises(LLMUnavailableError):
        await LLMService._wait_or_raise_stream_retry(
            attempt=3,
            deadline=0.0,
            interval=0.1,
            exc=RuntimeError("boom"),
        )


@pytest.mark.asyncio
async def test_wait_or_raise_stream_retry_sleeps_before_deadline(monkeypatch):
    calls = {"slept": False}

    async def _nosleep(_):
        calls["slept"] = True

    import app.services.llm_service as llm_module
    monkeypatch.setattr(llm_module.asyncio, "sleep", _nosleep)

    import time
    await LLMService._wait_or_raise_stream_retry(
        attempt=1,
        deadline=time.monotonic() + 100,
        interval=0.01,
        exc=RuntimeError("tmp"),
    )
    assert calls["slept"] is True


@pytest.mark.asyncio
async def test_yield_fallback_non_stream_text_yields_when_generate_returns(monkeypatch):
    monkeypatch.setattr(LLMService, "generate", classmethod(lambda cls, **kwargs: _resolved_text()))

    async def _collect():
        out = []
        async for t in LLMService._yield_fallback_non_stream_text(
            prompt="x", max_tokens=10, temperature=0.1, top_p=0.9, stop=None
        ):
            out.append(t)
        return out

    async def _resolved_text():
        return "fallback"

    tokens = await _collect()
    assert tokens == ["fallback"]


@pytest.mark.asyncio
async def test_generate_stream_openai_yields_tokens(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: object()))

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _stream_openai(*_args, **_kwargs):
        yield "A"
        yield "B"

    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_stream_openai_completions_with_retry", classmethod(lambda cls, **kwargs: _stream_openai()))

    out = []
    async for tok in LLMService.generate_stream("hello"):
        out.append(tok)
    assert out == ["A", "B"]


@pytest.mark.asyncio
async def test_generate_stream_ollama_yields_tokens(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: object()))

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return "qwen3:4b"

    async def _stream_ollama(*_args, **_kwargs):
        yield "X"

    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_stream_ollama_with_retry", classmethod(lambda cls, **kwargs: _stream_ollama()))

    out = []
    async for tok in LLMService.generate_stream("hello"):
        out.append(tok)
    assert out == ["X"]


@pytest.mark.asyncio
async def test_generate_wraps_http_error_as_unavailable(monkeypatch):
    import httpx
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_http(*_args, **_kwargs):
        raise httpx.HTTPError("http fail")

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_generate_with_openai_completions", classmethod(lambda cls, **kwargs: _raise_http()))

    with pytest.raises(LLMUnavailableError):
        await LLMService.generate("hello")


def test_get_client_creates_and_reuses_singleton(monkeypatch):
    import app.services.llm_service as llm_module

    created = []

    class _Client:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "LLM_HOST", "localhost", raising=False)
    monkeypatch.setattr(settings, "LLM_PORT", 11434, raising=False)
    monkeypatch.setattr(settings, "LLM_TIMEOUT", 12, raising=False)

    LLMService._client = None
    c1 = LLMService.get_client()
    c2 = LLMService.get_client()

    assert c1 is c2
    assert len(created) == 1
    assert created[0]["base_url"] == "http://localhost:11434"


@pytest.mark.asyncio
async def test_request_finished_triggers_unload_for_ollama(monkeypatch):
    called = {"n": 0}

    async def _fake_unload():
        called["n"] += 1

    monkeypatch.setattr(settings, "LLM_UNLOAD_AFTER_REQUEST", True, raising=False)
    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "_unload_ollama_model", classmethod(lambda cls: _fake_unload()))

    LLMService._active_requests = 1
    await LLMService._request_finished()
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_list_ollama_models_non_ollama_backend_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    assert await LLMService._list_ollama_models() == []


@pytest.mark.asyncio
async def test_resolve_generation_model_non_ollama_returns_configured(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", VLLM_MODEL, raising=False)
    assert await LLMService._resolve_generation_model() == VLLM_MODEL


@pytest.mark.asyncio
async def test_post_with_startup_retry_raises_after_deadline(monkeypatch):
    import httpx
    request = httpx.Request("POST", "http://localhost/v1/completions")

    class _Client:
        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: _Client()))
    monkeypatch.setattr(settings, "LLM_STARTUP_WAIT_SECONDS", 0, raising=False)
    monkeypatch.setattr(settings, "LLM_RETRY_INTERVAL_SECONDS", 0.01, raising=False)

    with pytest.raises(httpx.ConnectError):
        await LLMService._post_with_startup_retry("/v1/completions", {"x": 1})


@pytest.mark.asyncio
async def test_iter_openai_stream_tokens_handles_done_line():
    class _Resp:
        async def aiter_lines(self):
            yield "data: [DONE]"

    out = []
    async for tok in LLMService._iter_openai_stream_tokens(_Resp()):
        out.append(tok)
    assert out == []


@pytest.mark.asyncio
async def test_generate_wraps_generic_error_as_unavailable(monkeypatch):
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_generic(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_generate_with_openai_completions", classmethod(lambda cls, **kwargs: _raise_generic()))

    with pytest.raises(LLMUnavailableError):
        await LLMService.generate("hello")


@pytest.mark.asyncio
async def test_generate_stream_wraps_generic_error(monkeypatch):
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_generic(*_args, **_kwargs):
        raise RuntimeError("stream boom")
        yield  # pragma: no cover

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: object()))
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_stream_openai_completions_with_retry", classmethod(lambda cls, **kwargs: _raise_generic()))

    with pytest.raises(LLMUnavailableError):
        async for _ in LLMService.generate_stream("hello"):
            pass


@pytest.mark.asyncio
async def test_get_lifecycle_status_reads_heartbeat(monkeypatch, tmp_path):
    hb = tmp_path / "llm-heartbeat"
    hb.write_text("ok", encoding="utf-8")

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, endpoint):
            assert endpoint == "/v1/models"
            return _FakeResponse(status_code=503)

    import app.services.llm_service as llm_module
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _ProbeClient)
    monkeypatch.setattr(settings, "LLM_DEMAND_HEARTBEAT_FILE", str(hb), raising=False)
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)

    status = await LLMService.get_lifecycle_status()
    assert status["last_demand_utc"] is not None
    assert status["idle_seconds"] is not None
    assert status["container_reachable"] is False


@pytest.mark.asyncio
async def test_unload_ollama_model_success(monkeypatch):
    calls = {}

    class _Client:
        async def post(self, endpoint, json):
            calls["endpoint"] = endpoint
            calls["payload"] = json
            return _FakeResponse(status_code=200)

    monkeypatch.setattr(settings, "TEXT_MODEL_ID", OLLAMA_MODEL, raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: _Client()))

    await LLMService._unload_ollama_model()
    assert calls["endpoint"] == "/api/generate"
    assert calls["payload"]["keep_alive"] == 0


@pytest.mark.asyncio
async def test_unload_ollama_model_exception_is_non_fatal(monkeypatch):
    class _Client:
        async def post(self, endpoint, json):
            raise RuntimeError("boom")

    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: _Client()))
    await LLMService._unload_ollama_model()


@pytest.mark.asyncio
async def test_list_ollama_models_skips_invalid_entries(monkeypatch):
    fake_client = _FakeClient(tags_payload={"models": [1, {"name": "  "}, {"name": OLLAMA_MODEL}]})
    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    models = await LLMService._list_ollama_models()
    assert models == [OLLAMA_MODEL]


@pytest.mark.asyncio
async def test_list_ollama_models_returns_empty_on_exception(monkeypatch):
    class _Client:
        async def get(self, endpoint):
            raise RuntimeError("network")

    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: _Client()))
    assert await LLMService._list_ollama_models() == []


@pytest.mark.asyncio
async def test_resolve_generation_model_ollama_success(monkeypatch):
    fake_client = _FakeClient(tags_payload={"models": [{"name": OLLAMA_MODEL}]})
    monkeypatch.setattr(settings, "LLM_BACKEND", "ollama", raising=False)
    monkeypatch.setattr(settings, "TEXT_MODEL_ID", OLLAMA_MODEL, raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: fake_client))

    assert await LLMService._resolve_generation_model() == OLLAMA_MODEL


@pytest.mark.asyncio
async def test_request_started_heartbeat_failure_is_non_fatal(monkeypatch, tmp_path):
    import app.services.llm_service as llm_module

    original_touch = llm_module.Path.touch

    def _boom_touch(self):
        raise OSError("touch failed")

    monkeypatch.setattr(llm_module.Path, "touch", _boom_touch)
    monkeypatch.setattr(settings, "LLM_DEMAND_HEARTBEAT_FILE", str(tmp_path / "hb"), raising=False)

    LLMService._active_requests = 0
    await LLMService._request_started()
    assert LLMService._active_requests == 1

    monkeypatch.setattr(llm_module.Path, "touch", original_touch)


@pytest.mark.asyncio
async def test_generate_with_ollama_empty_response_raises(monkeypatch):
    from app.services.llm_service import LLMUnavailableError

    async def _fake_post(*_args, **_kwargs):
        return _FakeResponse(payload={"response": ""})

    monkeypatch.setattr(LLMService, "_post_with_startup_retry", classmethod(lambda cls, endpoint, payload: _fake_post()))

    with pytest.raises(LLMUnavailableError):
        await LLMService._generate_with_ollama(
            model=OLLAMA_MODEL,
            prompt="hello",
            max_tokens=32,
            temperature=0.2,
            top_p=0.9,
        )


@pytest.mark.asyncio
async def test_build_stream_retry_window_applies_interval_floor(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STARTUP_WAIT_SECONDS", 0, raising=False)
    monkeypatch.setattr(settings, "LLM_RETRY_INTERVAL_SECONDS", 0.01, raising=False)

    import time
    before = time.monotonic()
    deadline, interval = LLMService._build_stream_retry_window()
    assert interval == 0.1
    assert deadline >= before


@pytest.mark.asyncio
async def test_iter_ollama_stream_tokens_yields_until_done():
    class _Resp:
        async def aiter_lines(self):
            yield _json.dumps({"response": "A", "done": False})
            yield _json.dumps({"response": "", "done": True})
            yield _json.dumps({"response": "B", "done": False})

    out = []
    async for tok in LLMService._iter_ollama_stream_tokens(_Resp()):
        out.append(tok)
    assert out == ["A"]


@pytest.mark.asyncio
async def test_iter_openai_stream_tokens_yields_token_line():
    class _Resp:
        async def aiter_lines(self):
            yield f"data: {_json.dumps({'choices': [{'text': 'X'}]})}"
            yield "data: [DONE]"

    out = []
    async for tok in LLMService._iter_openai_stream_tokens(_Resp()):
        out.append(tok)
    assert out == ["X"]


@pytest.mark.asyncio
async def test_stream_ollama_with_retry_yields_streamed_tokens(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield _json.dumps({"response": "tok", "done": False})
            yield _json.dumps({"response": "", "done": True})

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Client:
        def stream(self, *_args, **_kwargs):
            return _StreamCtx()

    monkeypatch.setattr(LLMService, "_build_stream_retry_window", staticmethod(lambda: (9999999999.0, 0.1)))

    out = []
    async for tok in LLMService._stream_ollama_with_retry(
        client=_Client(),
        payload={"x": 1},
        prompt="p",
        max_tokens=32,
        temperature=0.2,
        top_p=0.9,
        stop=None,
    ):
        out.append(tok)
    assert out == ["tok"]


@pytest.mark.asyncio
async def test_stream_ollama_with_retry_falls_back_when_no_tokens(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield _json.dumps({"response": "", "done": True})

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Client:
        def stream(self, *_args, **_kwargs):
            return _StreamCtx()

    async def _fallback(**_kwargs):
        yield "fallback-token"

    monkeypatch.setattr(LLMService, "_yield_fallback_non_stream_text", classmethod(lambda cls, **kwargs: _fallback()))

    out = []
    async for tok in LLMService._stream_ollama_with_retry(
        client=_Client(),
        payload={"x": 1},
        prompt="p",
        max_tokens=32,
        temperature=0.2,
        top_p=0.9,
        stop=None,
    ):
        out.append(tok)
    assert out == ["fallback-token"]


@pytest.mark.asyncio
async def test_stream_openai_with_retry_yields_tokens(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield f"data: {_json.dumps({'choices': [{'text': 'open'}]})}"
            yield "data: [DONE]"

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Client:
        def stream(self, *_args, **_kwargs):
            return _StreamCtx()

    out = []
    async for tok in LLMService._stream_openai_completions_with_retry(client=_Client(), payload={"x": 1}):
        out.append(tok)
    assert out == ["open"]


@pytest.mark.asyncio
async def test_generate_reraises_llm_configuration_error(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return None

    async def _raise_cfg(*_args, **_kwargs):
        raise LLMConfigurationError("bad model")

    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _raise_cfg()))

    with pytest.raises(LLMConfigurationError):
        await LLMService.generate("hello")


@pytest.mark.asyncio
async def test_generate_stream_reraises_llm_unavailable(monkeypatch):
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_unavailable(*_args, **_kwargs):
        raise LLMUnavailableError("down")
        yield  # pragma: no cover

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: object()))
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_stream_openai_completions_with_retry", classmethod(lambda cls, **kwargs: _raise_unavailable()))

    with pytest.raises(LLMUnavailableError):
        async for _ in LLMService.generate_stream("hello"):
            pass


@pytest.mark.asyncio
async def test_generate_stream_wraps_http_error(monkeypatch):
    import httpx
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_http(*_args, **_kwargs):
        raise httpx.HTTPError("stream-http")
        yield  # pragma: no cover

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "get_client", classmethod(lambda cls: object()))
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_stream_openai_completions_with_retry", classmethod(lambda cls, **kwargs: _raise_http()))

    with pytest.raises(LLMUnavailableError):
        async for _ in LLMService.generate_stream("hello"):
            pass


@pytest.mark.asyncio
async def test_get_lifecycle_status_heartbeat_stat_and_probe_exceptions(monkeypatch):
    import app.services.llm_service as llm_module

    class _BadPath:
        def __init__(self, *_args, **_kwargs):
            pass

        def exists(self):
            return True

        def stat(self):
            raise OSError("stat fail")

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, endpoint):
            raise RuntimeError("probe fail")

    monkeypatch.setattr(llm_module, "Path", _BadPath)
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _ProbeClient)
    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)

    status = await LLMService.get_lifecycle_status()
    assert status["last_demand_utc"] is None
    assert status["idle_seconds"] is None
    assert status["container_reachable"] is False


@pytest.mark.asyncio
async def test_stream_ollama_with_retry_connect_error_calls_wait_or_raise(monkeypatch):
    import httpx
    from app.services.llm_service import LLMUnavailableError

    request = httpx.Request("POST", "http://localhost/api/generate")
    called = {"wait": 0}

    class _Client:
        def stream(self, *_args, **_kwargs):
            raise httpx.ConnectError("down", request=request)

    async def _wait(*_args, **_kwargs):
        called["wait"] += 1
        raise LLMUnavailableError("stop")

    monkeypatch.setattr(LLMService, "_wait_or_raise_stream_retry", classmethod(lambda cls, **kwargs: _wait()))

    with pytest.raises(LLMUnavailableError):
        async for _ in LLMService._stream_ollama_with_retry(
            client=_Client(),
            payload={"x": 1},
            prompt="p",
            max_tokens=32,
            temperature=0.2,
            top_p=0.9,
            stop=None,
        ):
            pass

    assert called["wait"] == 1


@pytest.mark.asyncio
async def test_stream_openai_with_retry_connect_error_calls_wait_or_raise(monkeypatch):
    import httpx
    from app.services.llm_service import LLMUnavailableError

    request = httpx.Request("POST", "http://localhost/v1/completions")
    called = {"wait": 0}

    class _Client:
        def stream(self, *_args, **_kwargs):
            raise httpx.ConnectError("down", request=request)

    async def _wait(*_args, **_kwargs):
        called["wait"] += 1
        raise LLMUnavailableError("stop")

    monkeypatch.setattr(LLMService, "_wait_or_raise_stream_retry", classmethod(lambda cls, **kwargs: _wait()))

    with pytest.raises(LLMUnavailableError):
        async for _ in LLMService._stream_openai_completions_with_retry(client=_Client(), payload={"x": 1}):
            pass

    assert called["wait"] == 1


@pytest.mark.asyncio
async def test_generate_reraises_llm_unavailable_error(monkeypatch):
    from app.services.llm_service import LLMUnavailableError

    async def _noop(*_args, **_kwargs):
        return None

    async def _resolved_model(*_args, **_kwargs):
        return VLLM_MODEL

    async def _raise_unavailable(*_args, **_kwargs):
        raise LLMUnavailableError("no output")

    monkeypatch.setattr(settings, "LLM_BACKEND", "vllm", raising=False)
    monkeypatch.setattr(LLMService, "_request_started", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_request_finished", classmethod(lambda cls: _noop()))
    monkeypatch.setattr(LLMService, "_resolve_generation_model", classmethod(lambda cls: _resolved_model()))
    monkeypatch.setattr(LLMService, "_generate_with_openai_completions", classmethod(lambda cls, **kwargs: _raise_unavailable()))

    with pytest.raises(LLMUnavailableError):
        await LLMService.generate("hello")
