import { describe, expect, it } from "vitest";

import { formatAnswer, formatSize, pageRange, statusLabel } from "./format";

describe("formatAnswer", () => {
  it("escapes model HTML before formatting", () => {
    const html = formatAnswer("<script>alert(1)</script>");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("renders bullets, headings and bold", () => {
    const html = formatAnswer("Intro.\n\n**Key points**\n- SYN\n- ACK");
    expect(html).toContain("<p>Intro.</p>");
    expect(html).toContain("<h3>Key points</h3>");
    expect(html).toContain("<ul><li>SYN</li><li>ACK</li></ul>");
  });
});

describe("pageRange", () => {
  it("uses a single page coordinate", () => {
    expect(pageRange(2, 2)).toBe("P.02");
  });

  it("formats a range", () => {
    expect(pageRange(9, 12)).toBe("P.09–12");
  });
});

describe("formatSize and statusLabel", () => {
  it("formats sizes", () => {
    expect(formatSize(1024)).toBe("1 KB");
    expect(formatSize(2 * 1024 * 1024)).toBe("2.0 MB");
  });

  it("labels document states", () => {
    expect(statusLabel("needs_ocr")).toBe("Needs OCR");
    expect(statusLabel("processing")).toBe("Indexing");
  });
});
