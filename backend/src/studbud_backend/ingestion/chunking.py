from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field

import pymupdf as fitz

logger = logging.getLogger(__name__)

TARGET_TOKENS = 650
OVERLAP_TOKENS = 100
MAX_SECTION_TITLE = 120
MIN_PAGE_CHARS = 30


class PdfExtractionError(RuntimeError):
    pass


@dataclass
class PageText:
    page_number: int
    text: str
    is_scanned: bool


@dataclass
class Section:
    title: str | None
    blocks: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ChunkData:
    index: int
    text: str
    page_start: int
    page_end: int
    section_title: str | None
    token_count: int
    figure_text: str | None = None


@dataclass
class ExtractionResult:
    page_count: int
    pages: list[PageText]
    scanned_pages: list[int]
    ocr_pages: list[int] = field(default_factory=list)

    @property
    def needs_ocr(self) -> bool:
        return bool(self.pages) and len(self.scanned_pages) == len(self.pages)


def extract_pages(
    data: bytes,
    max_pages: int,
    *,
    ocr_enabled: bool = False,
    ocr_language: str = "eng",
    ocr_dpi: int = 200,
) -> ExtractionResult:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises varied exception types
        raise PdfExtractionError("The PDF could not be opened.") from exc

    try:
        if document.page_count == 0:
            raise PdfExtractionError("The PDF has no pages.")
        if document.page_count > max_pages:
            raise PdfExtractionError(
                f"The PDF has {document.page_count} pages; the limit is {max_pages}."
            )

        has_tesseract = shutil.which("tesseract") is not None
        if ocr_enabled and not has_tesseract:
            logger.warning(
                "OCR is enabled but the tesseract executable was not found; "
                "scanned pages will be reported instead."
            )

        pages: list[PageText] = []
        ocr_pages: list[int] = []
        for index in range(document.page_count):
            page = document.load_page(index)
            text = page.get_text("text").strip()
            is_scanned = len(text) < MIN_PAGE_CHARS

            if is_scanned and ocr_enabled and has_tesseract:
                try:
                    textpage = page.get_textpage_ocr(language=ocr_language, dpi=ocr_dpi)
                    ocr_text = page.get_text("text", textpage=textpage).strip()
                except Exception:
                    logger.warning(
                        "OCR failed for page %s; keeping it as scanned",
                        index + 1,
                        exc_info=True,
                    )
                else:
                    if len(ocr_text) >= MIN_PAGE_CHARS:
                        text = ocr_text
                        is_scanned = False
                        ocr_pages.append(index + 1)

            pages.append(
                PageText(
                    page_number=index + 1,
                    text=text,
                    is_scanned=is_scanned,
                )
            )
    finally:
        document.close()

    scanned = [page.page_number for page in pages if page.is_scanned]
    return ExtractionResult(
        page_count=len(pages),
        pages=pages,
        scanned_pages=scanned,
        ocr_pages=ocr_pages,
    )


def _blocks_with_font_sizes(data: bytes) -> list[tuple[int, str, float]]:
    """Return (page_number, block_text, max_font_size) for text blocks."""
    document = fitz.open(stream=data, filetype="pdf")
    blocks: list[tuple[int, str, float]] = []
    try:
        for index in range(document.page_count):
            page = document.load_page(index)
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                text_parts: list[str] = []
                sizes: list[float] = []
                for line in lines:
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            text_parts.append(span_text)
                            sizes.append(float(span.get("size", 0)))
                text = " ".join(text_parts).strip()
                if text:
                    blocks.append((index + 1, text, max(sizes) if sizes else 0.0))
    finally:
        document.close()
    return blocks


