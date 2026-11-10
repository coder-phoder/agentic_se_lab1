"""The interface your tool layer must implement (Task 4). Do not change this file.

Your `tools.py` must define a class `ToolRegistry(ToolRegistryBase)`. Our public and hidden
tests only talk to your code through this interface:

    registry = ToolRegistry(workspace=Path("workspace"), timeout_s=60)
    registry.schemas()                                   # -> list of tool definitions
    registry.execute("read_file", '{"path": "README.md"}')  # -> ToolResult

Rules that the tests check:
  - execute() never raises. Every problem becomes ToolResult(ok=False, error="...").
  - `arguments` is the raw JSON string produced by the model. It can be invalid.
  - The limits below are respected. If output was cut, `truncated` is True.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Limits
MAX_OUTPUT_CHARS = 10_000   # max characters of the serialized output of one tool call
MAX_READ_LINES = 200        # max lines returned by one read_file call
MAX_SEARCH_RESULTS = 200    # upper bound for search_code max_results
MAX_LIST_ENTRIES = 500      # max entries returned by list_files
DEFAULT_TIMEOUT_S = 60      # subprocess timeout for run_tests and run_cli

REQUIRED_TOOLS = ["list_files", "read_file", "search_code", "run_tests", "edit_file"]
OPTIONAL_TOOLS = ["run_cli"]


@dataclass
class ToolResult:
    ok: bool
    output: Any = None          # str, or a JSON-serializable dict/list
    error: str | None = None    # message for the model if ok is False
    truncated: bool = False

    def to_content(self) -> str:
        """The string you put into the `tool` message for the model."""
        payload: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            payload["output"] = self.output
        else:
            payload["error"] = self.error
        if self.truncated:
            payload["truncated"] = True
        return json.dumps(payload, ensure_ascii=False)


class ToolRegistryBase(ABC):
    def __init__(self, workspace: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.workspace = Path(workspace)
        self.timeout_s = timeout_s

    @abstractmethod
    def schemas(self) -> list[dict]:
        """Tool definitions in the OpenAI "tools" format:

        {"type": "function",
         "function": {"name": "read_file", "description": "...",
                      "parameters": {"type": "object", "properties": {...}, "required": [...],
                                     "additionalProperties": false}}}
        """

    @abstractmethod
    def execute(self, name: str, arguments: str) -> ToolResult:
        """Validate and run one tool call. Never raises."""
