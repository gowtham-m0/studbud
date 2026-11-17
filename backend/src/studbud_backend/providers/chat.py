from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from functools import lru_cache

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class ChatUnavailable(RuntimeError):
    pass


class ChatError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


class GroqChat:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise ChatUnavailable("GROQ_API_KEY is not configured.")
        self.api_key = settings.groq_api_key
        self.base_url = settings.groq_base_url.rstrip("/")
        self.model = settings.groq_chat_model

    async def complete_json(self, system_prompt: str, user_prompt: str) -> ChatResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 1600,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise ChatError(f"Chat provider returned {response.status_code}.")
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    usage = body.get("usage") or {}
                    return ChatResult(
                        content=content,
                        model=body.get("model", self.model),
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                    )
                except (httpx.HTTPError, KeyError, IndexError, ChatError) as exc:
                    last_error = exc
                    if attempt == 2:
                        break
                    await asyncio.sleep(2**attempt)

        raise ChatError(f"Chat request failed: {last_error}")


def parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ChatError("Model did not return valid JSON.") from None
        return json.loads(text[start : end + 1])


@lru_cache
def get_chat_provider() -> GroqChat:
    return GroqChat()
