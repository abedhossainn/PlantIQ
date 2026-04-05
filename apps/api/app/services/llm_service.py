"""
Generic LLM Client Service - OpenAI-compatible inference for RAG responses.

Supports text generation with streaming via any OpenAI-compatible backend
(e.g., vLLM, Ollama, Docker Model Runner, llama.cpp server).
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when runtime LLM configuration is invalid."""


class LLMUnavailableError(RuntimeError):
    """Raised when runtime LLM service cannot generate output."""


class LLMService:
    """Service for interacting with OpenAI-compatible LLM inference servers.
    
    Architecture:
    - Manages httpx client lifecycle for async HTTP calls to OpenAI-compatible backends
    - Tracks active requests to signal demand to external orchestrators (e.g., Ollama container start/stop)
    - Provides both streaming and non-streaming generation paths
    - Implements fallback strategy: if streaming fails, retry with non-streaming mode
    
    Supported Backends:
    - vLLM (recommended for production)
    - Ollama (local inference with GPU, supports model unloading)
    - llama.cpp server (lightweight CPU inference)
    - Any OpenAI /v1/completions or /v1/chat/completions compatible server
    """

    # Singleton httpx client for async requests (reused across all LLM calls)
    _client: Optional[httpx.AsyncClient] = None
    
    # Tracks in-flight LLM requests. Used for demand signaling to orchestrators.
    _active_requests: int = 0
    
    # Lock ensures thread-safe request counting and model unload decisions.
    _request_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Get or create httpx client singleton."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(
                base_url=f"http://{settings.LLM_HOST}:{settings.LLM_PORT}",
                timeout=settings.LLM_TIMEOUT,
            )
            logger.info("Connected to LLM backend at %s:%s", settings.LLM_HOST, settings.LLM_PORT)
        return cls._client

    @classmethod
    async def _request_started(cls) -> None:
        async with cls._request_lock:
            cls._active_requests += 1

        # Demand signal for external supervisors that start/stop llm container on demand.
        try:
            heartbeat_path = Path(settings.LLM_DEMAND_HEARTBEAT_FILE)
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_path.touch()
        except Exception as exc:
            logger.debug("LLM demand heartbeat update failed (non-fatal): %s", exc)

    @classmethod
    async def _request_finished(cls) -> None:
        unload_required = False
        async with cls._request_lock:
            cls._active_requests = max(0, cls._active_requests - 1)
            unload_required = (
                cls._active_requests == 0
                and settings.LLM_UNLOAD_AFTER_REQUEST
                and settings.LLM_BACKEND.lower() == "ollama"
            )

        if unload_required:
            await cls._unload_ollama_model()

    @classmethod
    async def _unload_ollama_model(cls) -> None:
        """Best-effort unload of current text model from Ollama GPU memory."""
        client = cls.get_client()
        payload = {
            "model": settings.TEXT_MODEL_ID,
            "keep_alive": 0,
        }
        try:
            # Native Ollama endpoint for memory residency control.
            await client.post("/api/generate", json=payload)
            logger.info("Unloaded Ollama model from memory: %s", settings.TEXT_MODEL_ID)
        except Exception as exc:
            logger.warning("Could not unload Ollama model (non-fatal): %s", exc)

    @classmethod
    async def _list_ollama_models(cls) -> List[str]:
        """Return model names installed on Ollama (best effort)."""
        if settings.LLM_BACKEND.lower() != "ollama":
            return []

        client = cls.get_client()
        try:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json() or {}
            models = payload.get("models") or []
            names: List[str] = []
            for model_entry in models:
                if not isinstance(model_entry, dict):
                    continue
                model_name = model_entry.get("name")
                if isinstance(model_name, str) and model_name.strip():
                    names.append(model_name.strip())
            return names
        except Exception as exc:
            logger.debug("Unable to list Ollama models (non-fatal): %s", exc)
            return []

    @classmethod
    async def _resolve_generation_model(cls) -> str:
        """Resolve and validate runtime model ID for generation requests."""
        configured_model = settings.TEXT_MODEL_ID
        if settings.LLM_BACKEND.lower() != "ollama":
            return configured_model

        available_models = await cls._list_ollama_models()
        if not available_models:
            raise LLMConfigurationError(
                "Ollama backend is configured but no local models are installed. "
                f"Expected configured model: '{configured_model}'."
            )

        if configured_model not in available_models:
            raise LLMConfigurationError(
                "Configured Ollama model is not installed. "
                f"Configured: '{configured_model}'. Installed: {available_models}."
            )

        return configured_model

    @staticmethod
    def _prepare_ollama_prompt(model: str, prompt: str) -> str:
        """Normalize prompt for Ollama models that default to reasoning traces."""
        normalized_model = (model or "").strip().lower()
        normalized_prompt = (prompt or "").lstrip()
        if normalized_model.startswith("qwen3") and not normalized_prompt.startswith("/no_think"):
            return f"/no_think\n{normalized_prompt}"
        return prompt

    @classmethod
    def _build_ollama_generate_payload(
        cls,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        stream: bool,
    ) -> dict:
        """Build Ollama-native generate payload with thinking disabled."""
        return {
            "model": model,
            "prompt": cls._prepare_ollama_prompt(model, prompt),
            "stream": stream,
            "think": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            },
        }

    @classmethod
    async def _post_with_startup_retry(cls, endpoint: str, payload: dict) -> httpx.Response:
        """POST with connection retry to allow on-demand LLM container startup."""
        client = cls.get_client()
        wait_seconds = max(0, settings.LLM_STARTUP_WAIT_SECONDS)
        interval = max(0.1, settings.LLM_RETRY_INTERVAL_SECONDS)
        deadline = time.monotonic() + wait_seconds
        attempt = 0

        while True:
            attempt += 1
            try:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if time.monotonic() >= deadline:
                    logger.error("LLM backend unavailable after %s attempts: %s", attempt, exc)
                    raise
                logger.info(
                    "LLM backend not reachable yet (attempt %s); retrying in %.1fs",
                    attempt,
                    interval,
                )
                await asyncio.sleep(interval)

    @classmethod
    async def generate(
        cls,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """Generate text completion (non-streaming)."""
        await cls._request_started()

        if max_tokens is None:
            max_tokens = settings.LLM_MAX_TOKENS
        if temperature is None:
            temperature = settings.LLM_TEMPERATURE
        if top_p is None:
            top_p = settings.LLM_TOP_P

        runtime_model = await cls._resolve_generation_model()

        try:
            if settings.LLM_BACKEND.lower() == "ollama":
                payload = cls._build_ollama_generate_payload(
                    model=runtime_model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stream=False,
                )
                response = await cls._post_with_startup_retry("/api/generate", payload)
                result = response.json() or {}
                text = str(result.get("response") or "")
                if text:
                    logger.info("Generated %s characters", len(text))
                    return text.strip()
                raise LLMUnavailableError("LLM returned an empty completion text response.")

            payload = {
                "model": runtime_model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stop": stop or [],
            }
            response = await cls._post_with_startup_retry("/v1/completions", payload)
            result = response.json()

            if "choices" in result and len(result["choices"]) > 0:
                text = result["choices"][0].get("text", "")
                if text:
                    logger.info("Generated %s characters", len(text))
                    return text.strip()
                raise LLMUnavailableError("LLM returned an empty completion text response.")

            raise LLMUnavailableError("LLM response did not include completion choices.")
        except (LLMConfigurationError, LLMUnavailableError):
            raise
        except httpx.HTTPError as exc:
            logger.error("LLM request failed: %s", exc)
            raise LLMUnavailableError(f"LLM request failed: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during generation: %s", exc)
            raise LLMUnavailableError(f"Unexpected generation error: {exc}") from exc
        finally:
            await cls._request_finished()

    @classmethod
    async def generate_stream(
        cls,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> AsyncIterator[str]:
        """Generate text completion with streaming."""
        client = cls.get_client()
        await cls._request_started()

        if max_tokens is None:
            max_tokens = settings.LLM_MAX_TOKENS
        if temperature is None:
            temperature = settings.LLM_TEMPERATURE
        if top_p is None:
            top_p = settings.LLM_TOP_P

        runtime_model = await cls._resolve_generation_model()

        try:
            wait_seconds = max(0, settings.LLM_STARTUP_WAIT_SECONDS)
            interval = max(0.1, settings.LLM_RETRY_INTERVAL_SECONDS)
            deadline = time.monotonic() + wait_seconds
            attempt = 0

            if settings.LLM_BACKEND.lower() == "ollama":
                payload = cls._build_ollama_generate_payload(
                    model=runtime_model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stream=True,
                )

                while True:
                    attempt += 1
                    yielded_any_token = False
                    try:
                        async with client.stream("POST", "/api/generate", json=payload) as response:
                            response.raise_for_status()

                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line)
                                except json.JSONDecodeError:
                                    continue

                                text = str(chunk.get("response") or "")
                                if text:
                                    yielded_any_token = True
                                    yield text

                                if chunk.get("done"):
                                    break

                        if not yielded_any_token:
                            logger.warning(
                                "Ollama stream produced no token text; falling back to non-stream generation"
                            )
                            fallback_text = await cls.generate(
                                prompt=prompt,
                                max_tokens=max_tokens,
                                temperature=temperature,
                                top_p=top_p,
                                stop=stop,
                            )
                            if fallback_text:
                                yield fallback_text
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                        if time.monotonic() >= deadline:
                            logger.error("LLM streaming backend unavailable after %s attempts: %s", attempt, exc)
                            raise LLMUnavailableError(f"LLM streaming backend unavailable: {exc}") from exc
                        logger.info(
                            "LLM streaming backend not reachable yet (attempt %s); retrying in %.1fs",
                            attempt,
                            interval,
                        )
                        await asyncio.sleep(interval)
            else:
                payload = {
                    "model": runtime_model,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "stop": stop or [],
                    "stream": True,
                }

                while True:
                    attempt += 1
                    try:
                        async with client.stream("POST", "/v1/completions", json=payload) as response:
                            response.raise_for_status()

                            async for line in response.aiter_lines():
                                if not line:
                                    continue

                                if line.startswith("data: "):
                                    data = line[6:]

                                    if data == "[DONE]":
                                        break

                                    try:
                                        chunk = json.loads(data)
                                        if "choices" in chunk and len(chunk["choices"]) > 0:
                                            text = chunk["choices"][0].get("text", "")
                                            if text:
                                                yield text
                                    except json.JSONDecodeError:
                                        continue
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                        if time.monotonic() >= deadline:
                            logger.error("LLM streaming backend unavailable after %s attempts: %s", attempt, exc)
                            raise LLMUnavailableError(f"LLM streaming backend unavailable: {exc}") from exc
                        logger.info(
                            "LLM streaming backend not reachable yet (attempt %s); retrying in %.1fs",
                            attempt,
                            interval,
                        )
                        await asyncio.sleep(interval)
        except (LLMConfigurationError, LLMUnavailableError):
            raise
        except httpx.HTTPError as exc:
            logger.error("LLM streaming request failed: %s", exc)
            raise LLMUnavailableError(f"LLM streaming request failed: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during streaming: %s", exc)
            raise LLMUnavailableError(f"Unexpected streaming error: {exc}") from exc
        finally:
            await cls._request_finished()

    @classmethod
    async def health_check(cls) -> bool:
        """Check if LLM server is healthy."""
        client = cls.get_client()

        try:
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as exc:
            logger.error("LLM health check failed: %s", exc)
            return False

    @classmethod
    async def get_lifecycle_status(cls) -> dict:
        """Return current LLM lifecycle state for observability."""
        heartbeat_path = Path(settings.LLM_DEMAND_HEARTBEAT_FILE)

        last_demand_iso: Optional[str] = None
        idle_seconds: Optional[float] = None
        try:
            if heartbeat_path.exists():
                mtime = heartbeat_path.stat().st_mtime
                last_demand_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                idle_seconds = round(time.time() - mtime, 1)
        except Exception:
            pass

        # Lightweight liveness probe — short timeout, no retry.
        container_reachable = False
        try:
            async with httpx.AsyncClient(
                base_url=f"http://{settings.LLM_HOST}:{settings.LLM_PORT}",
                timeout=1.5,
            ) as probe:
                response = await probe.get("/v1/models")
                container_reachable = response.status_code < 500
        except Exception:
            container_reachable = False

        available_models = await cls._list_ollama_models()
        configured_model_available = (
            settings.TEXT_MODEL_ID in available_models
            if available_models
            else None
        )

        return {
            "backend": settings.LLM_BACKEND,
            "model": settings.TEXT_MODEL_ID,
            "configured_model": settings.TEXT_MODEL_ID,
            "configured_model_available": configured_model_available,
            "available_models": available_models,
            "host": settings.LLM_HOST,
            "port": settings.LLM_PORT,
            "container_reachable": container_reachable,
            "active_requests": cls._active_requests,
            "unload_after_request": settings.LLM_UNLOAD_AFTER_REQUEST,
            "startup_wait_seconds": settings.LLM_STARTUP_WAIT_SECONDS,
            "last_demand_utc": last_demand_iso,
            "idle_seconds": idle_seconds,
        }
