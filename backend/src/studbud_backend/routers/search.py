from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import Document, DocumentChunk, DocumentStatus, User
from ..providers.embeddings import get_embeddings
from ..schemas import SearchResponse, SearchResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])

RRF_K = 60
CANDIDATES = 30


def _snippet(text: str, query: str, section_title: str | None = None, limit: int = 260) -> str:
    cleaned = re.sub(r"#{1,6}\s*", "", text)
    if section_title:
        cleaned = re.sub(
            rf"^\s*{re.escape(section_title)}\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    if len(collapsed) <= limit:
        return collapsed
    tokens = [token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2]
    lowered = collapsed.lower()
    position = -1
    for token in tokens:
        position = lowered.find(token)
        if position != -1:
            break
    if position == -1:
        return collapsed[:limit].rstrip() + "…"
    start = max(0, position - limit // 3)
    end = min(len(collapsed), start + limit)
    snippet = collapsed[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(collapsed):
        snippet = snippet + "…"
    return snippet


@router.get("", response_model=SearchResponse)
async def search_documents(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=15, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    query = q.strip()
    if not query:
        return SearchResponse(query=q, results=[])

    candidates: dict[uuid.UUID, dict] = {}

    try:
        provider = get_embeddings()
        vector = await provider.embed_query(query)
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = (
            await db.execute(
                select(DocumentChunk, Document.file_name, distance.label("distance"))
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.user_id == user.id,
                    Document.status == DocumentStatus.ready,
                    DocumentChunk.embedding.is_not(None),
                    DocumentChunk.embedding_model == provider.model_id,
                )
                .order_by(distance)
                .limit(CANDIDATES)
            )
        ).all()

        for rank, (chunk, file_name, _distance) in enumerate(rows, start=1):
            candidates[chunk.id] = {
                "chunk": chunk,
                "document_name": file_name,
                "score": 1 / (RRF_K + rank),
            }
    except Exception:
        logger.exception("Vector search failed; continuing with keyword search")
        db.rollback()

    tsquery = func.plainto_tsquery("english", query)
    fts_rows = (
        await db.execute(
            select(
                DocumentChunk,
                Document.file_name,
                func.ts_rank(DocumentChunk.search_vector, tsquery).label("rank"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.user_id == user.id,
                Document.status == DocumentStatus.ready,
                DocumentChunk.search_vector.op("@@")(tsquery),
            )
            .order_by(func.ts_rank(DocumentChunk.search_vector, tsquery).desc())
            .limit(CANDIDATES)
        )
    ).all()

    for rank, (chunk, file_name, _rank) in enumerate(fts_rows, start=1):
        existing = candidates.get(chunk.id)
        if existing:
            existing["score"] += 1 / (RRF_K + rank)
        else:
            candidates[chunk.id] = {
                "chunk": chunk,
                "document_name": file_name,
                "score": 1 / (RRF_K + rank),
            }

    ranked = sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:limit]
    results = [
        SearchResult(
            chunk_id=item["chunk"].id,
            document_id=item["chunk"].document_id,
            document_name=item["document_name"],
            section_title=item["chunk"].section_title,
            page_start=item["chunk"].page_start,
            page_end=item["chunk"].page_end,
            snippet=_snippet(item["chunk"].text, query, item["chunk"].section_title),
            score=round(item["score"], 6),
        )
        for item in ranked
    ]
    return SearchResponse(query=query, results=results)
