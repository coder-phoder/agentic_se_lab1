"""rag.py - the "librarian" of our agent (Task 2).

It loads the UPB Agentic SE Web Style Guide (55 Markdown files), cuts it into chunks,
turns every chunk into a vector (embedding) and finds the chunks that best match a question.

Main entry points:
    index = StyleGuideIndex(backend="gateway", llm=llm)   # or "local" / "none"
    index.build()
    chunks = index.search("night mode colors", k=4)       # -> list[Chunk]
    text, ids = format_observation(chunks)                # <= 1,000 tokens for the model

Quick test from the repository root (prints the top results for test questions):
    uv run python task2_own_agent/rag.py
    uv run python task2_own_agent/rag.py --backend none "footer text"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TASK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TASK_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.llm_client import count_tokens  # noqa: E402

STYLE_GUIDE_DIR = TASK_DIR / "style_guide"
CACHE_DIR = TASK_DIR / ".cache"
LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

MAX_CHUNK_TOKENS = 300          # documents longer than this are split at their "## " headings
OBSERVATION_TOKEN_LIMIT = 1000  # rule of the lab: max. 1,000 tokens per search observation
DEFAULT_ALPHA = 0.7             # weight of the embedding score in the hybrid score (rest: BM25)


# --------------------------------------------------------------------------- data


@dataclass
class Chunk:
    doc_id: str        # e.g. "SG-13"
    title: str         # e.g. "Night mode palette (version 2)"
    status: str        # e.g. "ACTIVE (version 2)" or "DEPRECATED – replaced by SG-11"
    section: str       # "" if the chunk is the whole document, otherwise the "## " heading
    text: str          # what the model sees: a small header (id, title, status) + the rule text

    @property
    def deprecated(self) -> bool:
        return self.status.upper().startswith("DEPRECATED")

    @property
    def replaced_by(self) -> str | None:
        match = re.search(r"replaced by (SG-\d+)", self.status)
        return match.group(1) if match else None


# --------------------------------------------------------------- loading + chunking


def load_documents(folder: Path = STYLE_GUIDE_DIR) -> list[dict]:
    """Reads every SG-xx_*.md file and splits it into id, title, status, category and body."""
    docs = []
    for path in sorted(folder.glob("SG-*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        header = re.match(r"#\s*(SG-\d+):\s*(.+)", lines[0])
        if not header:
            raise ValueError(f"Unexpected first line in {path.name}: {lines[0]!r}")
        doc_id, title = header.group(1), header.group(2).strip()
        status, category, body_start = "", "", 1
        for i, line in enumerate(lines[1:6], start=1):
            if line.startswith("Status:"):
                status = line.split(":", 1)[1].strip()
                body_start = i + 1
            elif line.startswith("Category:"):
                category = line.split(":", 1)[1].strip()
                body_start = i + 1
        body = "\n".join(lines[body_start:]).strip()
        docs.append({"doc_id": doc_id, "title": title, "status": status, "category": category, "body": body})
    if not docs:
        raise FileNotFoundError(f"No style guide documents found in {folder}")
    return docs


def make_chunks(docs: list[dict], max_chunk_tokens: int = MAX_CHUNK_TOKENS) -> list[Chunk]:
    """One chunk per document. Only documents longer than max_chunk_tokens are split at '## ' headings.

    Every chunk starts with the document id, title and status, so the model always knows
    where a rule comes from and whether it is still ACTIVE or DEPRECATED.
    """
    chunks = []
    for doc in docs:
        header = f"[{doc['doc_id']}] {doc['title']}\nStatus: {doc['status']}"
        whole = f"{header}\n{doc['body']}"
        if count_tokens(whole) <= max_chunk_tokens:
            chunks.append(Chunk(doc["doc_id"], doc["title"], doc["status"], "", whole))
            continue
        # Long document: split into the intro (text before the first "## ") and one part per section.
        parts = re.split(r"(?m)^(?=## )", doc["body"])
        for part in parts:
            part = part.strip()
            if not part:
                continue
            section = part.splitlines()[0].lstrip("# ").strip() if part.startswith("## ") else ""
            chunks.append(Chunk(doc["doc_id"], doc["title"], doc["status"], section, f"{header}\n{part}"))
    return chunks


# ------------------------------------------------------------------ embeddings


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for BM25: lowercase words and numbers."""
    return re.findall(r"[a-z0-9]+", text.lower())


