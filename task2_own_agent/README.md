# Task 2 – Our own coding agent (Team 25)

A small coding agent, written from scratch in Python (no agent frameworks), that builds our team website
from the member profiles and makes it follow the *UPB Agentic SE Web Style Guide*. The agent does not
know the style guide: it looks the rules up with retrieval (RAG) and gets feedback from the site checker.

| File | What it is |
|---|---|
| `rag.py` | Loads and chunks the 55 style guide documents, embeds them, hybrid search, 1,000-token observations |
| `agent.py` | The agent loop: JSON protocol, 4 actions, error handling, step limit, finish rule, human feedback, logging |
| `test_agent_offline.py` | Offline test of the loop with a scripted fake model (no VPN, no cost) |
| `logs/run_XX.jsonl` | Complete log of a run (every request/answer, every observation, feedback) |
| `site/index.html` | The website produced by the logged run |

## How to run

From the repository root, with the uni VPN connected and the key in `.env`:

```bash
uv run python task2_own_agent/agent.py --content task1_opencode/content --out task2_own_agent/site/index.html
```

The agent prints one line per step. When it calls `finish` and the checker has passed, it asks for feedback
on the terminal: type feedback to let it continue, or press Enter to end the run.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--content` | `task1_opencode/content` | folder with `<firstname>.md` profiles and `images/` |
| `--out` | `task2_own_agent/site/index.html` | where the website is saved |
| `--max-steps` | `30` | maximum number of model answers (each human feedback adds 10) |
| `--k` | `4` | number of style guide chunks per search |
| `--model` | `LAB_CHAT_MODEL` from `.env` | chat model, e.g. the free fallback `kiconnect.qwen3.8-27b` |
| `--embeddings` | `gateway` | `gateway` (UPB embedding model), `local` (sentence-transformers, needs `uv sync --extra local`), `none` (BM25 only) |
| `--max-tokens` | not set | max. output tokens per answer (not set = no limit, avoids cut-off pages) |
| `--log` | next free `logs/run_XX.jsonl` | log file |
| `--no-feedback` | off | don't ask for human feedback (for tests) |

Other commands:

```bash
uv run python task2_own_agent/rag.py                     # retrieval self-test: 18 questions with known answers
uv run python task2_own_agent/rag.py "footer" --show     # show what the model gets for one query
uv run python task2_own_agent/test_agent_offline.py      # loop test with a fake model (27 checks)
uv run python task2_own_agent/check_site.py task2_own_agent/site/index.html --content task1_opencode/content
```

## Design decisions

**Chunking.** The style guide documents are short (28–144 words) and each one is about one topic, so we use
**one chunk per document**. Only a document longer than 300 tokens would be split at its `## ` headings
(the current guide has no document that long). Every chunk starts with a small header – document id, title and status line, e.g.
`[SG-11] Day mode palette (version 2)` / `Status: ACTIVE (version 2)` – so the model always sees where a
rule comes from and whether it is still valid. Splitting smaller would separate a rule from its status line.

**Embedding model and search.** Default: the gateway model `kiconnect.qwen3-embedding-8b` via `llm.embed`
(free). The vectors are normalised and kept in a numpy matrix, so cosine similarity is a dot product.
They are cached in `.cache/` (not submitted) and only recomputed when the guide changes.
We combine this with **BM25 keyword search** (`rank-bm25`): `score = 0.7 · cosine + 0.3 · BM25`, both scaled to 0..1.
Embeddings find rules by meaning ("remember the theme choice" → persistence), BM25 helps with exact words
("footer", "breakpoint", "h1"). With `--embeddings none` the same code runs BM25 only, which already finds
the expected ACTIVE document for 18/18 test questions (`rag.py` self-test).

**Deprecated rules.** Five documents are DEPRECATED and name their replacement. If a search returns a
deprecated document but not its replacement, `rag.py` adds the ACTIVE replacement right after it.
The status line in every chunk and the system prompt tell the model to follow ACTIVE documents only.

**k and the 1,000-token limit.** `k = 4`: four whole documents are typically 300–750 tokens, enough for
one topic and its neighbours. `format_observation` adds chunks best-first and measures the complete
observation with `count_tokens`; a chunk that would exceed 1,000 tokens is left out.

**Prompt design.** The system prompt explains the role, the JSON protocol, the four actions, the lab
requirements (single file, no internet, placeholders for pictures, responsive, day/night toggle, team view
on AI) and a suggested workflow (profiles → search topic by topic → write → fix failures → finish).
It contains **no style guide text** – only general topic names to search for. The task message contains
the content folder, output path, member names and the step budget.

**Protocol and invalid output.** One JSON object per answer: `{"thought", "action", "args"}`; for `write_site`
the HTML follows in a ```` ```html ```` block (`{"html": ...}` inside args is also accepted).
The parser finds the first JSON object with an `action` key (text or ```json fences around it are tolerated).
Every problem becomes an **error observation** and counts as a step, the loop never crashes:
no JSON / broken JSON, unknown action, missing or empty arguments, missing or incomplete HTML,
base64 image data written by the model, unknown picture file, answer cut off (`finish_reason = "length"`).
The error text says exactly what was wrong and repeats the correct format.

**Finish rule and human feedback.** `finish` is rejected if no site was written yet, if the last checker
report did not pass, or if human feedback was given but no new version was written. After an accepted
`finish` the user is asked for feedback: non-empty feedback goes back to the model as a new user message
(and adds 10 steps), empty input ends the run.

**Context control.** Old HTML versions are the biggest part of the message list. After each step, every
answer that contains HTML is replaced by a short note, except the one holding the newest saved version.
After `write_site` the model gets only the checker report back, never the page with embedded pictures.
`read_profiles` recommends the smallest picture per member, so the file stays small.

**Loop safety.** Step limit (default 30), a warning when the model sends exactly the same action three
times in a row, clear messages for network/key/budget problems.

**Logs.** `LLMClient(log_path=...)` logs every request (full message list) and answer with tokens and cost.
We add our own events: `run_start`, `step_start` (step number), `observation` (step, action, args,
result, checker results), `human_feedback`, `run_end` (status, steps, usage).

## Known limitations

- The message list still grows with every step (each search result stays in it); a very long run gets slower
  and more expensive. We only compact old HTML.
- The model may still ignore a DEPRECATED marker or invent a rule it did not search for; the checker catches
  most of these, but not rules the checker does not test (e.g. bio length, card order).
- The checker is the only "test" of the page. A page can pass all checks and still look bad.
- The agent rewrites the complete page for every change (no partial edits), which costs output tokens.
- `count_tokens` is an estimate (tiktoken `cl100k_base`); the gateway models use other tokenizers.
- The run depends on the UPB gateway (VPN). With `--embeddings local` only the chat model needs it.
- The gateway caches identical requests, so a repeated run with identical messages returns the stored answers.
