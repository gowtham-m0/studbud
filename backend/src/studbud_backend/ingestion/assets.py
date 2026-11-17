from __future__ import annotations

import logging
from dataclasses import dataclass

import pymupdf as fitz

from ..config import get_settings
from ..models import AssetKind
from ..providers.vision import VisionError, get_vision_provider

logger = logging.getLogger(__name__)

MIN_FIGURE_EDGE = 110
MIN_FIGURE_PAGE_AREA = 0.008
MIN_DRAWINGS_FOR_DIAGRAM = 20
CAPTION_PROMPT = (
    "This image comes from a study PDF. Describe any figure, diagram, chart, table, "
    "or labeled process visible here for a student. State what it shows and include "
    "visible labels, axes, values, or steps. If the image is only text, say so briefly. "
    "Do not invent details that are not visible."
)
PAGE_CAPTION_PROMPT = (
    "This is a page from a study PDF. Describe any diagram, figure, chart, or visual "
    "process on the page for a student, including visible labels and values. Ignore the "
    "ordinary body text. If there is no diagram, reply exactly: No diagram."
)


@dataclass
class AssetData:
    kind: AssetKind
    page_number: int
    asset_index: int
    data: bytes
    mime_type: str
    width: int
    height: int
    is_visual_page: bool = False
    caption: str | None = None

    @property
    def extension(self) -> str:
        return {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }.get(self.mime_type, "png")


def _render_preview(page: fitz.Page, dpi: int) -> tuple[bytes, int, int]:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    try:
        data = pixmap.tobytes("jpeg", jpg_quality=72)
    except Exception:
        data = pixmap.tobytes("png")
    return data, pixmap.width, pixmap.height


def _raster_figures(
    document: fitz.Document,
    page: fitz.Page,
    page_number: int,
    max_figures: int,
    seen_xrefs: set[int],
) -> list[AssetData]:
    figures: list[AssetData] = []
    page_area = max(1.0, page.rect.width * page.rect.height)

    for image in page.get_images(full=True):
        if len(figures) >= max_figures:
            break
        xref = int(image[0])
        if xref in seen_xrefs:
            continue

        rects = page.get_image_rects(xref)
        if not rects:
            continue
        rect = max(rects, key=lambda candidate: candidate.width * candidate.height)
        if rect.width < MIN_FIGURE_EDGE or rect.height < MIN_FIGURE_EDGE:
            continue
        if (rect.width * rect.height) / page_area < MIN_FIGURE_PAGE_AREA:
            continue

        try:
            image_data = document.extract_image(xref)
        except Exception:
            logger.warning("Could not extract image xref %s on page %s", xref, page_number)
            continue

        raw = image_data.get("image")
        if not raw:
            continue
        ext = str(image_data.get("ext", "")).lower()
        mime_by_ext = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }
        mime_type = mime_by_ext.get(ext)
        if mime_type is None:
            try:
                pixmap = fitz.Pixmap(document, xref)
                if pixmap.colorspace and pixmap.colorspace.n > 3:
                    pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                raw = pixmap.tobytes("png")
                mime_type = "image/png"
            except Exception:
                continue

        width = int(image_data.get("width") or rect.width)
        height = int(image_data.get("height") or rect.height)
        if width * height < MIN_FIGURE_EDGE * MIN_FIGURE_EDGE:
            continue

        seen_xrefs.add(xref)
        figures.append(
            AssetData(
                kind=AssetKind.figure,
                page_number=page_number,
                asset_index=len(figures) + 1,
                data=raw,
                mime_type=mime_type,
                width=width,
                height=height,
                is_visual_page=True,
            )
        )

    return figures


def extract_page_assets(
    data: bytes,
    *,
    max_figures_per_page: int | None = None,
    preview_dpi: int | None = None,
) -> tuple[list[AssetData], set[int]]:
    """Render every page and extract substantial raster figures.

    Returns assets plus the set of pages that contain visible figures/diagrams.
    Vector diagrams are represented by the page preview and flagged as visual.
    """
    settings = get_settings()
    figure_limit = max_figures_per_page or settings.max_figures_per_page
    dpi = preview_dpi or settings.page_preview_dpi

    document = fitz.open(stream=data, filetype="pdf")
    assets: list[AssetData] = []
    visual_pages: set[int] = set()
    seen_xrefs: set[int] = set()

    try:
        for index in range(document.page_count):
            page = document.load_page(index)
            page_number = index + 1

            preview_data, preview_width, preview_height = _render_preview(page, dpi)
            figures = _raster_figures(document, page, page_number, figure_limit, seen_xrefs)
            has_vector_diagram = len(page.get_drawings()) >= MIN_DRAWINGS_FOR_DIAGRAM
            is_visual = bool(figures) or has_vector_diagram
            if is_visual:
                visual_pages.add(page_number)

            assets.append(
                AssetData(
                    kind=AssetKind.page,
                    page_number=page_number,
                    asset_index=0,
                    data=preview_data,
                    mime_type="image/jpeg" if preview_data[:2] == b"\xff\xd8" else "image/png",
                    width=preview_width,
                    height=preview_height,
                    is_visual_page=has_vector_diagram and not figures,
                )
            )
            assets.extend(figures)
    finally:
        document.close()

    return assets, visual_pages


async def caption_assets(assets: list[AssetData], max_captions: int) -> int:
    """Caption raster figures and vector-diagram pages with a vision model.

    Returns the number of captions produced. Failures are logged and skipped so
    ingestion still succeeds without a vision key.
    """
    provider = get_vision_provider()
    if provider is None:
        return 0

    figures_by_page: dict[int, int] = {}
    for asset in assets:
        if asset.kind == AssetKind.figure:
            figures_by_page[asset.page_number] = figures_by_page.get(asset.page_number, 0) + 1

    targets: list[tuple[AssetData, str]] = []
    for asset in assets:
        if asset.kind == AssetKind.figure:
            targets.append((asset, CAPTION_PROMPT))
        elif (
            asset.kind == AssetKind.page
            and asset.is_visual_page
            and figures_by_page.get(asset.page_number, 0) == 0
        ):
            targets.append((asset, PAGE_CAPTION_PROMPT))

    captioned = 0
    for asset, prompt in targets[:max_captions]:
        try:
            caption = await provider.describe(asset.data, asset.mime_type, prompt)
        except VisionError as exc:
            logger.warning("Figure caption failed for document page %s: %s", asset.page_number, exc)
            break
        except Exception:
            logger.exception("Unexpected figure caption failure")
            break

        if asset.kind == AssetKind.page and caption.strip().lower().startswith("no diagram"):
            continue
        asset.caption = caption
        captioned += 1

    return captioned
