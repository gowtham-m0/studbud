"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ArrowLeftIcon, ArrowUpRightIcon } from "@/components/icons";
import { RequireAuth } from "@/components/require-auth";
import { ThemeToggle } from "@/components/theme-toggle";
import { ApiError, documentsApi } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";

function Viewer() {
  const router = useRouter();
  const params = useParams<{ documentId: string }>();
  const query = useSearchParams();
  const documentId = params.documentId;
  const pageParam = Number(query.get("page") ?? "1");
  const page = Number.isFinite(pageParam) && pageParam > 0 ? Math.floor(pageParam) : 1;

  const [documentItem, setDocumentItem] = useState<DocumentItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const next = await documentsApi.get(documentId);
        if (!active) return;
        setDocumentItem(next);
        document.title = `${next.file_name} · page ${page} · StudBud`;
      } catch (cause) {
        if (!active) return;
        setError(
          cause instanceof ApiError
            ? cause.detail
            : "This document could not be opened. It may have been deleted.",
        );
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [documentId, page]);

  function back() {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    router.push("/");
  }

  const fileUrl = documentsApi.fileUrl(documentId, page);

  return (
    <div className="viewer-shell">
      <header className="viewer-topbar">
        <button className="back-link" type="button" onClick={back}>
          <ArrowLeftIcon className="icon" />
          Back
        </button>

        <div className="viewer-title">
          <p>{documentItem?.file_name ?? "Document"}</p>
          <p>
            Page {page}
            {documentItem?.page_count ? ` of ${documentItem.page_count}` : ""}
          </p>
        </div>

        <div className="viewer-actions" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <a className="btn btn--ghost" href={fileUrl} target="_blank" rel="noopener">
            Open in new tab
            <ArrowUpRightIcon className="icon" style={{ width: 15, height: 15 }} />
          </a>
          <Link className="btn btn--quiet" href="/">
            Library
          </Link>
          <ThemeToggle />
        </div>
      </header>

      {error ? (
        <div className="state" role="alert" style={{ margin: "48px auto" }}>
          <h1>PDF unavailable</h1>
          <p>{error}</p>
          <Link className="btn btn--primary" href="/">
            Back to library
          </Link>
        </div>
      ) : loading ? (
        <div className="viewer-loading" aria-busy="true" aria-label="Loading PDF">
          <span className="skeleton" />
        </div>
      ) : (
        <iframe
          className="viewer-frame"
          src={fileUrl}
          title={`${documentItem?.file_name ?? "Document"}, page ${page}`}
        />
      )}
    </div>
  );
}

export default function ViewerPage() {
  return (
    <RequireAuth>
      <Suspense
        fallback={
          <div className="boot">
            <span className="mono-label">Opening PDF</span>
          </div>
        }
      >
        <Viewer />
      </Suspense>
    </RequireAuth>
  );
}
