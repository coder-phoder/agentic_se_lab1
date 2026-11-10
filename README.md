# Lab 1 – Agentic Software Engineering (WS 2026/27)

Starter material for Lab 1. The tasks, deadlines and grading are described on the lab sheet.

## Access to the UPB AI Gateway (do this first)

Every group member needs their own API key. Official guide: https://hilfe.uni-paderborn.de/AI-Gateway

1. **Activate the service** (once): log in to the Service Portal https://sp.upb.de/ with your university account →
   *Benutzerverwaltung* → *Weitere Dienste* → tab *Lehre und Studium* → *KI-Chat-Oberfläche* → *Optionen* → *Beantragen*.
   The request is approved automatically.
2. **Be in the university network:** the gateway only works from the university network (e.g. eduroam on campus)
   or via the university VPN. From home, connect the VPN first: https://hilfe.uni-paderborn.de/VPN_einrichten
3. **Create a key:** open https://ai-gateway.upb.de, log in with your university account, click *API-Key erstellen*
   and copy the key (`sk-...`). Store it safely; you can't see it again.
4. Keys **expire** after some time. If calls suddenly fail with `401`, create a new key and update your `.env`.
5. The terms of use of the university's AI services apply to the API as well.

Never commit the key, never paste it into a prompt, never put it into a file you submit.

## Setup

```bash
# 0. Install uv (once, no root needed), then open a new terminal (or: source ~/.bashrc)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 1. Python environment (Python 3.11+)
uv sync                    # or: python -m venv .venv && pip install -r requirements.txt
uv sync --extra local      # optional: local embedding / cross-encoder models (large download)

# 2. Gateway key
cp .env.example .env       # then put your key into .env (the model names are already filled in)

# 3. Check (in the university network or VPN)
uv run python common/hello_gateway.py
```

Run all commands from this directory (the repository root).

## Models, budget and limits

| Purpose | Model id | Cost |
|---|---|
| Default for all tasks (chat, agents, tool calling, judge) | `openai.gpt-6-luna` | $0.10 / 1M input tokens, $0.50 / 1M output tokens |
| Free fallback | `kiconnect.qwen3.8-27b` | free |
| Embeddings | `kiconnect.qwen3-embedding-8b` (fallback: `kiconnect.e5-mistral-7b-instruct`) | free |

- **Budget:** every student has **$20 per month** on the gateway. With `gpt-6-luna` the whole lab costs a group
  a few dollars, so you have plenty of room. It only gets expensive if you switch to one of the large models, which you don't need.
- **Fallback:** if your budget is used up (or a teammate's key can take over), use the free fallback model:
  `LLMClient(model=os.environ["LAB_FALLBACK_MODEL"])`. It is weaker, but supports tool calling.
  Say in your presentation which runs used which model.
- **Cost tracking:** `LLMClient` writes the cost of every call (`cost_usd`, reported by the gateway) into its log,
  and `llm.usage_summary()` prints tokens and cost so far. OpenCode shows the cost of a session in its UI.
- **Rate limits:** 100 requests per minute and at most 10 parallel requests per key. A normal agent loop stays far below this.
  Don't send requests from more than ~5 threads at the same time. `LLMClient` retries automatically when you hit the limit.
- **No `temperature`:** `gpt-6-luna` is a reasoning model and rejects the `temperature` parameter. Its output tokens
  include hidden reasoning tokens, so set `max_tokens` generously (or not at all).
- **Response cache:** the gateway caches responses. Sending exactly the same request again returns the stored answer
  within milliseconds (the log shows `"cache_hit": true`). Keep this in mind when you measure latency, and when you
  retry a request after a bad answer: change something (e.g. add the error message), otherwise you get the same answer again.

## Contents

| Folder | Content |
|---|---|
| `common/` | `llm_client.py` (gateway client with logging), `site_checker.py`, `embed_images.py` |
| `task1_opencode/` | OpenCode setup guide, config template, profile template |
| `task2_own_agent/` | specification, style guide (55 documents) |
| `task3_rag/` | PaderQueue dataset, questions, `evaluate.py`, `judge.py` |
| `task4_tools/` | toy repository `tinyledger`, tool interface, public tests, mock model |


## Troubleshooting

| Problem | Try this |
|---|---|
| `Command 'uv' not found` | Install uv (step 0 above) and open a new terminal, or use the venv route without uv |
| `401 Unauthorized` | Key missing in `.env`, or expired: create a new one at https://ai-gateway.upb.de |
| Connection timeout / connection refused | You are outside the university network. Connect the university VPN |

## Rules

- Never commit or submit your `.env` / API keys.
- Don't use agent or RAG frameworks (LangChain, LlamaIndex, ...) in Tasks 2–4.
- Every group member must be able to explain every part of the submission.
