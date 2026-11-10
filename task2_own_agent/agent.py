"""agent.py - our own small coding agent (Task 2).

The agent builds the team website from the member profiles and makes it follow the
UPB Agentic SE Web Style Guide, which it has to look up with RAG (see rag.py).

Run from the repository root (VPN on):
    uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html

How it works (one "step" = one answer of the model):
    1. We send the message list (system prompt + task + everything so far) to the model.
    2. The model answers with exactly one JSON object: {"thought": ..., "action": ..., "args": {...}}
       (for write_site the HTML follows in a ```html code block).
    3. Our code checks the answer and runs the action:
         search_style_guide -> rag search, read_profiles -> profile files,
         write_site -> embed images + save + run the checker, finish -> only if the checker passed.
    4. The result ("observation") is added to the message list and the loop starts again.
    After an accepted finish we ask the human for feedback (empty input ends the run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TASK_DIR.parent
for _path in (str(REPO_ROOT), str(TASK_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from common.embed_images import MIME_TYPES, embed_images  # noqa: E402
from common.llm_client import LLMClient  # noqa: E402
from common.site_checker import check_site, member_names_from_content  # noqa: E402
from rag import StyleGuideIndex, format_observation  # noqa: E402

DEFAULT_CONTENT = REPO_ROOT / "task1_opencode" / "content"
DEFAULT_OUT = TASK_DIR / "site" / "index.html"
LOG_DIR = TASK_DIR / "logs"

# The four actions and the arguments they need (name -> type).
ACTIONS: dict[str, dict[str, type]] = {
    "search_style_guide": {"query": str},
    "read_profiles": {},
    "write_site": {},
    "finish": {"summary": str},
}

# --------------------------------------------------------------------------- prompts
# Important lab rule: no style guide text in these prompts. The agent must look the rules up.

SYSTEM_PROMPT = """You are WebAgent, a small autonomous coding agent. Your job: build ONE self-contained HTML file - \
a team website for a student lab group - from the team members' profiles, and make it follow the \
"UPB Agentic SE Web Style Guide".

You do NOT know this style guide. Its rules can only be found with the search_style_guide action. \
Never guess a rule, look it up. Rules change between versions: every passage shows its document id \
(SG-xx) and its Status. A DEPRECATED document names the document that replaces it. Only follow ACTIVE documents.

## How you answer
Every answer contains exactly ONE JSON object, nothing before it:
{"thought": "<one short sentence>", "action": "<action name>", "args": {<arguments>}}
Exception: for write_site, put the complete HTML in a ```html code block directly AFTER the JSON object.

## Actions
1. search_style_guide - args: {"query": "<one topic>"} - returns the most relevant style guide passages. \
Ask about ONE topic per search, for example "night mode colors" or "footer".
2. read_profiles - args: {} - returns all team member profiles and the list of available picture files.
3. write_site - args: {} - followed by the COMPLETE page in a ```html block. The system embeds the pictures, \
saves the file and runs an automatic checker. You get the checker report back.
4. finish - args: {"summary": "<what you built>"} - only accepted after the latest checker report passed.

## Website requirements (from the lab task)
- One single HTML file: all CSS in <style>, all JavaScript in <script>. Nothing loaded from the internet \
(no CDNs, no web fonts, no external images or scripts).
- Introduce the team and every member, using the content of their profiles. Every member gets a picture.
- Pictures: NEVER write image data (base64, data: URIs) yourself. Write placeholders exactly like \
<img src="{{image:anna.jpg}}" alt="..."> using a file name from the read_profiles list. \
The system replaces them with the real pictures.
- Responsive for phones and desktops, with a day/night mode toggle button.
- A section with the team's shared view on AI and the future of software engineering, based on the profiles.
- Funny, friendly and creative - but the facts about members must come from their profiles.

## Suggested workflow
1. read_profiles.
2. Search the style guide topic by topic, for example: page metadata, page structure and sections, \
colors in both themes, accent color, theme switching, theme persistence, toggle control, member cards, \
hot takes, photos, headings, fonts and font sizes, responsive breakpoints, footer, animation. \
Several short searches work better than one long one. Don't repeat a search you already did.
3. write_site with a complete page.
4. Read the checker report. Its messages do not quote the rules: for each FAIL, search the style guide \
for that topic, fix the page and call write_site again with the COMPLETE page.
5. When all checks pass, call finish.

You have a limited number of steps. Keep the HTML compact (no comments, no unnecessary CSS) \
so that the whole page fits into one answer."""

TASK_TEMPLATE = """Build our team website now.

