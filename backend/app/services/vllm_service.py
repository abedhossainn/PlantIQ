"""
Backward compatibility shim for legacy imports.

Prefer importing LLMService from `app.services.llm_service`.
"""
from .llm_service import LLMService


# Legacy alias retained to avoid breaking tests and older imports.
VLLMService = LLMService
