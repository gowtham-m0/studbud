import type { DocumentStatus } from "./types";

export function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

export function pageRange(start: number, end: number): string {
  if (start === end) return `P.${String(start).padStart(2, "0")}`;
  return `P.${String(start).padStart(2, "0")}–${String(end).padStart(2, "0")}`;
}

export function statusLabel(status: DocumentStatus): string {
  const labels: Record<DocumentStatus, string> = {
    uploaded: "Uploaded",
    queued: "Queued",
    processing: "Indexing",
    ready: "Ready",
    failed: "Failed",
    needs_ocr: "Needs OCR",
  };
  return labels[status];
}

function escapeHtml(text: string): string {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function inline(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)/g, "$1<em>$2</em>");
}

/** Safe, small Markdown subset for model output. Escapes first. */
export function formatAnswer(raw: string): string {
  const lines = escapeHtml(raw).split(/\r?\n/);
  const out: string[] = [];
  let listOpen = false;

  for (const original of lines) {
    const line = original.trim();
    if (!line) {
      if (listOpen) {
        out.push("</ul>");
        listOpen = false;
      }
      continue;
    }

    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      if (!listOpen) {
        out.push("<ul>");
        listOpen = true;
      }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }

    if (listOpen) {
      out.push("</ul>");
      listOpen = false;
    }

    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      out.push(`<h3>${inline(heading[1])}</h3>`);
      continue;
    }

    const boldOnly = line.match(/^(\*\*|__)(.+)\1$/);
    if (boldOnly && boldOnly[2].length < 90) {
      out.push(`<h3>${inline(boldOnly[2])}</h3>`);
      continue;
    }

    out.push(`<p>${inline(line)}</p>`);
  }

  if (listOpen) out.push("</ul>");
  return out.join("");
}
