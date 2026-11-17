"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Brand } from "@/components/brand";
import { FileIcon, TrashIcon, UploadIcon } from "@/components/icons";
import { RequireAuth } from "@/components/require-auth";
import { SearchBox } from "@/components/search-box";
import { ThemeToggle } from "@/components/theme-toggle";
import { TopBar } from "@/components/topbar";
import { useAuth } from "@/components/providers";
import { ApiError, documentsApi } from "@/lib/api";
import { formatDate, formatSize, statusLabel } from "@/lib/format";
import type { DocumentItem } from "@/lib/types";

function isPending(document: DocumentItem) {
  return ["uploaded", "queued", "processing"].includes(document.status);
}

function LibraryView() {
  const router = useRouter();
  const { session, signOut } = useAuth();
  const fileInput = useRef<HTMLInputElement>(null);

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    document.title = "Your library · StudBud";
  }, []);

  const loadDocuments = useCallback(async () => {
    try {
      const next = await documentsApi.list();
      setDocuments(next);
      setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) return;
      setError("Your library could not be loaded. Check the server and try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!documents.some(isPending)) return;
    const timer = window.setInterval(() => void loadDocuments(), 3000);
    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  const pendingCount = documents.filter(isPending).length;
  const readyCount = documents.filter((item) => item.status === "ready").length;

  function submitSearch() {
    const value = query.trim();
    if (value) router.push(`/search?q=${encodeURIComponent(value)}`);
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setUploadError(null);

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Choose a PDF file. Other formats are not supported.");
      return;
    }

    setUploading(true);
    try {
      await documentsApi.upload(file);
      await loadDocuments();
    } catch (cause) {
      setUploadError(
        cause instanceof ApiError ? cause.detail : "Upload failed. Check the file and try again.",
      );
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function retry(documentItem: DocumentItem) {
    try {
      await documentsApi.retry(documentItem.id);
      await loadDocuments();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Could not retry this document.");
    }
  }

  async function remove(documentItem: DocumentItem) {
    const confirmed = window.confirm(
      `Delete “${documentItem.file_name}”? Its searchable passages and figures will be removed too.`,
    );
    if (!confirmed) return;

    try {
      await documentsApi.remove(documentItem.id);
      setDocuments((current) => current.filter((item) => item.id !== documentItem.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Could not delete this document.");
    }
  }

  async function handleSignOut() {
    try {
      await signOut();
    } catch {
      setError("Sign out failed. Try again.");
    }
  }

  return (
    <>
      <TopBar
        left={<Brand />}
        center={
          <SearchBox
            value={query}
            onChange={setQuery}
            onSubmit={submitSearch}
            placeholder="Search your library"
          />
        }
        right={
          <>
            <input
              ref={fileInput}
              className="sr-only"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => void handleFile(event.target.files?.[0])}
            />
            <button
              className="btn btn--ghost upload-btn"
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              aria-label="Upload PDF"
            >
              <UploadIcon className="icon" />
              <span className="btn-label">{uploading ? "Uploading…" : "Upload PDF"}</span>
            </button>
            <ThemeToggle />
            <div className="account">
              <span className="account__name">{session?.user.display_name}</span>
              <button className="btn btn--quiet" type="button" onClick={handleSignOut}>
                Sign out
              </button>
            </div>
          </>
        }
      />

      <main className="page">
        <div className="page-head">
          <div>
            <h1>Your library</h1>
            <p className="page-head__meta mono-label">
              {documents.length} {documents.length === 1 ? "document" : "documents"}
              {readyCount > 0 ? ` · ${readyCount} searchable` : ""}
            </p>
          </div>
          {pendingCount > 0 && (
            <span className="processing" role="status">
              <span className="processing__dot" aria-hidden="true" />
              Indexing {pendingCount} {pendingCount === 1 ? "document" : "documents"}
            </span>
          )}
        </div>

        {uploadError && (
          <p className="alert" role="alert" style={{ marginBottom: 18 }}>
            {uploadError}
          </p>
        )}

        {error && (
          <div className="state" role="alert">
            <p>{error}</p>
            <button className="btn btn--ghost" type="button" onClick={() => void loadDocuments()}>
              Try again
            </button>
          </div>
        )}

        {loading ? (
          <ul className="doc-list" aria-busy="true" aria-label="Loading documents">
            {[0, 1, 2].map((row) => (
              <li className="doc-row" key={row}>
                <span className="row-index">{String(row + 1).padStart(2, "0")}</span>
                <span className="skeleton file-chip" />
                <span className="skeleton" style={{ height: 20, width: "60%" }} />
                <span className="skeleton" style={{ height: 22, width: 72 }} />
                <span />
              </li>
            ))}
          </ul>
        ) : documents.length === 0 ? (
          <section className="empty">
            <FileIcon className="empty__icon" />
            <h2>Start with one PDF</h2>
            <p>
              Upload a textbook, lecture notes, or a handout. StudBud indexes it by page and
              section, keeps diagrams with their source page, and links every explanation back
              to the exact page.
            </p>
            <button
              className="btn btn--primary"
              type="button"
              onClick={() => fileInput.current?.click()}
            >
              <UploadIcon className="icon" />
              Upload a PDF
            </button>
          </section>
        ) : (
          <>
            <ul className="doc-list">
              {documents.map((documentItem, index) => (
                <li className="doc-row" key={documentItem.id}>
                  <span className="row-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="file-chip">
                    <FileIcon />
                  </span>
                  <div className="doc-main">
                    <h3>{documentItem.file_name}</h3>
                    <p>
                      {formatSize(documentItem.file_size_bytes)}
                      {documentItem.page_count ? ` · ${documentItem.page_count} pages` : ""}
                      {` · ${formatDate(documentItem.created_at)}`}
                    </p>
                    {documentItem.failure_reason && (
                      <p className="doc-reason">{documentItem.failure_reason}</p>
                    )}
                  </div>
                  <span className={`status status--${documentItem.status}`}>
                    <span className="status__dot" aria-hidden="true" />
                    {statusLabel(documentItem.status)}
                  </span>
                  <div className="doc-actions">
                    {(documentItem.status === "failed" ||
                      documentItem.status === "needs_ocr") && (
                      <button
                        className="btn btn--ghost"
                        type="button"
                        onClick={() => void retry(documentItem)}
                      >
                        Retry
                      </button>
                    )}
                    <button
                      className="icon-btn"
                      type="button"
                      onClick={() => void remove(documentItem)}
                      aria-label={`Delete ${documentItem.file_name}`}
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="library-note">
              Search covers everything marked Ready. A document becomes searchable after
              indexing finishes.
            </p>
          </>
        )}
      </main>
    </>
  );
}

export default function LibraryPage() {
  return (
    <RequireAuth>
      <LibraryView />
    </RequireAuth>
  );
}
