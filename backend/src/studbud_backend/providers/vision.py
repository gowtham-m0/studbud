from __future__ import annotations

import asyncio
import base64
import logging
from functools import lru_cache
from typing import Protocol

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class VisionError(RuntimeError):
    pass


class VisionProvider(Protocol):
    model_id: str

    async def describe(self, image_bytes: bytes, mime_type: str, prompt: str) -> str: ...


class GroqVision:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise VisionError("GROQ_API_KEY is not configured.")
        self.api_key = settings.groq_api_key
        self.base_url = settings.groq_base_url.rstrip("/")
        self.model_id = settings.groq_vision_model
        self.model = self.model_id

    async def describe(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 350,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", headers=headers, json=payload
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise VisionError(f"Vision provider returned {response.status_code}.")
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise VisionError("Vision provider returned an empty description.")
                    return content.strip()[:800]
                except (httpx.HTTPError, KeyError, IndexError, VisionError) as exc:
                    last_error = exc
                    if attempt == 2:
                        break
                    await asyncio.sleep(2**attempt)

        raise VisionError(f"Vision request failed: {last_error}")


class GeminiVision:
    """Google Gemini vision through the Generative Language API."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise VisionError("GEMINI_API_KEY is not configured.")
        self.api_key = settings.gemini_api_key
        self.base_url = settings.gemini_base_url.rstrip("/")
        self.model_id = settings.gemini_vision_model
        self.model = self.model_id

    async def describe(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": encoded,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 400,
            },
        }

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/models/{self.model}:generateContent",
                        params={"key": self.api_key},
                        json=payload,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise VisionError(f"Vision provider returned {response.status_code}.")
                    response.raise_for_status()
                    candidates = response.json().get("candidates") or []
                    parts = candidates[0]["content"]["parts"] if candidates else []
                    text = " ".join(
                        part["text"] for part in parts if isinstance(part.get("text"), str)
                    ).strip()
                    if not text:
                        raise VisionError("Vision provider returned an empty description.")
                    return text[:800]
                except (httpx.HTTPError, KeyError, IndexError, VisionError) as exc:
                    last_error = exc
                    if attempt == 2:
                        break
                    await asyncio.sleep(2**attempt)

        raise VisionError(f"Vision request failed: {last_error}")


@lru_cache
def get_vision_provider() -> VisionProvider | None:
    settings = get_settings()
    if not settings.figure_captioning_enabled:
        return None

    provider = settings.vision_provider.lower()
    if provider == "none":
        return None

    # Auto is Gemini-only. Groq's vision catalog has been retired; selecting Groq
    # blindly adds failed calls to every ingestion. Use VISION_PROVIDER=groq when a
    # working Groq vision model is available.
    if provider in {"auto", "gemini"} and settings.gemini_api_key:
        try:
            return GeminiVision()
        except VisionError as exc:
            logger.warning("Gemini vision unavailable: %s", exc)
            return None

    if provider == "groq" and settings.groq_api_key and settings.groq_vision_model.strip():
        try:
            return GroqVision()
        except VisionError as exc:
            logger.warning("Groq vision unavailable: %s", exc)
            return None

    logger.info("No vision provider configured; figures will be stored without captions.")
    return None
