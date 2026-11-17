"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { Brand } from "@/components/brand";
import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowUpRightIcon,
  FigureIcon,
  FileIcon,
} from "@/components/icons";
import { RequireAuth } from "@/components/require-auth";
import { ThemeToggle } from "@/components/theme-toggle";
import { TopBar } from "@/components/topbar";
import { ApiError, apiBlob, documentsApi, explanationsApi } from "@/lib/api";
import { formatAnswer, pageRange } from "@/lib/format";
import type { DocumentAsset, Explanation } from "@/lib/types";

function useAssetUrls(assets: DocumentAsset[]): Record<string, string> {
  const [urls, setUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    const created: string[] = [];

    async function load() {
      const entries = await Promise.all(
        assets.map(async (asset) => {
          try {
            const blob = await apiBlob(asset.content_path);
            const url = URL.createObjectURL(blob);
            created.push(url);
            return [asset.id, url] as const;
          } catch {
            return null;
          }
        }),
      );
      if (!active) return;
      setUrls(Object.fromEntries(entries.filter((entry) => entry !== null)));
    }

    void load();
    return () => {
      active = false;
      for (const url of created) URL.revokeObjectURL(url);
    };
  }, [assets]);

  return urls;
}

function ExplanationView() {
  const router = useRouter();
  const params = useParams<{ documentId: string; chunkId: string }>();
  const query = useSearchParams();
  const searchQuery = query.get("q") ?? "";

  const documentId = params.documentId;
  const chunkId = params.chunkId;

  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [assets, setAssets] = useState<DocumentAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const booted = useRef(false);

  const urls = useAssetUrls(assets);
  const figureAssets = useMemo(
    () => assets.filter((asset) => asset.kind === "figure"),
    [assets],
  );
  const pageAsset = useMemo(
    () => assets.find((asset) => asset.kind === "page") ?? null,
    [assets],
  );

  function messageFor(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.status === 503) {
        return "AI explanations are not configured yet. Add GROQ_API_KEY on the server.";
      }
      if (cause.status === 502) {
        return "The AI provider could not generate an explanation. Try again in a moment.";
      }
      if (cause.status === 404) {
        return "This passage is no longer available. Go back and search again.";
      }
      if (cause.status === 409) {
        return "This document is still being indexed. Try again once it is Ready.";
      }
      if (cause.status === 429) {
        return "Too many explanation requests. Wait a moment, then try again.";
      }
      if (cause.status === 0) {
        return "Cannot reach the server. Check your connection and try again.";
      }
      return cause.detail;
    }
    return "The explanation could not be generated. Try again.";
  }

  async function loadAssets(next: Explanation) {
    try {
      const pageAssets = await documentsApi.assets(next.document_id, next.page_start);
      setAssets(pageAssets);
    } catch {
      setAssets([]);
    }
  }

  async function generate(askQuestion?: string) {
    const initial = explanation === null;
    if (initial) setLoading(true);
    else setAsking(true);
    setError(null);

    try {
      const next = await explanationsApi.create(chunkId, askQuestion);
      setExplanation(next);
      setQuestion("");
      await loadAssets(next);

      const nextQuery = new URLSearchParams();
      if (searchQuery) nextQuery.set("q", searchQuery);
      nextQuery.set("explanationId", next.explanation_id);
      router.replace(`/documents/${documentId}/chunks/${chunkId}?${nextQuery.toString()}`, {
        scroll: false,
      });
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setLoading(false);
      setAsking(false);
    }
  }

  async function boot() {
    const storedId = query.get("explanationId");
    if (!documentId || !chunkId) {
      setLoading(false);
      setError("This result link is incomplete. Go back and choose a result.");
      return;
    }

    if (!storedId) {
      await generate();
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const stored = await explanationsApi.get(storedId);
      setExplanation(stored);
      await loadAssets(stored);
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void boot();
    // Boot exactly once; asking for another explanation is an explicit user action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (explanation) {
      document.title = `${explanation.section_title || "Explanation"} · StudBud`;
    }
  }, [explanation]);

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const value = question.trim();
    if (!value || asking) return;
    await generate(value);
  }

  const backHref = searchQuery ? `/search?q=${encodeURIComponent(searchQuery)}` : "/";

  return (
    <>
      <TopBar
        left={
          <>
            <Link className="back-link" href={backHref}>
              <ArrowLeftIcon className="icon" />
              Back to results
            </Link>
            <Brand />
          </>
        }
        right={
          <>
            <Link className="btn btn--quiet detail-library" href="/">
              Library
            </Link>
            <ThemeToggle />
          </>
        }
      />

      <main className="page">
        {loading ? (
          <div aria-busy="true" aria-label="Generating explanation">
            <div className="skeleton" style={{ height: 16, width: 220, marginBottom: 14 }} />
            <div
              className="skeleton"
              style={{ height: 44, width: "min(640px, 80%)", marginBottom: 24 }}
            />
            <div className="detail-grid">
              <div style={{ display: "grid", gap: 12 }}>
                {[100, 92, 96, 70, 100, 88, 60].map((width, index) => (
                  <span
                    className="skeleton"
                    key={index}
                    style={{ height: 17, width: `${width}%` }}
                  />
                ))}
              </div>
              <span className="skeleton" style={{ height: 220 }} />
            </div>
          </div>
        ) : error && !explanation ? (
          <div className="state" role="alert">
            <h1>Explanation unavailable</h1>
            <p>{error}</p>
            <div className="state__actions">
              <button className="btn btn--primary" type="button" onClick={() => void boot()}>
                Try again
              </button>
              <Link className="btn btn--ghost" href={backHref}>
                Back to results
              </Link>
            </div>
          </div>
        ) : explanation ? (
          <article>
            <header className="detail-head">
              <div className="detail-identity">
                <p className="detail-doc">
                  <FileIcon className="icon" />
                  {explanation.document_name}
                </p>
                <h1>{explanation.section_title || "Selected passage"}</h1>
                <div className="detail-meta">
                  <span className="page-tag">
                    {pageRange(explanation.page_start, explanation.page_end)}
                  </span>
                  <span>Explanation grounded in your document</span>
                </div>
              </div>

              <Link
                className="btn btn--primary pdf-button"
                href={`/documents/${explanation.document_id}/view?page=${explanation.page_start}`}
              >
                <FileIcon className="icon" style={{ width: 16, height: 16 }} />
                Open PDF · page {explanation.page_start}
                <ArrowUpRightIcon className="icon" style={{ width: 15, height: 15 }} />
              </Link>
            </header>

            {explanation.insufficient_context && (
              <p className="alert alert--warning" role="status" style={{ marginTop: 22 }}>
                <AlertIcon className="icon" />
                <span>
                  The uploaded material does not contain enough information to explain this
                  confidently. Check the source page or search a different term.
                </span>
              </p>
            )}

            <div className="detail-grid">
              <div>
                <div
                  className="answer"
                  dangerouslySetInnerHTML={{ __html: formatAnswer(explanation.answer) }}
                />

                {figureAssets.length > 0 && (
                  <section className="figures" aria-labelledby="figures-title">
                    <h2 id="figures-title">
                      Figures on page {String(explanation.page_start).padStart(2, "0")}
                    </h2>
                    <div className="figure-grid">
                      {figureAssets.map((figure, index) => (
                        <Link
                          className="figure-card"
                          key={figure.id}
                          href={`/documents/${explanation.document_id}/view?page=${figure.page_number}`}
                        >
                          {urls[figure.id] ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={urls[figure.id]}
                              alt={figure.caption || `Figure ${index + 1} on page ${figure.page_number}`}
                            />
                          ) : (
                            <span className="skeleton" style={{ height: 150, display: "block" }} />
                          )}
                          <span className="figure-caption">
                            <strong>
                              <FigureIcon
                                className="icon"
                                style={{ width: 12, height: 12, verticalAlign: "-2px" }}
                              />{" "}
                              Fig. {String(index + 1).padStart(2, "0")} · Page {figure.page_number}
                            </strong>
                            {figure.caption || "Figure extracted from the source page."}
                          </span>
                        </Link>
                      ))}
                    </div>
                  </section>
                )}

                <section className="ask">
                  <h2>Ask about this section</h2>
                  <p>Answers stay grounded in this part of your document.</p>
                  <form className="ask-form" onSubmit={ask}>
                    <label className="sr-only" htmlFor="follow-up">
                      Question about this section
                    </label>
                    <input
                      id="follow-up"
                      className="input"
                      type="text"
                      value={question}
                      onChange={(event) => setQuestion(event.target.value)}
                      placeholder="e.g. Why is the third ACK needed?"
                      autoComplete="off"
                      disabled={asking}
                    />
                    <button
                      className="btn btn--ghost"
                      type="submit"
                      disabled={asking || !question.trim()}
                    >
                      {asking ? "Asking…" : "Ask"}
                    </button>
                  </form>
                  {error && (
                    <p className="alert" role="alert" style={{ marginTop: 12 }}>
                      {error}
                    </p>
                  )}
                </section>
              </div>

              <aside className="sources" aria-labelledby="sources-title">
                <div className="sources-head">
                  <h2 id="sources-title">Sources</h2>
                  <span className="source-count">{explanation.citations.length}</span>
                </div>
                <p className="sources-intro">
                  Open the cited page to verify the explanation against the original text.
                </p>

                {pageAsset && (
                  <Link
                    className="page-preview"
                    href={`/documents/${explanation.document_id}/view?page=${explanation.page_start}`}
                  >
                    {urls[pageAsset.id] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={urls[pageAsset.id]}
                        alt={`Page ${explanation.page_start} of ${explanation.document_name}`}
                      />
                    ) : (
                      <span className="skeleton" style={{ height: 260, display: "block" }} />
                    )}
                    <span className="page-preview__caption">
                      <span>Source page</span>
                      <span>{pageRange(explanation.page_start, explanation.page_end)}</span>
                    </span>
                  </Link>
                )}

                {explanation.citations.length > 0 ? (
                  <ol className="source-list">
                    {explanation.citations.map((citation) => (
                      <li key={citation.chunk_id}>
                        <Link
                          className="source-card"
                          href={`/documents/${citation.document_id}/view?page=${citation.page_start}`}
                        >
                          <span className="source-card__head">
                            <span className="source-doc">{citation.document_name}</span>
                            <span className="source-page">
                              {pageRange(citation.page_start, citation.page_end)}
                            </span>
                          </span>
                          <span className="source-excerpt">{citation.excerpt}</span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="sources-intro">
                    The model did not return a verifiable citation for this explanation.
                  </p>
                )}

                <p className="model-note">Generated with {explanation.model}</p>
              </aside>
            </div>
          </article>
        ) : null}
      </main>
    </>
  );
}

export default function ExplanationPage() {
  return (
    <RequireAuth>
      <Suspense
        fallback={
          <div className="boot">
            <span className="mono-label">Opening explanation</span>
          </div>
        }
      >
        <ExplanationView />
      </Suspense>
    </RequireAuth>
  );
}
