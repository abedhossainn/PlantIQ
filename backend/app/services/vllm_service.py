"""
vLLM Client Service - LLM inference for RAG responses.

Handles text generation with streaming support using vLLM server.
"""
import logging
import httpx
from typing import AsyncIterator, List, Dict, Any, Optional
import json

from ..core.config import settings

logger = logging.getLogger(__name__)


class VLLMService:
    """Service for interacting with vLLM inference server."""
    
    _client: Optional[httpx.AsyncClient] = None
    
    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Get or create httpx client singleton."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(
                base_url=f"http://{settings.VLLM_HOST}:{settings.VLLM_PORT}",
                timeout=settings.VLLM_TIMEOUT,
            )
            logger.info(f"Connected to vLLM at {settings.VLLM_HOST}:{settings.VLLM_PORT}")
        return cls._client
    
    @classmethod
    async def generate(
        cls,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """
        Generate text completion (non-streaming).
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            stop: Stop sequences
            
        Returns:
            Generated text
        """
        client = cls.get_client()
        
        if max_tokens is None:
            max_tokens = settings.VLLM_MAX_TOKENS
        if temperature is None:
            temperature = settings.VLLM_TEMPERATURE
        if top_p is None:
            top_p = settings.VLLM_TOP_P
        
        payload = {
            "model": settings.VLLM_MODEL,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stop": stop or [],
        }
        
        try:
            response = await client.post("/v1/completions", json=payload)
            response.raise_for_status()
            result = response.json()
            
            # Extract generated text
            if "choices" in result and len(result["choices"]) > 0:
                text = result["choices"][0]["text"]
                logger.info(f"Generated {len(text)} characters")
                return text.strip()
            else:
                logger.error("No completion in vLLM response")
                return ""
                
        except httpx.HTTPError as e:
            logger.error(f"vLLM request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during generation: {e}")
            raise
    
    @classmethod
    async def generate_stream(
        cls,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> AsyncIterator[str]:
        """
        Generate text completion with streaming.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            stop: Stop sequences
            
        Yields:
            Token chunks as they're generated
        """
        client = cls.get_client()
        
        if max_tokens is None:
            max_tokens = settings.VLLM_MAX_TOKENS
        if temperature is None:
            temperature = settings.VLLM_TEMPERATURE
        if top_p is None:
            top_p = settings.VLLM_TOP_P
        
        payload = {
            "model": settings.VLLM_MODEL,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stop": stop or [],
            "stream": True,
        }
        
        try:
            async with client.stream("POST", "/v1/completions", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    # vLLM streams in SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix
                        
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
                            
        except httpx.HTTPError as e:
            logger.error(f"vLLM streaming request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during streaming: {e}")
            raise
    
    @classmethod
    async def health_check(cls) -> bool:
        """Check if vLLM server is healthy."""
        client = cls.get_client()
        
        try:
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"vLLM health check failed: {e}")
            return False
