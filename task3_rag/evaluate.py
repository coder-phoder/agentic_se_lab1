"""Retrieval evaluation for Task 3: context recall and context precision.

Input: a JSONL file with one line per question, the retrieved documents in rank order:
    {"id": "dev001", "retrieved_doc_ids": ["d0132", "d0406", "d0132", ...]}

Your retriever returns chunks. Map each chunk to its document id and keep the rank order.
Duplicates are removed here (the first occurrence counts), then the list is cut to the top k.

Metrics (both computed from the relevant document ids, no LLM needed):

  context recall@k
      Each question needs one or more pieces of information ("groups"). A group is covered if
      any of its documents is in the top k.
      recall = covered groups / all groups

  context precision@k  (rank-aware, as in RAGAS)
      Rewards putting relevant documents at the top.
      precision = sum over relevant positions i of (precision@i) / number of relevant documents in the top k
      A document is relevant if it belongs to any group. 0 if no relevant document is retrieved.

Unanswerable questions have no relevant documents and are not part of these metrics.
They are evaluated with the LLM judge instead (did the system say it doesn't know?).

Usage:
    uv run python task3_rag/evaluate.py results/r1_bm25_dev.jsonl
    uv run python task3_rag/evaluate.py results/r1_bm25_dev.jsonl --k 10 --json results/r1_metrics.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = HERE / "data" / "questions_dev.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def dedupe(ids: list[str]) -> list[str]:
    seen, result = set(), []
    for doc_id in ids:
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc_id)
    return result


def context_recall(retrieved: list[str], groups: list[list[str]]) -> float:
    top = set(retrieved)
    return sum(1 for group in groups if top & set(group)) / len(groups)


def context_precision(retrieved: list[str], groups: list[list[str]]) -> float:
    relevant = {doc_id for group in groups for doc_id in group}
    hits, score = 0, 0.0
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            hits += 1
            score += hits / i
    return score / hits if hits else 0.0


def evaluate(results: list[dict], questions: list[dict], k: int) -> dict:
    by_id = {r["id"]: r for r in results}
    per_category: dict[str, list[tuple[float, float]]] = defaultdict(list)
    per_question = []
    missing = []
    for question in questions:
        groups = question["relevant_doc_ids"]
        if not groups:
            continue
        if question["id"] not in by_id:
            missing.append(question["id"])
            retrieved = []
        else:
            retrieved = dedupe(by_id[question["id"]]["retrieved_doc_ids"])[:k]
        recall = context_recall(retrieved, groups)
        precision = context_precision(retrieved, groups)
        per_category[question["category"]].append((recall, precision))
        per_question.append({"id": question["id"], "category": question["category"],
                             "context_recall": recall, "context_precision": precision})

    def mean(values):
        return sum(values) / len(values) if values else 0.0

    all_scores = [s for scores in per_category.values() for s in scores]
    summary = {
        "k": k,
        "overall": {"n": len(all_scores), "context_recall": mean([r for r, _ in all_scores]),
                    "context_precision": mean([p for _, p in all_scores])},
        "per_category": {
            category: {"n": len(scores), "context_recall": mean([r for r, _ in scores]),
                       "context_precision": mean([p for _, p in scores])}
            for category, scores in sorted(per_category.items())
        },
        "missing_ids": missing,
    }
    return {"summary": summary, "per_question": per_question}


def format_table(summary: dict, name: str = "") -> str:
    lines = [f"{name}  (k={summary['k']})" if name else f"k={summary['k']}",
             f"{'category':<14}{'n':>4}{'recall':>10}{'precision':>11}"]
    for category, s in summary["per_category"].items():
        lines.append(f"{category:<14}{s['n']:>4}{s['context_recall']:>10.3f}{s['context_precision']:>11.3f}")
    o = summary["overall"]
    lines.append(f"{'OVERALL':<14}{o['n']:>4}{o['context_recall']:>10.3f}{o['context_precision']:>11.3f}")
    if summary["missing_ids"]:
        lines.append(f"WARNING: {len(summary['missing_ids'])} questions missing in the results (scored as 0)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval results (context recall/precision).")
    parser.add_argument("results", type=Path, help="JSONL with id + retrieved_doc_ids")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", type=Path, help="write summary + per-question scores to this file")
    args = parser.parse_args()

    report = evaluate(load_jsonl(args.results), load_jsonl(args.questions), args.k)
    print(format_table(report["summary"], args.results.name))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
