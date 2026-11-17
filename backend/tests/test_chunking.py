import shutil
from pathlib import Path

import pymupdf as fitz
import pytest

from studbud_backend.ingestion.chunking import (
    ChunkData,
    _chunk_page_blocks,
    build_sections,
    chunk_sections,
    extract_pages,
)

SAMPLE_PDF = Path(__file__).parent / "sample_networks.pdf"


def _sample_bytes() -> bytes:
    return SAMPLE_PDF.read_bytes()


def test_extract_preserves_pages() -> None:
    result = extract_pages(_sample_bytes(), max_pages=200)

    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert not result.needs_ocr
    assert "three-step handshake" in result.pages[1].text


def test_sections_and_page_metadata_survive_chunking() -> None:
    data = _sample_bytes()
    sections = build_sections(data)
    titles = [section.title for section in sections if section.title]
    assert "TCP Three-Way Handshake" in titles
    assert "Flow Control" in titles

    chunks = chunk_sections(sections)
    assert chunks
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))

    handshake_chunks = [
        chunk for chunk in chunks if chunk.section_title == "TCP Three-Way Handshake"
    ]
    assert handshake_chunks
    assert all(chunk.page_start == 2 and chunk.page_end == 2 for chunk in handshake_chunks)
    assert all(1 <= chunk.page_start <= chunk.page_end <= 3 for chunk in chunks)
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert any(chunk.text.startswith("## TCP Three-Way Handshake") for chunk in chunks)


def test_overlap_stays_inside_a_page() -> None:
    paragraphs = [f"Paragraph {index} " + ("word " * 12) for index in range(12)]
    page_chunks = _chunk_page_blocks(paragraphs, target_chars=260, overlap_chars=80)

    assert len(page_chunks) > 1
    first_blocks = set(page_chunks[0].split("\n\n"))
    second_blocks = set(page_chunks[1].split("\n\n"))
    assert first_blocks & second_blocks, "expected an overlapping tail between chunks"


def test_page_and_section_chunking_with_figure_text() -> None:
    sections = build_sections(_sample_bytes())
    chunks = chunk_sections(
        sections,
        figure_text_by_page={2: "Figure on page 2: SYN, SYN-ACK, ACK sequence diagram."},
        target_tokens=80,
        overlap_tokens=20,
    )

    assert chunks
    assert all(isinstance(chunk, ChunkData) for chunk in chunks)
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    handshake = [chunk for chunk in chunks if chunk.section_title == "TCP Three-Way Handshake"]
    assert handshake
    assert all(chunk.page_start == 2 for chunk in handshake)
    assert all(
        chunk.figure_text and "SYN, SYN-ACK, ACK" in chunk.figure_text for chunk in handshake
    )
    assert all(chunk.text.startswith("## TCP Three-Way Handshake") for chunk in handshake)


def test_scanned_pdf_detection() -> None:
    document = fitz.open()
    for _ in range(2):
        document.new_page()
    data = document.tobytes()
    document.close()

    result = extract_pages(data, max_pages=200)
    assert result.page_count == 2
    assert result.needs_ocr


def _raster_text_pdf() -> bytes:
    source = fitz.open()
    page = source.new_page(width=500, height=220)
    page.insert_text(
        (40, 80), "SYN SYN-ACK ACK three way handshake sequence", fontsize=24, fontname="hebo"
    )
    pixmap = page.get_pixmap(dpi=150, alpha=False)
    image = pixmap.tobytes("png")
    source.close()

    scanned = fitz.open()
    target = scanned.new_page(width=500, height=220)
    target.insert_image(fitz.Rect(0, 0, 500, 220), stream=image)
    data = scanned.tobytes()
    scanned.close()
    return data


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_ocr_extracts_scanned_page_text() -> None:
    result = extract_pages(_raster_text_pdf(), max_pages=10, ocr_enabled=True)
    assert result.ocr_pages == [1]
    assert not result.needs_ocr
    assert "SYN" in result.pages[0].text.upper()
