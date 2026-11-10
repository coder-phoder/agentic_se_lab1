"""LLM-as-judge for Task 3 (RAGAS-style end-to-end evaluation).

Input: a JSONL file with one line per question:
    {"id": "dev001", "answer": "The default was `300`.", "contexts": ["chunk text 1", "chunk text 2", ...]}
"contexts" are exactly the chunk texts you put into the prompt of your generator.

Metrics per question:
  faithfulness      (RAGAS) The judge splits the answer into claims and checks each claim against the contexts.
                    score = supported claims / all claims. Answers without claims (e.g. "I don't know") get no score.
                    Abstentions (the answer is exactly ABSTENTION, see below) are not sent to the judge and get no score
                    either: saying "not in the documentation" makes no claim about the context. They show up in the
                    `abstained` column instead, and correctness tells you whether abstaining was right.
  answer_relevance  (RAGAS) The judge writes 3 questions that the answer would answer. We embed them and the
                    original question; score = mean cosine similarity. Measures if the answer addresses the question,
                    not if it is correct.
  correctness       (not in RAGAS core) The judge compares the answer with the ground truth answer:
                    1 = correct, 0.5 = partially correct, 0 = wrong.
                    For unanswerable questions: 1 if the answer says the information is not available, else 0.

The judge is an LLM, so it makes mistakes. Check some decisions by hand (see the lab sheet).

Usage:
    uv run python task3_rag/judge.py results/answers_r4.jsonl --sample 50 --out results/judge_r4.jsonl
    uv run python task3_rag/judge.py results/answers_r4.jsonl --model <other model> --local-embeddings

Cost: up to 3 LLM calls per question (2 for abstentions). Use --sample.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common.llm_client import LLMClient  # noqa: E402

DEFAULT_QUESTIONS = HERE / "data" / "questions_dev.jsonl"
ABSTENTION = "The documentation does not contain this information."


def is_abstention(answer: str) -> bool:
    """True if the answer is the abstention sentence (ignoring case, quotes and surrounding whitespace)."""
    normalize = lambda text: text.strip().strip("\"'`*").strip().rstrip(".").lower()  # noqa: E731
    return normalize(answer) == normalize(ABSTENTION)

FAITHFULNESS_PROMPT = """You check whether an answer is supported by retrieved context.

Step 1: Split the ANSWER into short, self-contained factual claims. Ignore statements like "I don't know".
Step 2: For each claim, decide if it can be directly inferred from the CONTEXT. Only use the CONTEXT, not your own knowledge.

CONTEXT:
{context}

ANSWER:
{answer}

Respond with JSON only, in this format:
{{"claims": [{{"claim": "...", "supported": true}}, ...]}}"""

RELEVANCE_PROMPT = """Here is an answer from a documentation assistant.
Write 3 different questions that this answer would be a good answer to.
If the answer says that it does not know or the information is not available, write questions about what it says it doesn't know.

ANSWER:
{answer}

Respond with JSON only, in this format:
{{"questions": ["...", "...", "..."]}}"""

CORRECTNESS_PROMPT = """You grade an answer of a documentation assistant against the ground truth.

QUESTION:
{question}

GROUND TRUTH ANSWER:
{ground_truth}

ANSWER TO GRADE:
{answer}

Rules:
- "correct": contains the essential information of the ground truth and nothing that contradicts it.
- "partial": contains some but not all essential information, or adds a contradicting detail.
- "wrong": misses the essential information or contradicts the ground truth.
- If the ground truth says the documentation does not contain the information, the answer is "correct" only if it
  clearly says that the information is not available. Any concrete answer is "wrong".

