"""LLM 호출부. 비즈니스 로직(`extractor.py`)은 여기 무엇이 있는지 몰라도 된다."""

from .base import LlmClient, LlmError
from .ollama import OllamaClient
from .stub import StubLlmClient

__all__ = ["LlmClient", "LlmError", "OllamaClient", "StubLlmClient"]