class StyleGuideIndex:
    """Holds all chunks, their embedding vectors (numpy matrix) and a BM25 keyword index.

    backend:
      "gateway" - embeddings from the UPB AI Gateway (llm.embed, free, needs VPN)
      "local"   - local sentence-transformers model (works offline, needs `uv sync --extra local`)
      "none"    - no embeddings, keyword search (BM25) only (for offline tests)
    """

    def __init__(self, backend: str = "gateway", llm=None, alpha: float = DEFAULT_ALPHA,
                 style_guide_dir: Path = STYLE_GUIDE_DIR) -> None:
        if backend not in {"gateway", "local", "none"}:
            raise ValueError(f"Unknown embedding backend: {backend}")
        if backend == "gateway" and llm is None:
            raise ValueError("The gateway backend needs an LLMClient (llm=...).")
        self.backend = backend
        self.llm = llm
        self.alpha = alpha if backend != "none" else 0.0
        self.style_guide_dir = style_guide_dir
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None  # shape (n_chunks, dim), every row has length 1
        self.bm25 = None
        self._local_model = None

    # ---- building

    def build(self) -> "StyleGuideIndex":
        from rank_bm25 import BM25Okapi

        self.chunks = make_chunks(load_documents(self.style_guide_dir))
        self.bm25 = BM25Okapi([_tokenize(c.text) for c in self.chunks])
        if self.backend != "none":
            self.vectors = self._load_or_embed([c.text for c in self.chunks])
        return self

    def _model_name(self) -> str:
        return self.llm.embedding_model if self.backend == "gateway" else LOCAL_MODEL

    def _embed(self, texts: list[str]) -> np.ndarray:
        if self.backend == "gateway":
            vectors = self.llm.embed(texts)
        else:
            if self._local_model is None:
                from sentence_transformers import SentenceTransformer

                self._local_model = SentenceTransformer(LOCAL_MODEL)
            vectors = self._local_model.encode(texts, convert_to_numpy=True)
        vectors = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-12, None)  # length 1 -> dot product = cosine similarity

    def _load_or_embed(self, texts: list[str]) -> np.ndarray:
        """Embeds all chunks once and caches the matrix in .cache/ (re-used if nothing changed)."""
        key = hashlib.sha256((self._model_name() + "\n" + "\n\x00".join(texts)).encode("utf-8")).hexdigest()[:16]
        cache_file = CACHE_DIR / f"embeddings_{self.backend}_{key}.npy"
        if cache_file.exists():
            vectors = np.load(cache_file)
            if vectors.shape[0] == len(texts):
                return vectors
        vectors = self._embed(texts)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(cache_file, vectors)
        return vectors

    # ---- searching

    def search_scored(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        """Returns the k best chunks with their hybrid score (0..1)."""
        if not self.chunks:
            raise RuntimeError("Call build() first.")
        k = max(1, min(k, len(self.chunks)))

        keyword = np.asarray(self.bm25.get_scores(_tokenize(query)), dtype=np.float32)
        scores = (1 - self.alpha) * _min_max(keyword)
        if self.vectors is not None and self.alpha > 0:
            query_vector = self._embed([query])[0]
            cosine = self.vectors @ query_vector  # cosine similarity with every chunk
            scores = scores + self.alpha * _min_max(cosine)

        order = np.argsort(-scores)[:k]
        results = [(self.chunks[i], float(scores[i])) for i in order]
        return self._add_replacements(results, k)

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        """The function the lab asks for: the k most similar chunks for a query."""
        return [chunk for chunk, _ in self.search_scored(query, k)]

    def _add_replacements(self, results: list[tuple[Chunk, float]], k: int) -> list[tuple[Chunk, float]]:
        """If an old (DEPRECATED) rule was found but its ACTIVE replacement was not, put the replacement
        directly after it. So the list can be slightly longer than k; the 1,000-token limit in
        format_observation still applies."""
        found_ids = {chunk.doc_id for chunk, _ in results}
        expanded: list[tuple[Chunk, float]] = []
        for chunk, score in results:
            expanded.append((chunk, score))
            target = chunk.replaced_by
            if chunk.deprecated and target and target not in found_ids:
                replacement = next((c for c in self.chunks if c.doc_id == target), None)
                if replacement is not None:
                    expanded.append((replacement, score))
                    found_ids.add(target)
        return expanded


def _min_max(values: np.ndarray) -> np.ndarray:
    """Scales scores to 0..1 so that embedding and BM25 scores can be added."""
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-9:
        return np.zeros_like(values)
    return (values - low) / (high - low)


# ------------------------------------------------------------- observation text


def format_observation(chunks: list[Chunk], token_limit: int = OBSERVATION_TOKEN_LIMIT) -> tuple[str, list[str]]:
    """Builds the text the model receives for a search, never longer than token_limit tokens.

    Chunks are added best-first; a chunk that would break the limit is left out.
    Returns (text, list of the doc ids that were included).
    """
    intro = "Style guide passages (best match first). Only ACTIVE documents are valid rules."
    parts = [intro]
    included: list[str] = []
    for n, chunk in enumerate(chunks, start=1):
        label = chunk.doc_id + (f" / {chunk.section}" if chunk.section else "")
        candidate = "\n\n".join(parts + [f"--- Result {n}: {label} ---\n{chunk.text}"])
        if count_tokens(candidate) > token_limit:
            continue
        parts.append(f"--- Result {n}: {label} ---\n{chunk.text}")
        included.append(chunk.doc_id)
    if not included:
        # A single chunk is longer than the limit (does not happen with this guide): cut it.
        first = chunks[0].text if chunks else ""
        text = f"{intro}\n\n--- Result 1: {chunks[0].doc_id if chunks else '-'} ---\n{first}"
        while count_tokens(text) > token_limit and len(text) > 50:
            text = text[: int(len(text) * 0.9)]
        return text, [chunks[0].doc_id] if chunks else []
    return "\n\n".join(parts), included


# ------------------------------------------------------- convenience + self-test

_default_index: StyleGuideIndex | None = None


def search(query: str, k: int = 4) -> list[Chunk]:
    """Module-level search(query, k) as described in the lab specification.

    Uses a default index with gateway embeddings (or set the backend with build_default_index first).
    """
    global _default_index
    if _default_index is None:
        build_default_index()
    return _default_index.search(query, k)


def build_default_index(backend: str = "gateway") -> StyleGuideIndex:
    global _default_index
    llm = None
    if backend == "gateway":
        from common.llm_client import LLMClient

        llm = LLMClient(log_path=CACHE_DIR / "rag_selftest.jsonl")
    _default_index = StyleGuideIndex(backend=backend, llm=llm).build()
    return _default_index


# Test questions with the document that MUST be found (used to check retrieval quality).
TEST_QUESTIONS = [
    ("page title format", "SG-02"),
    ("which language attribute on the html element", "SG-02"),
    ("day mode colors background and text", "SG-11"),
    ("night mode colors", "SG-13"),
    ("accent color", "SG-14"),
    ("how is the theme switched data attribute", "SG-20"),
    ("remember the theme choice localStorage key", "SG-21"),
    ("theme toggle button", "SG-22"),
    ("member card markup", "SG-30"),
    ("hot take badge", "SG-31"),
    ("photo alt text", "SG-33"),
    ("required page sections and ids", "SG-35"),
    ("how many h1 headings", "SG-36"),
    ("footer text", "SG-40"),
    ("mobile breakpoint", "SG-50"),
    ("font family", "SG-51"),
    ("font size units", "SG-52"),
    ("animations and reduced motion", "SG-55"),
]


def _self_test(index: StyleGuideIndex, k: int, questions: list[tuple[str, str | None]]) -> None:
    hits = 0
    for question, expected in questions:
        results = index.search_scored(question, k)
        ids = [c.doc_id for c, _ in results]
        text, included = format_observation([c for c, _ in results])
        mark = ""
        if expected:
            ok = expected in included
            hits += ok
            mark = "OK  " if ok else "MISS"
        shown = ", ".join(f"{c.doc_id}({s:.2f})" for c, s in results)
        print(f"{mark:4} {question!r:52} -> {shown}   [{count_tokens(text)} tokens]")
    graded = [q for q in questions if q[1]]
    if graded:
        print(f"\nHit rate @k={k}: {hits}/{len(graded)} questions found the expected ACTIVE document.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the style guide retrieval.")
    parser.add_argument("questions", nargs="*", help="your own questions (default: built-in test questions)")
    parser.add_argument("--backend", choices=["gateway", "local", "none"], default="gateway")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--show", action="store_true", help="print the full observation text for each question")
    args = parser.parse_args()

    index = build_default_index(args.backend)
    print(f"{len(index.chunks)} chunks from {len({c.doc_id for c in index.chunks})} documents, backend={args.backend}\n")
    questions = [(q, None) for q in args.questions] or TEST_QUESTIONS
    _self_test(index, args.k, questions)
    if args.show:
        for q, _ in questions:
            print(f"\n===== {q}\n" + format_observation(index.search(q, args.k))[0])


if __name__ == "__main__":
    main()
