from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str = "mock"
    model: str = ""
    endpoint: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2000


class LLMProvider:
    name = "base"

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        raise NotImplementedError


class MockProvider(LLMProvider):
    name = "mock"

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        # Deterministic fallback used for tests and no-key environments.
        return "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 50"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None, endpoint: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.endpoint = endpoint or "https://api.openai.com/v1/chat/completions"
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is required for provider=openai")

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        data = _post_json(self.endpoint, payload, {"Authorization": f"Bearer {self.api_key}"})
        return data["choices"][0]["message"]["content"]


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-3-5-sonnet-latest", api_key: str | None = None, endpoint: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.endpoint = endpoint or "https://api.anthropic.com/v1/messages"
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for provider=anthropic")

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        system = ""
        converted = []
        for m in messages:
            if m.get("role") == "system":
                system += m.get("content", "") + "\n"
            else:
                converted.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        payload = {"model": self.model, "system": system, "messages": converted, "temperature": temperature, "max_tokens": max_tokens}
        data = _post_json(self.endpoint, payload, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        return "".join(block.get("text", "") for block in data.get("content", []))


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str = "gemini-1.5-pro", api_key: str | None = None, endpoint: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY or GOOGLE_API_KEY is required for provider=gemini")
        self.endpoint = endpoint or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        text = "\n\n".join(f"{m.get('role','user').upper()}: {m.get('content','')}" for m in messages)
        payload = {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        data = _post_json(self.endpoint, payload, {})
        return data["candidates"][0]["content"]["parts"][0]["text"]


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str = "llama3.1", endpoint: str | None = None):
        self.model = model
        self.endpoint = endpoint or os.environ.get("OLLAMA_ENDPOINT") or "http://localhost:11434/api/chat"

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False, "options": {"temperature": temperature, "num_predict": max_tokens}}
        data = _post_json(self.endpoint, payload, {})
        return data.get("message", {}).get("content", "")


class CustomHTTPProvider(LLMProvider):
    name = "custom_http"

    def __init__(self, model: str = "", endpoint: str | None = None, api_key: str | None = None):
        self.model = model
        self.endpoint = endpoint or os.environ.get("AUTOKG_LLM_ENDPOINT")
        self.api_key = api_key or os.environ.get("AUTOKG_LLM_KEY")
        if not self.endpoint:
            raise LLMError("AUTOKG_LLM_ENDPOINT or llm.endpoint is required for provider=custom_http")

    def generate(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 2000) -> str:
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post_json(self.endpoint, payload, headers)
        if "text" in data:
            return data["text"]
        if "content" in data:
            return data["content"]
        if "choices" in data:
            return data["choices"][0].get("message", {}).get("content") or data["choices"][0].get("text", "")
        raise LLMError("Custom HTTP provider response must contain text/content/choices")


def create_llm_provider(config: LLMConfig | dict[str, Any] | None = None) -> LLMProvider:
    if config is None:
        return MockProvider()
    if isinstance(config, dict):
        provider = config.get("provider") or os.environ.get("AUTOKG_LLM_PROVIDER") or "mock"
        cfg = LLMConfig(
            provider=provider,
            model=config.get("model") or os.environ.get("AUTOKG_LLM_MODEL") or "",
            endpoint=config.get("endpoint") or os.environ.get("AUTOKG_LLM_ENDPOINT"),
            api_key_env=config.get("api_key_env"),
            api_key=config.get("api_key"),
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=int(config.get("max_tokens", 2000)),
        )
    else:
        cfg = config
    key = cfg.api_key or (os.environ.get(cfg.api_key_env) if cfg.api_key_env else None)
    p = (cfg.provider or "mock").lower()
    if p in ("mock", "none", "rule"):
        return MockProvider()
    if p == "openai":
        return OpenAIProvider(model=cfg.model or "gpt-4o-mini", api_key=key, endpoint=cfg.endpoint)
    if p == "anthropic":
        return AnthropicProvider(model=cfg.model or "claude-3-5-sonnet-latest", api_key=key, endpoint=cfg.endpoint)
    if p == "gemini":
        return GeminiProvider(model=cfg.model or "gemini-1.5-pro", api_key=key, endpoint=cfg.endpoint)
    if p == "ollama":
        return OllamaProvider(model=cfg.model or "llama3.1", endpoint=cfg.endpoint)
    if p in ("custom", "custom_http", "http"):
        return CustomHTTPProvider(model=cfg.model, endpoint=cfg.endpoint, api_key=key)
    raise LLMError(f"Unknown LLM provider: {cfg.provider}")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise LLMError(f"LLM HTTP call failed: {exc}") from exc
