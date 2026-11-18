"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Brand } from "@/components/brand";
import { AlertIcon } from "@/components/icons";
import { useAuth } from "@/components/providers";
import { ThemeToggle } from "@/components/theme-toggle";
import { ApiError } from "@/lib/api";

export default function SignInPage() {
  const router = useRouter();
  const { session, loading, signIn } = useAuth();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.title = "Sign in · StudBud";
  }, []);

  useEffect(() => {
    if (!loading && session) router.replace("/");
  }, [loading, session, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const value = key.trim();
    if (!value || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await signIn(value);
      router.replace("/");
    } catch (cause) {
      if (cause instanceof ApiError) {
        if (cause.status === 401) {
          setError(cause.detail || "That key is invalid, expired, or revoked. Check it and try again.");
        } else if (cause.status === 429) {
          setError("Too many attempts. Wait a moment, then try again.");
        } else if (cause.status === 0) {
          setError("Cannot reach the server. Check your connection and try again.");
        } else {
          setError(cause.detail);
        }
      } else {
        setError("Something went wrong while signing in. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="signin">
      <section className="signin__intro">
        <Brand href="/sign-in" />
        <h1 style={{ marginTop: 42 }}>Search the page. Verify the answer.</h1>
        <p>
          StudBud indexes your academic PDFs by page and section, keeps diagrams attached to
          their source page, and grounds every explanation in the passages it cites.
        </p>
        <div className="signin__facts">
          <div className="signin__fact">
            <span>01</span>
            <span>Ask in your own words, not the book&apos;s index.</span>
          </div>
          <div className="signin__fact">
            <span>02</span>
            <span>Every result resolves to a document, heading, and page.</span>
          </div>
          <div className="signin__fact">
            <span>03</span>
            <span>Figures stay with the page. Open the source in one click.</span>
          </div>
        </div>
      </section>

      <section className="signin__panel">
        <ThemeToggle className="signin__theme" />
        <span className="mono-label mono-label--accent">Access key / 01</span>
        <h2 style={{ marginTop: 8 }}>Sign in</h2>
        <p className="muted" style={{ marginTop: 8, fontSize: 14 }}>
          Enter the access key your administrator issued. No registration or password.
        </p>

        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="access-key">Access key</label>
            <input
              id="access-key"
              className="input input--mono"
              type="password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="sb_XXXX-XXXX-XXXX-XXXX"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              disabled={submitting}
              required
            />
          </div>

          {error && (
            <p className="alert" role="alert">
              <AlertIcon className="icon" />
              <span>{error}</span>
            </p>
          )}

          <button
            className="btn btn--primary"
            type="submit"
            disabled={submitting || !key.trim()}
            style={{ width: "100%" }}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="signin__hint">
          Keys expire after a set period. If yours stopped working, ask your administrator for
          a new one.
        </p>
      </section>
    </main>
  );
}