- The member profiles are in: {content_dir} (use read_profiles to read them)
- The page will be saved to: {out_path}
- The team has {n} members: {names}. Every one of them must appear on the page with their picture.
- You have at most {max_steps} steps.

Start with your first action."""

HTML_HINT = re.compile(r"```html|<!doctype|<html", re.IGNORECASE)
COMPACT_NOTE = "[HTML removed to save tokens"

FORMAT_REMINDER = (
    'Answer with exactly one JSON object, for example {"thought": "I need the footer rules", '
    '"action": "search_style_guide", "args": {"query": "footer"}}. '
    "Valid actions: search_style_guide, read_profiles, write_site, finish. "
    "For write_site, put the complete HTML in a ```html block directly after the JSON."
)


# --------------------------------------------------------------------------- parsing


class ModelCallError(Exception):
    """The request to the model failed (no VPN, wrong key, budget used up, ...)."""


class ParseError(Exception):
    """The model's answer does not follow our protocol. The message is sent back to the model."""


@dataclass
class Parsed:
    thought: str
    action: str
    args: dict
    html: str | None = None


def _find_json_object(text: str) -> tuple[dict, int]:
    """Finds the first JSON object with an "action" key in the text. Returns (object, end position)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "action" in obj:
            return obj, end
    raise ParseError("Your answer contains no valid JSON object with an \"action\" field.")


def _find_html_block(text: str) -> str | None:
    """Returns the content of the first ```html code block (also if the closing ``` is missing)."""
    opening = re.search(r"```html[^\n]*\n", text, re.IGNORECASE)
    if not opening:
        return None
    start = opening.end()
    closing = text.find("```", start)
    return (text[start:closing] if closing != -1 else text[start:]).strip()


def parse_reply(text: str) -> Parsed:
    """Turns the model's answer into (thought, action, args, html) or raises ParseError."""
    if not text or not text.strip():
        raise ParseError("Your answer was empty.")
    obj, end = _find_json_object(text)

    action = obj.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ParseError(f"Unknown action {action!r}. Valid actions: {', '.join(ACTIONS)}.")

    args = obj.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ParseError(f'"args" must be a JSON object, not {type(args).__name__}.')

    for name, expected_type in ACTIONS[action].items():
        value = args.get(name)
        if not isinstance(value, expected_type) or (isinstance(value, str) and not value.strip()):
            raise ParseError(f'Action {action} needs the argument "{name}" ({expected_type.__name__}, not empty).')

    html = None
    if action == "write_site":
        html = args.get("html") if isinstance(args.get("html"), str) else None
        if html is None:
            html = _find_html_block(text[end:]) or _find_html_block(text)
        if not html:
            raise ParseError("write_site needs the complete HTML in a ```html code block directly after the JSON.")
        if not re.search(r"<html|<!doctype", html, re.IGNORECASE):
            raise ParseError("The HTML for write_site must be a complete page (<!doctype html> ... </html>).")
        if re.search(r"data:image/[a-z0-9.+-]+;base64,", html, re.IGNORECASE):
            raise ParseError("Never write base64 image data yourself. "
                             "Use placeholders like <img src=\"{{image:anna.jpg}}\" alt=\"...\">.")

    thought = obj.get("thought") if isinstance(obj.get("thought"), str) else ""
    return Parsed(thought=thought, action=action, args=args, html=html)


# --------------------------------------------------------------------------- agent


