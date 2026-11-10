"""Thin client for the UPB AI Gateway (OpenAI-compatible API).

Every request and response is appended to a JSONL log file, so you always have a
complete record of the conversation with the model. Each entry also contains the cost of
the call in USD, as reported by the gateway (header `x-litellm-response-cost`).

Usage:
    from common.llm_client import LLMClient

    llm = LLMClient(log_path="logs/run_01.jsonl")
    answer = llm.chat([{"role": "user", "content": "Hello!"}])
    vectors = llm.embed(["first text", "second text"])        # numpy array (n, dim)
    message = llm.chat_with_tools(messages, tools=[...])       # for Task 4
    print(llm.usage_summary())                                 # tokens + cost so far

Configuration comes from environment variables (put them in .env, see .env.example):
    UPB_AI_GATEWAY_KEY, UPB_AI_GATEWAY_BASE_URL,
    LAB_CHAT_MODEL, LAB_FALLBACK_MODEL, LAB_EMBEDDING_MODEL

Note: the default model (gpt-6-luna) is a reasoning model and does not accept `temperature`.
Its output tokens include hidden reasoning tokens, so keep `max_tokens` generous.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv not installed: rely on the real environment
        return
    load_dotenv(REPO_ROOT / ".env")


_load_env()


def count_tokens(text: str) -> int:
    """Approximate number of tokens in `text`.

    Uses tiktoken's cl100k_base encoding. The models on the gateway use different
    tokenizers, so treat this as an estimate. Falls back to len(text) / 4.
    """
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        embedding_model: str | None = None,
        log_path: str | Path | None = None,
        max_retries: int = 5,
        timeout_s: float = 120,
        openai_client: Any = None,
    ) -> None:
        """
        model:           default chat model (falls back to $LAB_CHAT_MODEL)
        embedding_model: default embedding model (falls back to $LAB_EMBEDDING_MODEL)
        log_path:        JSONL file for the request/response log
                         (default: logs/llm_<timestamp>.jsonl in the current directory)
        timeout_s:       timeout per request; a request that hangs longer is retried
        openai_client:   inject your own client object (e.g. a fake for testing)
        """
        self.model = model or os.environ.get("LAB_CHAT_MODEL")
        self.embedding_model = embedding_model or os.environ.get("LAB_EMBEDDING_MODEL")
        self.max_retries = max_retries

        if openai_client is None:
            from openai import OpenAI

            api_key = os.environ.get("UPB_AI_GATEWAY_KEY")
            base_url = os.environ.get("UPB_AI_GATEWAY_BASE_URL")
            if not api_key or not base_url:
                raise RuntimeError(
                    "UPB_AI_GATEWAY_KEY and UPB_AI_GATEWAY_BASE_URL must be set (see .env.example)."
                )
            # Retries happen in _with_retries (with logging), not inside the SDK.
            openai_client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0)
        self._client = openai_client

        if log_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = Path("logs") / f"llm_{stamp}.jsonl"
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0
        self.n_calls = 0

    # ------------------------------------------------------------------ chat

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a list of messages, return the text of the answer."""
        response = self._chat_request(messages, model, max_tokens, **kwargs)
        return response.choices[0].message.content or ""

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        tool_choice: str | dict = "auto",
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """Native function calling. Returns the assistant message object.

        message.content      – text (may be None)
        message.tool_calls   – list of tool calls (may be None); each has
                               .id, .function.name, .function.arguments (raw JSON string)
        Append it to the history with `message_to_dict(message)`.
        """
        response = self._chat_request(
            messages, model, max_tokens, tools=tools, tool_choice=tool_choice, **kwargs
        )
        return response.choices[0].message

    def _chat_request(self, messages, model, max_tokens, **kwargs):
        params: dict[str, Any] = {"model": model or self.model, "messages": messages}
        if params["model"] is None:
            raise RuntimeError("No chat model configured (set LAB_CHAT_MODEL or pass model=...).")
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        params.update(kwargs)

        start = time.time()
        response, meta = self._with_retries(lambda: self._create(self._client.chat.completions, **params))
        duration = time.time() - start

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        self.total_prompt_tokens += prompt_tokens or 0
        self.total_completion_tokens += completion_tokens or 0
        self._count(meta)

        self._log(
            {
                "type": "chat",
                "model": params["model"],
                "request": {k: v for k, v in params.items() if k != "model"},
                "response": message_to_dict(response.choices[0].message),
                "finish_reason": response.choices[0].finish_reason,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": getattr(details, "reasoning_tokens", None),
                    "cached_prompt_tokens": getattr(prompt_details, "cached_tokens", None),
                },
                **meta,
                "duration_s": round(duration, 3),
            }
        )
        return response

    # ------------------------------------------------------------ embeddings

    def embed(self, texts: list[str], model: str | None = None, batch_size: int = 64) -> np.ndarray:
        """Embed a list of texts. Returns a float32 array of shape (len(texts), dim).

        Only the number of texts is logged, not the texts themselves.
        """
        model = model or self.embedding_model
        if model is None:
            raise RuntimeError("No embedding model configured (set LAB_EMBEDDING_MODEL or pass model=...).")
        vectors: list[list[float]] = []
        cost = 0.0
        start = time.time()
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response, meta = self._with_retries(lambda: self._create(self._client.embeddings, model=model, input=batch))
            vectors.extend(item.embedding for item in response.data)
            self._count(meta)
            cost += meta["cost_usd"] or 0.0
        self._log(
            {
                "type": "embedding",
                "model": model,
                "n_texts": len(texts),
                "cost_usd": cost,
                "duration_s": round(time.time() - start, 3),
            }
        )
        return np.asarray(vectors, dtype=np.float32)

    def usage_summary(self) -> str:
        """One line with calls, tokens and cost so far (for this client object)."""
        return (
            f"{self.n_calls} calls, {self.total_prompt_tokens} prompt + {self.total_completion_tokens} completion tokens, "
            f"${self.total_cost_usd:.5f}"
        )

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _create(endpoint, **params):
        """Calls endpoint.create and returns (response, meta) with the cost reported by the gateway.

        The gateway also caches responses: an identical request returns the stored answer
        (meta["cache_hit"] is True). This matters when you measure latency or retry a request.
        """
        raw_api = getattr(endpoint, "with_raw_response", None)
        if raw_api is None:  # fake/mock client without HTTP headers
            return endpoint.create(**params), {"cost_usd": None, "cache_hit": None}
        raw = raw_api.create(**params)
        cost = raw.headers.get("x-litellm-response-cost")
        try:
            cost = float(cost) if cost is not None else None
        except ValueError:
            cost = None
        return raw.parse(), {"cost_usd": cost, "cache_hit": raw.headers.get("x-litellm-cache-key") is not None}

    def _count(self, meta: dict) -> None:
        self.n_calls += 1
        self.total_cost_usd += meta["cost_usd"] or 0.0

    def _with_retries(self, fn):
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:  # openai raises typed errors; we check by name to stay lightweight
                name = type(exc).__name__
                status = getattr(exc, "status_code", None)
                retryable = name in {"RateLimitError", "APIConnectionError", "APITimeoutError"} or (
                    isinstance(status, int) and status >= 500
                )
                if not retryable or attempt == self.max_retries:
                    if "budget" in str(exc).lower():
                        print(
                            "[llm_client] Your gateway budget seems to be used up. Switch to the free fallback "
                            "model: model=os.environ['LAB_FALLBACK_MODEL'] (see README)."
                        )
                    raise
                print(f"[llm_client] {name}, retrying in {delay:.0f}s ...")
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def _log(self, entry: dict) -> None:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def log_event(self, event: dict) -> None:
        """Write your own entries into the same log (e.g. tool results, human feedback)."""
        self._log({"type": "event", **event})


def message_to_dict(message: Any) -> dict:
    """Convert an assistant message object from the API into a plain dict for the history."""
    if isinstance(message, dict):
        return message
    result: dict[str, Any] = {"role": getattr(message, "role", "assistant"), "content": message.content}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in tool_calls
        ]
    return result
