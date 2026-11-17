"""Measure retrieval quality against a labelled question set.

Dataset shape:
{
  "name": "networks-sample",
  "questions": [
    {
      "id": "q1",
      "question": "Explain the TCP three-way handshake",
      "document": "sample_networks.pdf",
      "pages": [2],
      "section": "TCP Three-Way Handshake",
      "answerable": true
    }
  ]
}

Usage:
    cd backend
    STUDBUD_KEY=sb_... uv run python scripts/evaluate_retrieval.py \
      --dataset evaluation/sample_questions.json --k 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class QuestionResult:
    question_id: str
    question: str
    expected_document: str
    expected_pages: list[int]
    first_relevant_rank: int | None
    top_result_matches_page: bool
    result_count: int


def is_relevant(result: dict, expected_document: str, expected_pages: list[int]) -> bool:
    if result.get("document_name") != expected_document:
        return False
    start = int(result.get("page_start", 0))
    end = int(result.get("page_end", start))
    return any(start <= page <= end for page in expected_pages)


def evaluate(
    dataset: dict,
    results_by_question: dict[str, list[dict]],
) -> tuple[list[QuestionResult], dict]:
    rows: list[QuestionResult] = []
    for item in dataset["questions"]:
        if not item.get("answerable", True):
            continue
        question_id = item["id"]
        results = results_by_question.get(question_id, [])
        expected_document = item["document"]
        expected_pages = list(item.get("pages", []))
        first_rank = None
        for rank, result in enumerate(results, start=1):
            if is_relevant(result, expected_document, expected_pages):
                first_rank = rank
                break
        top_matches = bool(results and is_relevant(results[0], expected_document, expected_pages))
        rows.append(
            QuestionResult(
                question_id=question_id,
                question=item["question"],
                expected_document=expected_document,
                expected_pages=expected_pages,
                first_relevant_rank=first_rank,
                top_result_matches_page=top_matches,
                result_count=len(results),
            )
        )

    answerable = [row for row in rows]
    total = len(answerable) or 1
    recall = sum(1 for row in answerable if row.first_relevant_rank is not None) / total
    mrr = sum(1 / row.first_relevant_rank for row in answerable if row.first_relevant_rank) / total
    page_at_1 = sum(1 for row in answerable if row.top_result_matches_page) / total

    metrics = {
        "questions_scored": len(answerable),
        "recall_at_k": round(recall, 4),
        "mrr": round(mrr, 4),
        "page_at_1": round(page_at_1, 4),
    }
    return rows, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--key", default=os.environ.get("STUDBUD_KEY", ""))
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--json-out")
    parser.add_argument("--min-recall", type=float, default=0.0)
    args = parser.parse_args()

    if not args.key:
        print("Set STUDBUD_KEY or pass --key.")
        return 1
    if not 1 <= args.k <= 30:
        print("--k must be between 1 and 30.")
        return 1

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    results_by_question: dict[str, list[dict]] = {}

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60.0) as client:
        login = client.post("/api/auth/sign-in", json={"key": args.key})
        if login.status_code != 204:
            print(f"Sign-in failed: {login.status_code} {login.text}")
            return 1

        for item in dataset["questions"]:
            response = client.get("/api/search", params={"q": item["question"], "limit": args.k})
            if response.status_code != 200:
                print(f"Search failed for {item['id']}: {response.status_code} {response.text}")
                return 1
            results_by_question[item["id"]] = response.json().get("results", [])

    rows, metrics = evaluate(dataset, results_by_question)

    print(f"Dataset: {dataset.get('name', args.dataset)}")
    print(f"K: {args.k}")
    for row in rows:
        rank = row.first_relevant_rank if row.first_relevant_rank is not None else "miss"
        print(
            f"  {row.question_id}: rank={rank} top_page={row.top_result_matches_page} "
            f"pages={row.expected_pages} results={row.result_count} — {row.question}"
        )
    print(json.dumps(metrics, indent=2))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"metrics": metrics, "questions": [row.__dict__ for row in rows]}, indent=2),
            encoding="utf-8",
        )

    if metrics["recall_at_k"] < args.min_recall:
        print(
            f"Recall@K {metrics['recall_at_k']} is below --min-recall {args.min_recall}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