@dataclass
class Agent:
    llm: LLMClient
    index: StyleGuideIndex
    content_dir: Path
    out_path: Path
    max_steps: int = 30
    k: int = 4
    max_tokens: int | None = None
    ask_feedback: bool = True
    feedback_extra_steps: int = 10

    messages: list[dict] = field(default_factory=list)
    step: int = 0
    version: int = 0                     # how many times the site was written
    last_check_passed: bool = False
    last_report_text: str = ""
    feedback_pending: bool = False       # human feedback received, but no new version written yet
    html_message_indexes: list[int] = field(default_factory=list)  # assistant answers that contain HTML
    last_saved_index: int | None = None  # the answer whose HTML is the latest saved version
    recent_signatures: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.images_dir = self.content_dir / "images"
        self.member_names = member_names_from_content(self.content_dir)

    # ---------------------------------------------------------------- main loop

    def run(self) -> str:
        """Runs the loop. Returns "finished", "step_limit" or raises on API errors."""
        task = TASK_TEMPLATE.format(
            content_dir=self.content_dir, out_path=self.out_path, n=len(self.member_names),
            names=", ".join(self.member_names), max_steps=self.max_steps,
        )
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task}]
        self.llm.log_event({
            "event": "run_start", "content_dir": str(self.content_dir), "out_path": str(self.out_path),
            "member_names": self.member_names, "max_steps": self.max_steps, "k": self.k,
            "embedding_backend": self.index.backend, "model": self.llm.model,
        })
        print(f"Team: {', '.join(self.member_names)} | max steps: {self.max_steps} | log: {self.llm.log_path}\n")

        while self.step < self.max_steps:
            self.step += 1
            self.llm.log_event({"event": "step_start", "step": self.step})
            reply, finish_reason = self._ask_model()
            self.messages.append({"role": "assistant", "content": reply})
            if HTML_HINT.search(reply):
                self.html_message_indexes.append(len(self.messages) - 1)

            done, observation, info = self._handle_reply(reply, finish_reason)
            self._compact_old_html()
            if done:
                self._log_run_end("finished")
                print(f"\nDone after {self.step} steps. Website: {self.out_path}")
                return "finished"

            observation = self._repetition_warning(info) + observation
            self.messages.append({
                "role": "user",
                "content": f"Observation for step {self.step} (of max. {self.max_steps}):\n{observation}",
            })
            self.llm.log_event({"event": "observation", "step": self.step, **info, "observation": observation})

        print(f"\nStep limit of {self.max_steps} reached - stopping. "
              f"The last saved version (if any) is in {self.out_path}.")
        self._log_run_end("step_limit")
        return "step_limit"

    def _ask_model(self) -> tuple[str, str | None]:
        """Sends the message list to the model. Returns (answer text, finish_reason).

        We use the client's _chat_request (instead of chat) because it also gives us finish_reason;
        it writes the same log entry (request + response + usage + cost).
        """
        try:
            response = self.llm._chat_request(self.messages, None, self.max_tokens)
        except Exception as exc:
            raise ModelCallError(f"{type(exc).__name__}: {exc}") from exc
        choice = response.choices[0]
        return choice.message.content or "", choice.finish_reason

    def _handle_reply(self, reply: str, finish_reason: str | None) -> tuple[bool, str, dict]:
        """Parses one answer and runs the action. Returns (run finished?, observation, log info)."""
        if finish_reason == "length":
            print(f"Step {self.step:>2} | answer was cut off (too long)")
            return False, ("ERROR: Your answer was cut off because it was too long. Nothing was executed. "
                           "Send it again, shorter: compact CSS, no comments, no unnecessary markup."), \
                {"action": None, "ok": False, "error": "cut off (finish_reason=length)"}
        try:
            parsed = parse_reply(reply)
        except ParseError as exc:
            print(f"Step {self.step:>2} | invalid answer: {exc}")
            return False, f"ERROR: {exc} Nothing was executed.\n{FORMAT_REMINDER}", \
                {"action": None, "ok": False, "error": str(exc)}

        shown_args = {k: v for k, v in parsed.args.items() if k != "html"}
        print(f"Step {self.step:>2} | {parsed.action} {json.dumps(shown_args, ensure_ascii=False)}"
              + (f"  - {parsed.thought}" if parsed.thought else ""))
        info = {"action": parsed.action, "args": shown_args, "thought": parsed.thought}
        if parsed.html is not None:
            info["html_sha1"] = hashlib.sha1(parsed.html.encode("utf-8")).hexdigest()[:12]

        if parsed.action == "search_style_guide":
            return False, self._search(parsed.args["query"], info), info
        if parsed.action == "read_profiles":
            return False, self._read_profiles(info), info
        if parsed.action == "write_site":
            return False, self._write_site(parsed, info), info
        return self._finish(parsed.args["summary"], info)

    # ---------------------------------------------------------------- actions

    def _search(self, query: str, info: dict) -> str:
        chunks = self.index.search(query, self.k)
        text, included = format_observation(chunks)
        info.update(ok=True, retrieved=included)
        print(f"        -> {', '.join(included)}")
        return text

    def _read_profiles(self, info: dict) -> str:
        files = sorted(p for p in self.content_dir.glob("*.md") if not p.name.startswith("_"))
        parts = [f"Team members ({len(files)}): {', '.join(self.member_names)}"]
        for path in files:
            parts.append(f"===== {path.name} (member: {path.stem.capitalize()}) =====\n"
                         f"{path.read_text(encoding='utf-8').strip()}")

        images = sorted(p for p in self.images_dir.iterdir()
                        if p.is_file() and p.suffix.lower() in MIME_TYPES) if self.images_dir.is_dir() else []
        lines = [f"- {p.name} ({p.stat().st_size / 1024:.0f} KB)" for p in images]
        parts.append("Available picture files (use them as {{image:<file name>}}):\n" + ("\n".join(lines) or "- none"))
        recommended = []
        for name in self.member_names:
            own = [p for p in images if p.stem.lower().startswith(name.lower())]
            if own:
                best = min(own, key=lambda p: p.stat().st_size)
                recommended.append(f"- {name}: {best.name}")
        if recommended:
            parts.append("Recommended picture per member (the smallest file keeps the page small):\n"
                         + "\n".join(recommended))
        info.update(ok=True, n_profiles=len(files), n_images=len(images))
        print(f"        -> {len(files)} profiles, {len(images)} pictures")
        return "\n\n".join(parts)

    def _write_site(self, parsed: Parsed, info: dict) -> str:
        html = parsed.html or ""
        info["html_chars"] = len(html)
        try:
            embedded = embed_images(html, self.images_dir)
        except (FileNotFoundError, ValueError) as exc:
            info.update(ok=False, error=str(exc))
            print(f"        -> picture error: {exc}")
            return f"ERROR: {exc} Nothing was saved. Use exactly the file names from read_profiles."

        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(embedded, encoding="utf-8")
        self.last_saved_index = len(self.messages) - 1  # this answer holds the newest saved HTML
        self.version += 1
        size = len(embedded.encode("utf-8"))
        report = check_site(embedded, mode="full", member_names=self.member_names, file_size=size)
        self.last_check_passed = report.passed
        self.last_report_text = report.summary()
        self.feedback_pending = False

        failures = report.failures()
        info.update(ok=True, version=self.version, size_kb=round(size / 1024),
                    checks_passed=len(report.results) - len(failures), checks_total=len(report.results),
                    failed_checks=[r.name for r in failures])
        print(f"        -> saved version {self.version} ({size / 1024:.0f} KB), "
              f"checker: {len(report.results) - len(failures)}/{len(report.results)} passed"
              + (f", failing: {', '.join(r.name for r in failures)}" if failures else ""))

        next_step = ("All checks passed. If the page is complete, call finish."
                     if report.passed else
                     "Some checks FAIL. The messages don't quote the rules: search the style guide for each "
                     "failing topic, fix the page, then call write_site again with the COMPLETE page.")
        return (f"Saved version {self.version} to {self.out_path} ({size / 1024:.0f} KB).\n"
                f"Checker report:\n{self.last_report_text}\n\n{next_step}")

    def _finish(self, summary: str, info: dict) -> tuple[bool, str, dict]:
        if self.version == 0:
            info.update(ok=False, error="finish before write_site")
            print("        -> rejected: no website written yet")
            return False, "finish rejected: you have not written the website yet. Use write_site first.", info
        if self.feedback_pending:
            info.update(ok=False, error="finish without applying feedback")
            print("        -> rejected: human feedback not applied yet")
            return False, ("finish rejected: you received human feedback but did not write a new version yet. "
                           "Apply the feedback with write_site first."), info
        if not self.last_check_passed:
            info.update(ok=False, error="last check failed")
            print("        -> rejected: the last checker report did not pass")
            return False, ("finish rejected: the last checker report did not pass. Failing checks:\n"
                           + "\n".join(line for line in self.last_report_text.splitlines()
                                       if line.startswith("[FAIL]"))), info

        info.update(ok=True, accepted=True)
        print(f"\nThe agent says it is done: {summary}\nWebsite: {self.out_path}")
        feedback = self._get_feedback()
        self.llm.log_event({"event": "human_feedback", "step": self.step, "feedback": feedback})
        if not feedback:
            return True, "", info

        self.feedback_pending = True
        self.max_steps += self.feedback_extra_steps
        info["human_feedback"] = feedback
        print(f"        -> feedback sent to the agent (+{self.feedback_extra_steps} steps, "
              f"new max. {self.max_steps})")
        return False, (f"finish accepted. Human feedback: {feedback}\n"
                       "Please improve the website accordingly: write the COMPLETE page again with write_site "
                       "(check the style guide if needed), then finish again."), info

    # ---------------------------------------------------------------- helpers

    def _get_feedback(self) -> str:
        if not self.ask_feedback:
            return ""
        try:
            return input("Your feedback for the agent (just press Enter to end): ").strip()
        except EOFError:
            return ""

    def _compact_old_html(self) -> None:
        """Keeps the message list small: every answer with HTML is shortened to a note,
        except the answer that holds the newest SAVED version (the model may need it to make changes)."""
        for i in self.html_message_indexes:
            content = self.messages[i]["content"]
            if i == self.last_saved_index or COMPACT_NOTE in content:
                continue
            head = content.split("```html", 1)[0].strip()
            head = head if len(head) <= 400 else head[:400] + " ..."
            what = "an earlier saved version" if i < (self.last_saved_index or -1) else "an answer that was not saved"
            self.messages[i] = {"role": "assistant",
                                "content": f"{head}\n```html\n{COMPACT_NOTE}: {what}]\n```"}

    def _repetition_warning(self, info: dict) -> str:
        """Warns the model if it sends exactly the same action three times in a row."""
        signature = json.dumps([info.get("action"), info.get("args"), info.get("html_sha1"), info.get("error")],
                               sort_keys=True)
        self.recent_signatures = (self.recent_signatures + [signature])[-3:]
        if len(self.recent_signatures) == 3 and len(set(self.recent_signatures)) == 1:
            print("        -> warning: same answer three times in a row")
            return ("WARNING: you sent exactly the same action three times in a row. "
                    "Do something different (another action or another query).\n")
        return ""

    def _log_run_end(self, status: str) -> None:
        self.llm.log_event({"event": "run_end", "status": status, "steps": self.step, "versions": self.version,
                            "last_check_passed": self.last_check_passed, "usage": self.llm.usage_summary()})


