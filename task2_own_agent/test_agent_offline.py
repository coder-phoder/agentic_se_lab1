"""Offline test of our agent loop with a FAKE model (no VPN, no cost).

The fake model sends a fixed script of answers - including broken ones - and we check that
agent.py reacts correctly: errors don't crash the loop, finish is only accepted after the checker
passed, human feedback continues the loop, the step limit stops the run, everything is logged.

The real website is of course written by the real model; this only tests OUR code.

Run from the repository root:
    uv run python task2_own_agent/test_agent_offline.py
"""

from __future__ import annotations

import builtins
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

TASK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TASK_DIR.parent
for _path in (str(REPO_ROOT), str(TASK_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import agent as agent_module  # noqa: E402
from common.embed_images import MIME_TYPES  # noqa: E402
from common.llm_client import count_tokens  # noqa: E402
from common.site_checker import CheckReport, CheckResult, member_names_from_content  # noqa: E402

CONTENT = REPO_ROOT / "task1_opencode" / "content"
PASS_MARKER = "<!-- OFFLINE TEST: FORCE PASS -->"


# --------------------------------------------------------------------------- fake model


class FakeOpenAI:
    """Looks like the openai client (client.chat.completions.create) but answers from a script."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(json.loads(json.dumps(params["messages"])))  # snapshot
        item = self.script.pop(0) if self.script else json.dumps(
            {"thought": "script empty", "action": "search_style_guide", "args": {"query": "footer"}})
        text, finish = item if isinstance(item, tuple) else (item, "stop")
        message = SimpleNamespace(role="assistant", content=text, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=None)


def act(action: str, **args) -> str:
    return json.dumps({"thought": f"test: {action}", "action": action, "args": args})


def page(names: list[str], pictures: dict[str, str], extra: str = "") -> str:
    cards = "\n".join(f'<article><img src="{{{{image:{pictures[n]}}}}}" alt="Photo of {n}"><h3>{n}</h3></article>'
                      for n in names)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Offline test</title></head>"
            f"<body><h1>Offline test page</h1>{cards}{extra}</body></html>")


def write(html: str) -> str:
    return act("write_site") + "\n```html\n" + html + "\n```"


# --------------------------------------------------------------------------- helpers

results: list[tuple[bool, str]] = []


def check(condition: bool, text: str) -> None:
    results.append((bool(condition), text))
    print(("PASS  " if condition else "FAIL  ") + text)


def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def observations(log: list[dict]) -> list[dict]:
    return [e for e in log if e.get("event") == "observation"]


# --------------------------------------------------------------------------- scenario 1


def scenario_full_run(tmp: Path) -> None:
    print("\n=== Scenario 1: broken answers, rejected finish, checker, feedback, accepted finish ===")
    names = member_names_from_content(CONTENT)
    images = [p for p in (CONTENT / "images").iterdir() if p.suffix.lower() in MIME_TYPES]
    pictures = {n: min((p for p in images if p.stem.lower().startswith(n.lower())),
                       key=lambda p: p.stat().st_size).name for n in names}
    good = page(names, pictures, PASS_MARKER)

    script = [
        "Hello! I will now build the website.",                                  # 1 no JSON
        act("dance"),                                                            # 2 unknown action
        act("search_style_guide"),                                               # 3 missing argument
        '{"thought": "oops", "action": "read_profiles", "args": {}',             # 4 broken JSON
        act("finish", summary="done"),                                           # 5 finish too early
        act("read_profiles"),                                                    # 6
        act("search_style_guide", query="footer text"),                          # 7
        act("search_style_guide", query="footer text"),                          # 8 repeat
        act("search_style_guide", query="footer text"),                          # 9 repeat -> warning
        write(page(names, {**pictures, names[0]: "does-not-exist.jpg"})),        # 10 unknown picture
        write(page(names, pictures).replace("{{image:", "data:image/jpeg;base64,AAAA{{")),  # 11 base64
        (act("write_site") + "\n```html\n<!doctype html><html><body>cut", "length"),        # 12 cut off
        write(page(names, pictures)),                                            # 13 real checker: FAIL
        act("finish", summary="done"),                                           # 14 rejected: check failed
        write(good),                                                             # 15 forced PASS
        act("finish", summary="first version"),                                  # 16 accepted -> feedback
        act("finish", summary="again"),                                          # 17 rejected: feedback pending
        write(good.replace("Offline test page", "Offline test page, now funnier")),  # 18 PASS again
        act("finish", summary="final version"),                                  # 19 accepted -> empty feedback
    ]
    fake = FakeOpenAI(script)
    out, log_path = tmp / "site" / "index.html", tmp / "logs" / "run_test.jsonl"

    real_check_site = agent_module.check_site

    def check_site_for_test(html, **kwargs):
        if PASS_MARKER in html:
            return CheckReport([CheckResult("offline test", True, "forced pass (fake page)")])
        return real_check_site(html, **kwargs)

    answers = iter(["please add a joke", ""])
    original_input = builtins.input
    agent_module.check_site = check_site_for_test
    builtins.input = lambda prompt="": (print(prompt + "<simulated>"), next(answers))[1]
    try:
        code = agent_module.main(["--content", str(CONTENT), "--out", str(out), "--log", str(log_path),
                                  "--embeddings", "none", "--model", "fake-model", "--max-steps", "25"],
                                 openai_client=fake)
    finally:
        agent_module.check_site = real_check_site
        builtins.input = original_input

    log = read_log(log_path)
    obs = observations(log)
    by_step = {e["step"]: e for e in obs}

    check(code == 0, "run ended with status finished (exit code 0)")
    check(len(fake.requests) == len(script), f"all {len(script)} scripted answers were used, no crash")
    for step in (1, 2, 3, 4):
        check(by_step[step]["ok"] is False and "ERROR" in by_step[step]["observation"],
              f"step {step}: invalid answer -> error observation, loop continues")
    check("not written the website yet" in by_step[5]["observation"], "step 5: finish before write_site is rejected")
    check(all(n in by_step[6]["observation"] for n in names), "step 6: read_profiles returns every member")
    check("Recommended picture" in by_step[6]["observation"], "step 6: read_profiles recommends the smallest picture")
    search_obs = by_step[7]["observation"]
    check(count_tokens(search_obs) <= 1000, f"step 7: search observation has {count_tokens(search_obs)} <= 1000 tokens")
    check("SG-40" in by_step[7]["retrieved"], "step 7: search for 'footer text' finds the ACTIVE footer rule SG-40")
    check("WARNING" in by_step[9]["observation"], "step 9: same action 3x in a row -> warning")
    check("not found" in by_step[10]["observation"], "step 10: unknown picture -> error, nothing saved")
    check("base64" in by_step[11]["observation"], "step 11: base64 written by the model is refused")
    check("cut off" in by_step[12]["observation"], "step 12: cut-off answer (finish_reason=length) is handled")
    check(by_step[13].get("version") == 1 and by_step[13]["failed_checks"], "step 13: page saved, real checker reports FAILs")
    check("did not pass" in by_step[14]["observation"], "step 14: finish rejected because the checker failed")
    check(by_step[15]["failed_checks"] == [], "step 15: checker passed")
    check(by_step[16].get("human_feedback") == "please add a joke", "step 16: finish accepted, human feedback sent back")
    check("did not write a new version" in by_step[17]["observation"], "step 17: finish rejected until feedback is applied")
    check(any(e.get("event") == "human_feedback" and e["feedback"] == "" for e in log), "step 19: empty feedback ends the run")
    check(out.exists() and "data:image/" in out.read_text(encoding="utf-8"), "website saved with embedded pictures")
    last_request = fake.requests[-1]
    full_html = sum(1 for m in last_request if m["role"] == "assistant" and "<!doctype html>" in m["content"].lower())
    removed = sum(1 for m in last_request if "[HTML removed to save tokens" in m["content"])
    check(full_html == 1 and removed == 5, f"old/invalid HTML answers compacted ({removed} removed, {full_html} kept)")
    check(all("step" in e for e in obs) and any(e.get("event") == "run_end" for e in log),
          "log has step numbers for every observation and a run_end entry")
    check(sum(1 for e in log if e.get("type") == "chat") == len(script), "log has every model request and answer")


# --------------------------------------------------------------------------- scenario 2


def scenario_step_limit(tmp: Path) -> None:
    print("\n=== Scenario 2: the model never finishes -> step limit ===")
    fake = FakeOpenAI([act("search_style_guide", query=f"topic {i}") for i in range(10)])
    log_path = tmp / "logs" / "run_limit.jsonl"
    code = agent_module.main(["--content", str(CONTENT), "--out", str(tmp / "limit.html"), "--log", str(log_path),
                              "--embeddings", "none", "--model", "fake-model", "--max-steps", "3", "--no-feedback"],
                             openai_client=fake)
    log = read_log(log_path)
    check(code == 1 and len(fake.requests) == 3, "stops after exactly 3 steps with exit code 1")
    check(any(e.get("event") == "run_end" and e["status"] == "step_limit" for e in log), "log says status step_limit")


def main() -> int:
    if not list(CONTENT.glob("*.md")):
        print(f"No profiles in {CONTENT} - add the team profiles first.")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        scenario_full_run(Path(tmp))
        scenario_step_limit(Path(tmp))
    failed = [text for ok, text in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
