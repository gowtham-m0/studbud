# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Next.js 16 App Router frontend (Vercel free tier), Python FastAPI monolith with in-process ingestion worker (Render free tier with keepalive and hosted Gemini embeddings), PostgreSQL 16 + pgvector (Neon free tier), Cloudflare R2 private object storage, Groq for chat, embeddings, and optional figure captions. Chosen for zero-cost deployment, React UI flexibility, and a strong PDF-processing ecosystem.

## Users

General learners: students, self-directed learners, and teachers who work from PDFs such as textbooks, school/college books, lecture notes, research papers, and handouts. They are usually mid-study, looking for one concept, definition, or explanation inside a large stack of material. They need a fast answer and a way to verify it against the original page.

## Product Purpose

StudBud turns a personal PDF library into a searchable knowledge base. A learner uploads academic PDFs, searches a concept or question in natural language, and gets a clear explanation grounded in the uploaded material, with the source document and page attached. Success means the learner finds the right passage quickly and can confirm it in the original PDF without guessing.

## Positioning

Answers are grounded in the learner's own uploaded documents and always trace back to a document, section heading, and page range. Every explanation has a one-click jump to the exact PDF page. The product does not present general model knowledge as if it came from the learner's books.

## Operating Context

- Learners keep a private library of PDFs: textbooks, class notes, handouts, papers.
- Search happens mid-study, often on a phone or laptop between classes.
- Documents may be text-based or scanned; scanned pages are reported honestly rather than silently indexed.
- Access is gated: a developer/owner issues an access key with an expiry date; learners sign in with that key, no registration.
- The MVP runs on free tiers, so processing is asynchronous and occasional cold starts are expected.

## Capabilities and Constraints

- Access-key sign-in with required expiry (default 30 days), revocation, and HttpOnly cookie sessions.
- Flat per-user library; no collections or sharing in the MVP.
- PDF upload, background ingestion, page-aware text extraction, page/section-aligned chunking with overlap, embeddings.
- Page previews and extracted raster figures stored with page provenance; optional vision captions feed retrieval and explanation context.
- Hybrid retrieval (pgvector + PostgreSQL full-text) scoped to the signed-in user's Ready documents.
- Search results: document name left, section heading right, with page range and snippet.
- Explanation page: book name, heading, grounded AI explanation, citations, source-page preview, extracted figures, and an "Open PDF (page N)" action.
- Light and dark themes with a visible toggle; the choice persists locally.
- Groq chat completions (`openai/gpt-oss-120b` at time of writing) and optional Gemini vision captions; local FastEmbed embeddings by default (Nomic 768-d), with hash fallback only if FastEmbed is unavailable.
- OCR is detect-and-report only in the MVP.
- No public registration, passwords, collaboration, or public document links.
- Free-tier limits: cap upload size and page count; retry provider rate limits with backoff.

## Brand Commitments

- Name: StudBud.
- Voice: clear, direct, student-friendly. Never overconfident when sources are thin.
- No fabricated testimonials, benchmarks, citations, or usage claims.

## Evidence on Hand

- No customer logos, testimonials, case studies, or marketing assets exist.
- Uploaded PDFs are user-provided content; they must never be used as public evidence or marketing material.
- Screenshots or examples shown in the UI must come from the signed-in user's own library.

## Product Principles

1. Ground every explanation in retrieved passages; abstain when the material does not support an answer.
2. Make verification one click away: document, heading, page, and an exact PDF page jump.
3. Respect the material: preserve page provenance, technical terms, formulas, and document structure.
4. Protect the library: every lookup is scoped to the authenticated owner, and deletion removes derived data.
5. Keep the MVP honest and lean: report scanned or failed documents plainly, and ship only what free-tier infrastructure can support.

## Accessibility & Inclusion

- Responsive from phone width up with no horizontal page scroll.
- Keyboard-operable search, upload, result rows, and PDF navigation.
- Visible focus states and sufficient color contrast in light and dark modes.
- Explanations use readable typography and plain-language phrasing where possible.
