"""
Generic LLM Client Service - OpenAI-compatible inference for RAG responses.

Supports text generation with streaming via any OpenAI-compatible backend
(e.g., vLLM, Ollama, Docker Model Runner, llama.cpp server).
"""
import logging
import asyncio
import httpx
from typing import AsyncIterator, List, Optional
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with OpenAI-compatible LLM inference servers."""

    _client: Optional[httpx.AsyncClient] = None
    _active_requests: int = 0
    _request_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Get or create httpx client singleton."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(
                base_url=f"http://{settings.LLM_HOST}:{settings.LLM_PORT}",
                timeout=settings.LLM_TIMEOUT,
            )
            logger.info(f"Connected to LLM backend at {settings.LLM_HOST}:{settings.LLM_PORT}")
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
            logger.debug(f"LLM demand heartbeat update failed (non-fatal): {exc}")

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
            logger.info(f"Unloaded Ollama model from memory: {settings.TEXT_MODEL_ID}")
        except Exception as exc:
            logger.warning(f"Could not unload Ollama model (non-fatal): {exc}")

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
                    logger.error(f"LLM backend unavailable after {attempt} attempts: {exc}")
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
        client = cls.get_client()
        await cls._request_started()

        if max_tokens is None:
            max_tokens = settings.LLM_MAX_TOKENS
        if temperature is None:
            temperature = settings.LLM_TEMPERATURE
        if top_p is None:
            top_p = settings.LLM_TOP_P

        payload = {
            "model": settings.TEXT_MODEL_ID,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stop": stop or [],
        }

        try:
            response = await cls._post_with_startup_retry("/v1/completions", payload)
            result = response.json()

            if "choices" in result and len(result["choices"]) > 0:
                text = result["choices"][0]["text"]
                logger.info(f"Generated {len(text)} characters")
                return text.strip()

            logger.error("No completion in LLM response")
            return ""
        except httpx.HTTPError as e:
            logger.error(f"LLM request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during generation: {e}")
            raise
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

        payload = {
            "model": settings.TEXT_MODEL_ID,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stop": stop or [],
            "stream": True,
        }

        try:
            wait_seconds = max(0, settings.LLM_STARTUP_WAIT_SECONDS)
            interval = max(0.1, settings.LLM_RETRY_INTERVAL_SECONDS)
            deadline = time.monotonic() + wait_seconds
            attempt = 0

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
                        logger.error(f"LLM streaming backend unavailable after {attempt} attempts: {exc}")
                        raise
                    logger.info(
                        "LLM streaming backend not reachable yet (attempt %s); retrying in %.1fs",
                        attempt,
                        interval,
                    )
                    await asyncio.sleep(interval)
        except httpx.HTTPError as e:
            logger.error(f"LLM streaming request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during streaming: {e}")
            raise
        finally:
            await cls._request_finished()

    @classmethod
    async def health_check(cls) -> bool:
        """Check if LLM server is healthy."""
        client = cls.get_client()

        try:
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")
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
                r = await probe.get("/v1/models")
                container_reachable = r.status_code < 500
        except Exception:
            container_reachable = False

        return {
            "backend": settings.LLM_BACKEND,
            "model": settings.TEXT_MODEL_ID,
            "host": settings.LLM_HOST,
            "port": settings.LLM_PORT,
            "container_reachable": container_reachable,
            "active_requests": cls._active_requests,
            "unload_after_request": settings.LLM_UNLOAD_AFTER_REQUEST,
            "startup_wait_seconds": settings.LLM_STARTUP_WAIT_SECONDS,
            "last_demand_utc": last_demand_iso,
            "idle_seconds": idle_seconds,
        }