def build_sections(data: bytes, extra_text_by_page: dict[int, str] | None = None) -> list[Section]:
    blocks = _blocks_with_font_sizes(data)

    if extra_text_by_page:
        blocks = [block for block in blocks if block[0] not in extra_text_by_page]
        blocks.extend(
            (page_number, text, 0.0)
            for page_number, text in extra_text_by_page.items()
            if text.strip()
        )
        blocks.sort(key=lambda block: block[0])

    if not blocks:
        return []

    weighted_sizes: list[float] = []
    for _, text, size in blocks:
        weighted_sizes.extend([size] * max(1, len(text) // 20))
    weighted_sizes.sort()
    body_size = weighted_sizes[len(weighted_sizes) // 2] if weighted_sizes else 0.0
    heading_threshold = body_size * 1.15 if body_size else 0.0

    sections: list[Section] = [Section(title=None)]
    for page_number, text, size in blocks:
        words = text.split()
        is_heading = (
            heading_threshold > 0
            and size >= heading_threshold
            and len(text) <= MAX_SECTION_TITLE
            and len(words) <= 14
            and not text.endswith(".")
        )
        if is_heading:
            sections.append(Section(title=text))
        else:
            sections[-1].blocks.append((page_number, text))

    sections = [section for section in sections if section.blocks or section.title]
    if sections and sections[0].title is None and not sections[0].blocks:
        sections = sections[1:]
    return sections


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split_long_text(text: str, limit_chars: int) -> list[str]:
    if len(text) <= limit_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > limit_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)

    # A single very long sentence still needs a hard cap.
    capped: list[str] = []
    for piece in pieces:
        if len(piece) <= int(limit_chars * 1.25):
            capped.append(piece)
        else:
            capped.extend(piece[i : i + limit_chars] for i in range(0, len(piece), limit_chars))
    return capped


def _chunk_page_blocks(blocks: list[str], target_chars: int, overlap_chars: int) -> list[str]:
    """Greedy paragraph chunks with a tail overlap, never crossing a page."""
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(_split_long_text(block, target_chars))

    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    index = 0

    while index < len(pieces):
        piece = pieces[index]
        if current and current_chars + len(piece) > target_chars:
            chunks.append("\n\n".join(current))

            tail: list[str] = []
            tail_chars = 0
            for previous in reversed(current):
                if tail_chars + len(previous) > overlap_chars:
                    break
                tail.insert(0, previous)
                tail_chars += len(previous)

            # If the next paragraph is already large, a tail would only bloat it.
            if tail_chars + len(piece) <= target_chars:
                current = tail
                current_chars = tail_chars
            else:
                current = []
                current_chars = 0

        current.append(piece)
        current_chars += len(piece)
        index += 1

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def chunk_sections(
    sections: list[Section],
    figure_text_by_page: dict[int, str] | None = None,
    target_tokens: int = TARGET_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[ChunkData]:
    """Chunk by section and page, with overlap inside each page.

    Page boundaries are strict: a chunk never mixes text from two pages, so every
    citation resolves to a single page. Section titles are carried on every chunk.
    """
    target_chars = target_tokens * 4
    overlap_chars = overlap_tokens * 4
    figures = figure_text_by_page or {}

    chunks: list[ChunkData] = []
    for section in sections:
        if not section.blocks:
            continue

        blocks_by_page: dict[int, list[str]] = {}
        for page_number, text in section.blocks:
            blocks_by_page.setdefault(page_number, []).append(text)

        for page_number in sorted(blocks_by_page):
            page_chunks = _chunk_page_blocks(
                blocks_by_page[page_number], target_chars, overlap_chars
            )
            figure_text = figures.get(page_number)
            for page_chunk in page_chunks:
                text = page_chunk
                if section.title:
                    text = f"## {section.title}\n\n{text}"
                chunks.append(
                    ChunkData(
                        index=len(chunks),
                        text=text,
                        page_start=page_number,
                        page_end=page_number,
                        section_title=section.title,
                        token_count=_estimate_tokens(
                            text + ("\n" + figure_text if figure_text else "")
                        ),
                        figure_text=figure_text,
                    )
                )

    return chunks
