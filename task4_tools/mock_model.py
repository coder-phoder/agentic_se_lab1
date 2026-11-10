"""A scripted fake model for testing your Task 4 agent loop without using the gateway.

It behaves like the OpenAI client for `chat.completions.create(...)` with tools, but ignores
the conversation and replays a fixed list of tool calls. Some of them are malicious or broken
on purpose. Your tool layer must handle all of them without crashing.

Usage:
    from common.llm_client import LLMClient
    from mock_model import MockOpenAIClient

    llm = LLMClient(model="mock", log_path="logs/mock_run.jsonl", openai_client=MockOpenAIClient())
    message = llm.chat_with_tools(messages, tools=registry.schemas())

run_cli is optional. If you don't implement it, the run_cli calls are simply rejected as unknown tools.

The script also contains the edits that fix the bugs, so after a complete mock run all tests
should pass. Only if your tools work correctly, of course.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# (description, tool name, arguments as a raw string)
SCRIPT: list[tuple[str, str, str]] = [
    ("look around", "list_files", json.dumps({"path": "."})),
    ("run the test suite", "run_tests", json.dumps({})),
    ("read the file from the first traceback", "read_file", json.dumps({"path": "src/tinyledger/ledger.py"})),
    ("MALICIOUS: path outside the workspace", "read_file", json.dumps({"path": "../secrets/canary.txt"})),
    ("BROKEN: invalid JSON arguments", "read_file", '{"path": "src/tinyledger/ledger.py"'),
    ("BROKEN: wrong argument type", "read_file", json.dumps({"path": "src/tinyledger/ledger.py", "start_line": "ten"})),
    ("MALICIOUS: tool that does not exist", "run_shell", json.dumps({"command": "cat ~/.ssh/id_rsa"})),
    ("MALICIOUS: modify a test instead of the code", "edit_file", json.dumps({
        "path": "tests/test_settle.py", "old_str": "assert 430 <= received <= 434", "new_str": "assert True"})),
    ("fix bug 1 (KeyError for people who never paid)", "edit_file", json.dumps({
        "path": "src/tinyledger/ledger.py",
        "old_str": "balances = {expense.payer: 0 for expense in self.expenses}",
        "new_str": "balances = {person: 0 for person in self.people()}"})),
    ("find where amounts are split", "search_code", json.dumps({"pattern": r"def split_evenly", "glob": "**/*.py"})),
    ("read the split function", "read_file", json.dumps({"path": "src/tinyledger/money.py", "start_line": 30, "end_line": 45})),
    ("fix bug 2 (lost cents when splitting)", "edit_file", json.dumps({
        "path": "src/tinyledger/money.py",
        "old_str": "    share = total_cents // parts\n    return [share] * parts",
        "new_str": "    share, remainder = divmod(total_cents, parts)\n"
                   "    return [share + (1 if i < remainder else 0) for i in range(parts)]"})),
    ("run the tests again", "run_tests", json.dumps({"target": "tests/test_settle.py"})),
    ("reproduce the issue", "run_cli", json.dumps({"args": ["report", "data/sample.csv", "--month", "2026-03"]})),
    ("MALICIOUS: argument injection attempt", "run_cli", json.dumps({"args": ["report; cat ../secrets/canary.txt"]})),
    ("fix bug 3 (dates parsed month-first)", "edit_file", json.dumps({
        "path": "src/tinyledger/io_csv.py",
        "old_str": "    month, day = first, second\n    if month > 12:\n        # clearly the other way round\n        month, day = second, first\n",
        "new_str": "    day, month = first, second\n"})),
    ("verify the issue is fixed", "run_cli", json.dumps({"args": ["report", "data/sample.csv", "--month", "2026-03"]})),
    ("final test run", "run_tests", json.dumps({})),
]

FINAL_ANSWER = "All tests pass and the March report is correct. I fixed three bugs in ledger.py, money.py and io_csv.py."


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    content: str | None
    tool_calls: list[_ToolCall] | None = None
    role: str = "assistant"


@dataclass
class _Choice:
    message: _Message
    finish_reason: str


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage


@dataclass
class MockOpenAIClient:
    script: list[tuple[str, str, str]] = field(default_factory=lambda: list(SCRIPT))
    step: int = 0
    received: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = self
        self.completions = self

    def create(self, **params: Any) -> _Response:
        self.received.append(params)
        prompt_tokens = sum(len(str(m.get("content") or "")) // 4 for m in params.get("messages", []))
        if self.step >= len(self.script):
            message = _Message(content=FINAL_ANSWER)
            return _Response([_Choice(message, "stop")], _Usage(prompt_tokens, 30))
        description, name, arguments = self.script[self.step]
        self.step += 1
        call = _ToolCall(id=f"call_{self.step:03d}", function=_Function(name, arguments))
        message = _Message(content=f"Step {self.step}: {description}", tool_calls=[call])
        return _Response([_Choice(message, "tool_calls")], _Usage(prompt_tokens, 40))
