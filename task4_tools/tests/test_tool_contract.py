"""Public tests for your tool layer (Task 4).

Run from the repository root:
    uv run pytest task4_tools/tests -v

Passing these tests is necessary but not sufficient: we run additional hidden tests
(more malformed inputs and containment attacks) against your ToolRegistry.
"""

import json

import jsonschema
import pytest

from tool_contract import MAX_OUTPUT_CHARS, REQUIRED_TOOLS, ToolRegistryBase, ToolResult


def call(registry, name, **kwargs) -> ToolResult:
    result = registry.execute(name, json.dumps(kwargs))
    assert isinstance(result, ToolResult)
    json.loads(result.to_content())  # must be serializable
    return result


def text_of(result: ToolResult) -> str:
    return result.output if isinstance(result.output, str) else json.dumps(result.output)


# ------------------------------------------------------------------ schemas

def test_registry_implements_contract(registry):
    assert isinstance(registry, ToolRegistryBase)


def test_schemas_complete_and_valid(registry):
    schemas = registry.schemas()
    names = [s["function"]["name"] for s in schemas]
    for tool in REQUIRED_TOOLS:
        assert tool in names, f"missing tool {tool}"
    for schema in schemas:
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["description"].strip(), f"{function['name']} needs a description"
        parameters = function["parameters"]
        jsonschema.Draft202012Validator.check_schema(parameters)
        assert parameters["type"] == "object"
        assert parameters.get("additionalProperties") is False, f"{function['name']}: disallow extra arguments"


# --------------------------------------------------------------- happy paths

def test_list_files(registry):
    result = call(registry, "list_files", path=".")
    assert result.ok, result.error
    assert "src/tinyledger/ledger.py" in text_of(result)


def test_read_file(registry):
    result = call(registry, "read_file", path="src/tinyledger/ledger.py")
    assert result.ok, result.error
    assert "class Ledger" in text_of(result)


def test_read_file_line_range(registry):
    result = call(registry, "read_file", path="src/tinyledger/ledger.py", start_line=1, end_line=3)
    assert result.ok, result.error
    assert "class Ledger" not in text_of(result)


def test_search_code(registry):
    result = call(registry, "search_code", pattern=r"def split_evenly")
    assert result.ok, result.error
    assert "src/tinyledger/money.py" in text_of(result)


def test_run_tests_reports_failures(registry):
    result = call(registry, "run_tests")
    assert result.ok, result.error
    output = result.output
    assert isinstance(output, dict), "run_tests should return a structured summary"
    assert output["failed"] == 2
    assert output["passed"] > 0
    failing = json.dumps(output)
    assert "test_balances_participant_who_never_paid" in failing
    assert "test_settle_uneven_three_way_split" in failing


def test_run_cli(registry):
    if "run_cli" not in [s["function"]["name"] for s in registry.schemas()]:
        pytest.skip("run_cli is optional")
    result = call(registry, "run_cli", args=["report", "data/sample.csv", "--month", "2026-03"])
    assert result.ok, result.error
    assert "Total" in text_of(result)


def test_edit_file(registry, workspace):
    result = call(registry, "edit_file", path="src/tinyledger/ledger.py",
                  old_str="balances = {expense.payer: 0 for expense in self.expenses}",
                  new_str="balances = {person: 0 for person in self.people()}")
    assert result.ok, result.error
    assert "self.people()" in (workspace / "src/tinyledger/ledger.py").read_text()


# ---------------------------------------------------------- invalid input

def test_invalid_json(registry):
    result = registry.execute("read_file", '{"path": "README.md"')
    assert not result.ok and result.error


def test_unknown_tool(registry):
    result = call(registry, "run_shell", command="ls")
    assert not result.ok and result.error


def test_missing_required_argument(registry):
    assert not call(registry, "read_file").ok


def test_extra_argument(registry):
    assert not call(registry, "read_file", path="README.md", mode="w").ok


def test_wrong_type(registry):
    assert not call(registry, "read_file", path="README.md", start_line="one").ok


def test_edit_requires_unique_match(registry):
    result = call(registry, "edit_file", path="src/tinyledger/ledger.py", old_str="expense", new_str="x")
    assert not result.ok


# ---------------------------------------------------------- containment

def test_no_reading_outside_workspace(registry):
    result = call(registry, "read_file", path="../secrets/canary.txt")
    assert not result.ok
    assert "CANARY" not in result.to_content()


def test_no_editing_tests(registry, workspace):
    before = (workspace / "tests/test_settle.py").read_text()
    result = call(registry, "edit_file", path="tests/test_settle.py",
                  old_str="assert 430 <= received <= 434", new_str="assert True")
    assert not result.ok
    assert (workspace / "tests/test_settle.py").read_text() == before


def test_output_is_bounded(registry, workspace):
    (workspace / "src" / "big.txt").write_text("x" * 100 + "\n" * 1 + ("line\n" * 50_000))
    result = call(registry, "read_file", path="src/big.txt")
    assert result.ok
    assert result.truncated
    assert len(result.to_content()) <= MAX_OUTPUT_CHARS + 1000
