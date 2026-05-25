"""Minimal Ollama client for chat-based extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class OllamaError(RuntimeError):
    """Raised when the Ollama API call fails."""


@dataclass(slots=True)
class OllamaClient:
    base_url: str
    timeout_seconds: int = 600

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if response_format is not None:
            payload["format"] = response_format
        if options:
            payload["options"] = options

        body = json.dumps(payload).encode("utf-8")
        url = self.base_url.rstrip("/") + "/api/chat"
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                content = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise OllamaError(f"Failed to reach Ollama at {url}: {exc.reason}") from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned non-JSON response.") from exc

        if "message" not in parsed or "content" not in parsed["message"]:
            raise OllamaError("Ollama response missing message content.")
        return parsed
