"""Generate a small text-based PDF for local ingestion tests."""

from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).parent / "sample_networks.pdf"


def add_page(document: fitz.Document, blocks: list[tuple[float, str, float, float]]) -> fitz.Page:
    page = document.new_page(width=595, height=842)
    y = 60
    for size, text, x, width in blocks:
        rect = fitz.Rect(x, y, x + width, y + 400)
        page.insert_textbox(rect, text, fontsize=size, fontname="helv", lineheight=1.35)
        used = fitz.get_text_length(text, fontname="helv", fontsize=size)
        lines = max(1, int(used / width) + 1)
        y += (size * 1.6) * lines + 14
    return page


def diagram_png() -> bytes:
    """Render a small three-step handshake diagram as a raster image."""
    diagram = fitz.open()
    page = diagram.new_page(width=420, height=190)
    page.draw_rect(fitz.Rect(20, 40, 145, 120), color=(0.06, 0.1, 0.17), width=1.5)
    page.draw_rect(fitz.Rect(275, 40, 400, 120), color=(0.06, 0.1, 0.17), width=1.5)
    page.insert_text((42, 75), "CLIENT", fontsize=13, fontname="hebo")
    page.insert_text((296, 75), "SERVER", fontsize=13, fontname="hebo")
    page.draw_line(fitz.Point(145, 58), fitz.Point(275, 58), color=(0.1, 0.3, 0.9), width=2)
    page.draw_line(fitz.Point(275, 82), fitz.Point(145, 82), color=(0.1, 0.3, 0.9), width=2)
    page.draw_line(fitz.Point(145, 106), fitz.Point(275, 106), color=(0.1, 0.3, 0.9), width=2)
    page.insert_text((174, 50), "SYN", fontsize=10, fontname="helv")
    page.insert_text((160, 76), "SYN-ACK", fontsize=10, fontname="helv")
    page.insert_text((184, 100), "ACK", fontsize=10, fontname="helv")
    page.insert_text((20, 158), "Figure 1. TCP three-way handshake sequence", fontsize=9)
    pixmap = page.get_pixmap(dpi=150, alpha=False)
    data = pixmap.tobytes("png")
    diagram.close()
    return data


def main() -> None:
    document = fitz.open()

    add_page(
        document,
        [
            (22, "Computer Networks", 50, 495),
            (16, "Connection Establishment", 50, 495),
            (
                11,
                "Transport protocols must agree on how to begin a conversation. "
                "A client and a server exchange control information before any "
                "application data is sent. This process establishes state at both "
                "endpoints so that later segments can be interpreted correctly.",
                50,
                495,
            ),
            (
                11,
                "Connection establishment is separate from data transfer. Once the "
                "connection exists, both sides track sequence numbers, buffers, and "
                "timers. If establishment fails, no application data is delivered.",
                50,
                495,
            ),
        ],
    )

    handshake_page = add_page(
        document,
        [
            (16, "TCP Three-Way Handshake", 50, 495),
            (
                11,
                "TCP establishes a connection using a three-step handshake. The "
                "client sends a SYN segment with its initial sequence number. The "
                "server replies with a SYN-ACK segment that acknowledges the client "
                "sequence number and carries the server initial sequence number.",
                50,
                495,
            ),
            (
                11,
                "The client completes the handshake by sending an ACK segment. At "
                "this point both hosts have synchronized sequence numbers and the "
                "connection is established. The three steps are SYN, SYN-ACK, and "
                "ACK. This mechanism confirms that both directions of the connection "
                "are reachable and that both sequence number spaces are initialized.",
                50,
                495,
            ),
        ],
    )
    handshake_page.insert_image(fitz.Rect(55, 520, 540, 740), stream=diagram_png())
    handshake_page.insert_text((55, 762), "Figure 1. TCP three-way handshake sequence", fontsize=9)

    add_page(
        document,
        [
            (16, "Flow Control", 50, 495),
            (
                11,
                "Flow control prevents a fast sender from overwhelming a slow "
                "receiver. TCP uses a sliding window advertised by the receiver. "
                "The window size indicates how many bytes the receiver can accept "
                "before further acknowledgements are required.",
                50,
                495,
            ),
            (
                11,
                "A zero window tells the sender to pause. When buffer space becomes "
                "available, the receiver advertises a larger window and transmission "
                "resumes. Congestion control is a separate mechanism that limits "
                "sending based on network conditions.",
                50,
                495,
            ),
        ],
    )

    document.save(OUT)
    document.close()
    print(OUT)


if __name__ == "__main__":
    main()
