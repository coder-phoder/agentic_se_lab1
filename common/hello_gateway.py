"""Checks that your gateway access works.

Run from the repository root:
    uv run python common/hello_gateway.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import LLMClient  # noqa: E402


def main() -> None:
    llm = LLMClient(log_path="logs/hello_gateway.jsonl")
    print(f"Chat model:      {llm.model}")
    try:
        answer = llm.chat([{"role": "user", "content": "Say hello to a group of master students in one short sentence."}])
    except Exception as exc:
        print(f"Gateway call failed: {type(exc).__name__}: {exc}")
        print("Check: are you in the university network or connected via VPN? Is your key in .env and not expired?")
        sys.exit(1)
    print(f"Model says:      {answer}")
    print(f"Usage so far:    {llm.usage_summary()}")

    try:
        vectors = llm.embed(["hello", "world"])
        print(f"Embedding model: {llm.embedding_model} (dimension {vectors.shape[1]})")
    except Exception as exc:
        print(f"Embeddings not working ({exc}). Try the fallback embedding model or a local model, see README.md.")

    print(f"Log written to:  {llm.log_path}")


if __name__ == "__main__":
    main()
