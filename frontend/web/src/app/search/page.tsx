"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { Brand } from "@/components/brand";
import { ArrowLeftIcon, ChevronRightIcon, FileIcon } from "@/components/icons";
import { RequireAuth } from "@/components/require-auth";
import { SearchBox } from "@/components/search-box";
import { ThemeToggle } from "@/components/theme-toggle";
import { TopBar } from "@/components/topbar";
import { ApiError, searchApi } from "@/lib/api";
import { pageRange } from "@/lib/format";
import type { SearchResult } from "@/lib/types";

function SearchView() {
  const router = useRouter();
  const params = useSearchParams();
  const query = (params.get("q") ?? "").trim();

  const [term, setTerm] = useState(query);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (value: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await searchApi.search(value);
      setResults(response.results);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) return;
      setError("Search is unavailable right now. Check the server and try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!query) {
      router.replace("/");
      return;
    }
    setTerm(query);
    document.title = `Search: ${query} · StudBud`;
    void load(query);
  }, [query, load, router]);

  function submit() {
    const value = term.trim();
    if (!value) return;
    if (value === query) {
      void load(value);
      return;
    }
    router.push(`/search?q=${encodeURIComponent(value)}`);
  }

  return (
    <>
      <TopBar
        left={<Brand />}
        center={
          <SearchBox value={term} onChange={setTerm} onSubmit={submit} id="results-search" />
        }
        right={
          <>
            <Link className="btn btn--quiet" href="/">
              <ArrowLeftIcon className="icon" style={{ width: 16, height: 16 }} />
              Library
            </Link>
            <ThemeToggle />
          </>
        }
      />

      <main className="page">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link href="/">Library</Link>
          <span aria-hidden="true">/</span>
          <span>Search</span>
        </nav>

        <div className="result-head">
          <h1>Results for “{query}”</h1>
          {!loading && !error && (
            <p className="result-count">
              {results.length} {results.length === 1 ? "passage" : "passages"} found
            </p>
          )}
        </div>

        {loading ? (
          <ul className="result-list" aria-busy="true" aria-label="Searching">
            {[0, 1, 2, 3].map((row) => (
              <li className="result-row" key={row}>
                <span className="row-index">{String(row + 1).padStart(2, "0")}</span>
                <span className="skeleton" style={{ height: 16, width: 150 }} />
                <span className="result-body">
                  <span className="skeleton" style={{ height: 20, width: "55%" }} />
                  <span className="skeleton" style={{ height: 13, width: "90%" }} />
                  <span className="skeleton" style={{ height: 13, width: "70%" }} />
                </span>
                <span />
              </li>
            ))}
          </ul>
        ) : error ? (
          <div className="state" role="alert">
            <p>{error}</p>
            <button className="btn btn--ghost" type="button" onClick={() => void load(query)}>
              Try again
            </button>
          </div>
        ) : results.length === 0 ? (
          <section className="empty">
            <h2>No passages found</h2>
            <p>
              Try a shorter phrase, a different term, or check that the document you expected
              is marked Ready in your library.
            </p>
            <Link className="btn btn--ghost" href="/">
              Back to library
            </Link>
          </section>
        ) : (
          <ul className="result-list">
            {results.map((result, index) => (
              <li key={result.chunk_id}>
                <Link
                  className="result-row"
                  href={`/documents/${result.document_id}/chunks/${result.chunk_id}?q=${encodeURIComponent(query)}`}
                >
                  <span className="row-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="result-doc">
                    <FileIcon />
                    <span>{result.document_name}</span>
                  </span>
                  <span className="result-body">
                    <span className="result-heading">
                      {result.section_title || "Unsectioned passage"}
                    </span>
                    <span className="result-snippet">{result.snippet}</span>
                    <span className="result-page">{pageRange(result.page_start, result.page_end)}</span>
                  </span>
                  <ChevronRightIcon className="result-chevron" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}

export default function SearchPage() {
  return (
    <RequireAuth>
      <Suspense fallback={<div className="boot"><span className="mono-label">Searching</span></div>}>
        <SearchView />
      </Suspense>
    </RequireAuth>
  );
}
