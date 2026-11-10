# Task 1 – Setting up OpenCode with the UPB AI Gateway

This guide gets you from zero to a working coding agent in about 20 minutes.
Each group member does this on their own machine.

## 1. Get an API key

Follow "Access to the UPB AI Gateway" in the README in the repository root: activate the service in the
Service Portal, connect to the university network or VPN, create a key at https://ai-gateway.upb.de.
OpenCode only works with the gateway while you are in the university network or connected via VPN.

## 2. Install OpenCode

macOS / Linux / WSL:

```bash
curl -fsSL https://opencode.ai/install | bash
```

Then **open a new terminal** (or run `source ~/.bashrc`, or `source ~/.zshrc`). The installer adds
`~/.opencode/bin` to your PATH, but only new shells see it. If your shell says `Command 'opencode' not found`
and suggests `sudo snap install opencode`, ignore that: you just need a new terminal.

Alternative (any OS with Node.js 18+):

```bash
npm install -g opencode-ai
```

On Linux, if Node came from `apt`, this fails with `EACCES` on `/usr/local/lib/node_modules`.
Don't use `sudo`; use the curl installer instead.

Check the installation:

```bash
opencode --version
```

Windows users: we recommend WSL. Native Windows usually works via `npm`, but we can't support every setup.

## 3. Make your key available as an environment variable

macOS / Linux (add the line to `~/.zshrc` or `~/.bashrc` to make it permanent):

```bash
export UPB_AI_GATEWAY_KEY="paste-your-key-here"
```

Windows PowerShell:

```powershell
setx UPB_AI_GATEWAY_KEY "paste-your-key-here"
```

Open a new terminal afterwards.

## 4. Add the gateway as a provider

OpenCode reads `opencode.json` from the project directory. We provide a template in this folder.
It tells OpenCode that the gateway speaks the OpenAI API and reads the key from your environment variable:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "upb": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "UPB AI Gateway",
      "options": {
        "baseURL": "https://ai-gateway.uni-paderborn.de/v1",
        "apiKey": "{env:UPB_AI_GATEWAY_KEY}"
      },
      "models": {
        "openai.gpt-6-luna": {
          "name": "GPT-6 Luna (default)",
          "tool_call": true, "reasoning": true, "temperature": false,
          "cost": { "input": 0.10, "output": 0.50, "cache_read": 0.01 },
          "limit": { "context": 922000, "output": 128000 }
        },
        "kiconnect.qwen3.8-27b": { "name": "Qwen 3.8 27B (free fallback)", ... }
      }
    }
  },
  "model": "upb/openai.gpt-6-luna"
}
```

Use `GPT-6 Luna` for the task. The `cost` entry (USD per 1M tokens) lets OpenCode show you what a session costs.
The free Qwen model is the fallback if your budget is used up (see the README in the repository root).

The template also asks before every shell command and file edit (`"permission"` section). Keep that on at the beginning: it's the best way to see what the agent actually does.

## 5. Hello world

```bash
mkdir hello-agent && cd hello-agent
cp ../task1_opencode/opencode.json .
opencode
```

In the OpenCode terminal UI:

1. Check that the status bar shows `GPT-6 Luna (default)` (otherwise: `/models` and select it from "UPB AI Gateway").
2. Send: `Create a Python script hello.py that prints "Hello from our agent!" and run it.`
3. Watch what happens: the agent proposes a file edit and a shell command. Approve them.
4. Take a screenshot and put it in a backup slide of your presentation.

## 6. Working on the team website

- Work in the `task1_opencode/` folder, so the agent can see `content/`.
  When the agent wants to read files outside this folder (e.g. `../common/`), OpenCode asks for the
  `external_directory` permission. Reading is fine; think twice before you allow it to write outside the folder.
- Tell the agent about `embed_images.py` and `check_site.py`. It can run them itself.
- Useful commands in the OpenCode UI:
  - `/new` – new session
  - `/sessions` – switch between sessions
  - `/undo` – undo the last change of the agent
  - `/export` – export the current conversation (do this at the end of each session!)
- `AGENTS.md`: you can create a file with project instructions that OpenCode reads automatically (`/init` creates one).
  If you use it, submit it too.

## 7. Save your conversations

At the end of every session:

- In the UI: `/export`, then save the file as `conversation/session_01.md`, `session_02.md`, ...
- Or from the command line: `opencode export` (lets you pick a session and prints it as JSON). Save it as `conversation/session_01.json`.

Also write down for each session: number of prompts, tokens and cost. With GPT-6 Luna a session costs only
a few cents, and the UI rounds to cents (often `$0.00`). Exact numbers: `opencode stats`, or the JSON from
`opencode export`, where every assistant message has `tokens` (input, output, reasoning, cache read) and `cost` in USD.

## Troubleshooting

| Problem | Try this |
|---|---|
| `Command 'opencode' not found` right after installing | Open a new terminal or `source ~/.bashrc`; or run `~/.opencode/bin/opencode` directly |
| `npm ERR! code EACCES` | Use the curl installer instead of npm. Don't use `sudo npm` |
| `401 Unauthorized` | Key not set in this terminal: `echo $UPB_AI_GATEWAY_KEY` |
| Connection timeout / connection refused | You are outside the university network. Connect the university VPN (https://hilfe.uni-paderborn.de/VPN_einrichten) |
| `401 Unauthorized` although the key is set | Your key may have expired. Create a new one at https://ai-gateway.upb.de |
| Model not listed | Check the model id in `opencode.json` against the API Hub |
| Agent can't run Python | Make sure `python` works in the same terminal, or tell the agent to use `python3` / `uv run python` |
| Tool calls fail with this model | Some models are bad at tool calling. Switch back to `GPT-6 Luna` |
| `Budget has been exceeded` | Your $20 for this month are used up. Switch to the free fallback model (`/models`) |