# --------------------------------------------------------------------------- command line


def next_log_path() -> Path:
    """task2_own_agent/logs/run_01.jsonl, run_02.jsonl, ... (first free number)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    n = 1
    while (LOG_DIR / f"run_{n:02d}.jsonl").exists():
        n += 1
    return LOG_DIR / f"run_{n:02d}.jsonl"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Our own small coding agent that builds the team website.")
    parser.add_argument("--content", type=Path, default=DEFAULT_CONTENT, help="folder with <firstname>.md + images/")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the website is saved")
    parser.add_argument("--max-steps", type=int, default=30, help="maximum number of model answers (default 30)")
    parser.add_argument("--k", type=int, default=4, help="style guide chunks per search (default 4)")
    parser.add_argument("--model", default=None, help="chat model (default: LAB_CHAT_MODEL from .env)")
    parser.add_argument("--embeddings", choices=["gateway", "local", "none"], default="gateway",
                        help="gateway = UPB embedding model (default), local = sentence-transformers, none = BM25 only")
    parser.add_argument("--max-tokens", type=int, default=None, help="max. output tokens per answer (default: not set)")
    parser.add_argument("--log", type=Path, default=None, help="log file (default: logs/run_XX.jsonl, next free number)")
    parser.add_argument("--no-feedback", action="store_true", help="don't ask for human feedback (for tests)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, openai_client=None) -> int:
    args = parse_args(argv)
    content_dir, out_path = args.content, args.out
    if not content_dir.is_dir() or not member_names_from_content(content_dir):
        print(f"Error: no profiles (*.md) found in {content_dir}")
        return 2
    if not (content_dir / "images").is_dir():
        print(f"Error: picture folder {content_dir / 'images'} not found")
        return 2

    log_path = args.log or next_log_path()
    try:
        llm = LLMClient(model=args.model, log_path=log_path, openai_client=openai_client)
    except RuntimeError as exc:  # no key / base URL configured
        print(f"Error: {exc}\nCreate .env in the repository root (cp .env.example .env) and put your key in it.")
        return 2
    print(f"Building the style guide index (embeddings: {args.embeddings}) ...")
    try:
        index = StyleGuideIndex(backend=args.embeddings, llm=llm if args.embeddings == "gateway" else None).build()
    except ImportError as exc:
        print(f"Error: {exc}. For --embeddings local run `uv sync --extra local` first.")
        return 2
    except Exception as exc:
        if args.embeddings != "gateway":
            raise
        print(f"Error while embedding the style guide: {type(exc).__name__}: {exc}\n"
              "Check: VPN connected? Key in .env correct? (Or try --embeddings local / none.)")
        return 1

    agent = Agent(llm=llm, index=index, content_dir=content_dir, out_path=out_path, max_steps=args.max_steps,
                  k=args.k, max_tokens=args.max_tokens, ask_feedback=not args.no_feedback)
    try:
        status = agent.run()
    except KeyboardInterrupt:
        agent._log_run_end("interrupted")
        print("\nStopped by the user.")
        return 130
    except ModelCallError as exc:  # e.g. no VPN, wrong key, budget used up
        agent._log_run_end("error: model call failed")
        print(f"\nThe model call failed: {exc}\n"
              "Check: VPN connected? Key in .env correct and not expired? Budget left?")
        return 1
    print(f"Usage: {llm.usage_summary()}\nLog: {log_path}")
    return 0 if status == "finished" else 1


if __name__ == "__main__":
    sys.exit(main())
