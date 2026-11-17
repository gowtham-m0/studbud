"""Smoke-test Groq chat and embeddings before indexing a real library.

Usage:
    cd backend
    uv run python scripts/smoke_groq.py
"""

import asyncio
import sys

import pymupdf as fitz

from studbud_backend.config import get_settings
from studbud_backend.providers.chat import ChatError, GroqChat
from studbud_backend.providers.embeddings import EmbeddingError, get_embeddings
from studbud_backend.providers.vision import VisionError, get_vision_provider


def diagram_png() -> bytes:
    document = fitz.open()
    page = document.new_page(width=320, height=160)
    page.insert_text((20, 40), "TCP three-way handshake", fontsize=14, fontname="hebo")
    page.insert_text((20, 80), "CLIENT  --SYN-->  SERVER", fontsize=11, fontname="helv")
    page.insert_text((20, 100), "CLIENT  <--SYN-ACK--  SERVER", fontsize=11, fontname="helv")
    page.insert_text((20, 120), "CLIENT  --ACK-->  SERVER", fontsize=11, fontname="helv")
    pixmap = page.get_pixmap(dpi=120, alpha=False)
    data = pixmap.tobytes("png")
    document.close()
    return data


async def main() -> int:
    settings = get_settings()
    if not settings.groq_api_key:
        print("GROQ_API_KEY is not set. Add it to backend/.env first.")
        return 1

    try:
        provider = get_embeddings()
        embeddings = await provider.embed_documents(["TCP three-way handshake"])
        query_vector = await provider.embed_query("how does TCP connect?")
    except EmbeddingError as exc:
        print(f"Embeddings failed: {exc}")
        print("Set EMBEDDING_PROVIDER=hash for offline use, or install fastembed.")
        return 1
    print(
        f"Embeddings OK: provider={type(provider).__name__} "
        f"model={provider.model_id} dimensions={len(embeddings[0])} "
        f"query_dimensions={len(query_vector)}"
    )

    try:
        result = await GroqChat().complete_json(
            "Return a JSON object with a single key `status` whose value is `ok`.",
            'Respond with {"status":"ok"}.',
        )
    except ChatError as exc:
        print(f"Chat failed: {exc}")
        print(f"Model tried: {settings.groq_chat_model}")
        return 1
    print(f"Chat OK: model={result.model} content={result.content[:100]!r}")

    vision = get_vision_provider()
    if vision is None:
        print(
            "Vision captioning skipped: set GEMINI_API_KEY (auto), or "
            "VISION_PROVIDER=groq with a working GROQ_VISION_MODEL."
        )
    else:
        try:
            caption = await vision.describe(
                diagram_png(),
                "image/png",
                "Describe this diagram in one sentence for a student.",
            )
        except VisionError as exc:
            print(f"Vision captioning failed (optional): {exc}")
            print(f"Vision provider: {type(vision).__name__} model={vision.model_id}")
        else:
            print(
                f"Vision OK: provider={type(vision).__name__} "
                f"model={vision.model_id} caption={caption[:140]!r}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