Respond with JSON only, in this format:
{{"verdict": "correct" | "partial" | "wrong", "reason": "one sentence"}}"""

VERDICT_SCORES = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}


def load_jsonl(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"judge did not return JSON: {text[:200]}")
    return json.loads(match.group(0))


class Judge:
    def __init__(self, llm: LLMClient, embed_fn):
        self.llm = llm
        self.embed_fn = embed_fn

    def ask(self, prompt: str) -> dict:
        last_error = None
        for attempt in range(3):
            # The gateway caches identical requests, so a retry must differ from the first attempt.
            suffix = "" if attempt == 0 else f"\n\n(Attempt {attempt + 1}: reply with valid JSON only.)"
            reply = self.llm.chat([{"role": "user", "content": prompt + suffix}])
            try:
                return parse_json(reply)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
        raise RuntimeError(f"judge output unusable after 3 attempts: {last_error}")

    def faithfulness(self, answer: str, contexts: list[str]) -> tuple[float | None, list]:
        context = "\n\n---\n\n".join(contexts) if contexts else "(no context)"
        claims = self.ask(FAITHFULNESS_PROMPT.format(context=context, answer=answer)).get("claims", [])
        if not claims:
            return None, []
        return sum(1 for c in claims if c.get("supported")) / len(claims), claims

    def answer_relevance(self, question: str, answer: str) -> tuple[float, list]:
        generated = self.ask(RELEVANCE_PROMPT.format(answer=answer)).get("questions", [])[:3]
        if not generated:
            return 0.0, []
        vectors = self.embed_fn([question] + generated)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        return float(np.mean(vectors[1:] @ vectors[0])), generated

    def correctness(self, question: str, ground_truth: str, answer: str) -> tuple[float, str]:
        result = self.ask(CORRECTNESS_PROMPT.format(question=question, ground_truth=ground_truth, answer=answer))
        verdict = str(result.get("verdict", "wrong")).lower()
        return VERDICT_SCORES.get(verdict, 0.0), result.get("reason", "")


def stratified_sample(questions: list[dict], n: int, seed: int = 0) -> list[dict]:
    by_category = defaultdict(list)
    for question in questions:
        by_category[question["category"]].append(question)
    rng = random.Random(seed)
    per_category = max(1, n // len(by_category))
    sample = []
    for category in sorted(by_category):
        items = sorted(by_category[category], key=lambda q: q["id"])
        sample.extend(rng.sample(items, min(per_category, len(items))))
    return sorted(sample, key=lambda q: q["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS-style LLM judge.")
    parser.add_argument("answers", type=Path)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--sample", type=int, help="judge a stratified sample of N questions (same sample every time)")
    parser.add_argument("--model", help="judge model (default: $LAB_CHAT_MODEL)")
    parser.add_argument("--local-embeddings", action="store_true",
                        help="use sentence-transformers all-MiniLM-L6-v2 for answer relevance")
    parser.add_argument("--out", type=Path, help="per-question judge results (JSONL)")
    args = parser.parse_args()

    answers = {a["id"]: a for a in load_jsonl(args.answers)}
    questions = [q for q in load_jsonl(args.questions) if q["id"] in answers]
    if args.sample:
        questions = stratified_sample(questions, args.sample)

    llm = LLMClient(model=args.model, log_path=Path("logs") / f"judge_{args.answers.stem}.jsonl")
    if args.local_embeddings:
        from sentence_transformers import SentenceTransformer

        st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        embed_fn = lambda texts: np.asarray(st_model.encode(texts))  # noqa: E731
    else:
        embed_fn = llm.embed
    judge = Judge(llm, embed_fn)

    rows = []
    for i, question in enumerate(questions, start=1):
        answer = answers[question["id"]]
        abstained = is_abstention(answer["answer"])
        if abstained:
            faith, claims = None, []
        else:
            faith, claims = judge.faithfulness(answer["answer"], answer.get("contexts", []))
        relevance, generated = judge.answer_relevance(question["question"], answer["answer"])
        correct, reason = judge.correctness(question["question"], question["answer"], answer["answer"])
        rows.append({"id": question["id"], "category": question["category"], "abstained": abstained,
                     "faithfulness": faith,
                     "answer_relevance": relevance, "correctness": correct, "correctness_reason": reason,
                     "claims": claims, "generated_questions": generated})
        print(f"[{i}/{len(questions)}] {question['id']} faith={faith} rel={relevance:.2f} correct={correct}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(format_summary(rows))


def format_summary(rows: list[dict]) -> str:
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    by_category["OVERALL"] = rows

    def mean(values):
        values = [v for v in values if v is not None]
        return f"{sum(values) / len(values):.3f}" if values else "  -  "

    lines = [f"{'category':<14}{'n':>4}{'abstained':>11}{'faithful':>10}{'relevance':>11}{'correct':>9}"]
    for category, items in by_category.items():
        lines.append(f"{category:<14}{len(items):>4}{mean([float(r.get('abstained', False)) for r in items]):>11}"
                     f"{mean([r['faithfulness'] for r in items]):>10}"
                     f"{mean([r['answer_relevance'] for r in items]):>11}{mean([r['correctness'] for r in items]):>9}")
    lines.append("faithful: mean over answers with claims (abstentions are not scored)")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
