# Namma Agent — Project Instructions

Namma Agent is a **cloud-only** personal AI assistant. The brain is an API call
(native Anthropic / OpenAI / Google, or any OpenAI-compatible endpoint). The
entire application lives in the [`namma_agent/`](namma_agent/) package — there is no
local-model, intent-recognizer, or PyQt stack. (The legacy v1 tree was removed;
git history holds it if you ever need it.)

## Architecture

```
namma_agent/
├── config.py / config.yaml      — config loader (+ config.local.yaml overlay) + .env
├── service.py                   — NammaAgentService: wires provider + tools + memory + agent
├── app.py / __main__.py         — launcher (uvicorn + pywebview window; --server for headless)
├── core/
│   ├── agent.py                 — THE agent loop (generate → tools → loop → final, streaming)
│   ├── providers/               — provider abstraction (anthropic/openai/google/openai_compat + chain)
│   ├── tools.py                 — ToolRegistry (neutral defs + approval gate)
│   ├── memory.py                — single SQLite (sessions/turns/facts FTS5/audit) + notes
│   ├── docindex.py / docscan.py — project document RAG (chunk/index/retrieve) + injection screening
│   ├── learning_nudge.py        — opt-in "it's been a while" Telegram nudges for idle topics
│   ├── persona.py               — persona YAML → system prompt
│   ├── skills.py                — SKILL.md procedural memory / learning loop
│   ├── narration.py / events.py — spoken progress + event bus
│   └── browser_controller.py    — Playwright-driven visible browser
├── tools/                       — auto-discovered tool modules (one register() per file)
├── personas/                    — core (built-in default; users add their own to ~/.namma_agent/personas)
├── comms/  voice/  mcp/  server/  webui/   — bridges, TTS+STT, MCP client, FastAPI, React UI
└── tests/                       — the test suite (offline/mocked)
```

Run: `python -m namma_agent --server` then open http://127.0.0.1:8000.
Test: `python -m pytest namma_agent/tests/ -q` (no API key needed).

## The assistant's name is configurable — never hard-code it

`assistant.name` in `namma_agent/config.yaml` (or the `ASSISTANT_NAME` env var) is the
**single source of truth** for what the assistant is called. Resolve it via
`namma_agent.config.assistant_name()`. It flows into the system prompt, the web UI, the
about tool, and Telegram.

When you add user-facing text that names the assistant:
- **Backend / prompts:** use the `{name}` placeholder (the persona renderer
  substitutes `self.name`) or read `assistant_name()` directly.
- **Web UI:** read it from `config.assistant_name` (already fetched via
  `/api/config`) and thread it down as a prop — don't hard-code the assistant's name.
- **Leave `NAMMA_*` env-var names alone** (`NAMMA_API_KEY`, `NAMMA_TELEGRAM_TOKEN`,
  etc.) — those are stable identifiers, not display text.

The Python package/dir is `namma_agent` and stays that way regardless of the display name.

## Adding a tool

1. Create `namma_agent/tools/<name>.py` with a `register(registry)` function that calls
   `registry.register(name, description, json_schema, handler)`. It's auto-discovered.
2. Params are **JSON Schema** (no intent regex — the model calls tools natively).
3. Destructive/sensitive actions: add the tool name to the safety classification so
   it's approval-gated; degrade gracefully when an external binary is missing
   (return a clear "install X" error, don't crash).
4. Add a focused test under `namma_agent/tests/test_<area>.py`.

## Platform notes

Cross-platform (Linux + Windows). Guard platform-specific code with
`platform.system()` / `os.name`. Patterns already in use: `start_new_session=True`
(POSIX) vs `creationflags=DETACHED_PROCESS` (Windows); `.venv/bin/python3` vs
`.venv/Scripts/python.exe`; always pass `encoding="utf-8", errors="replace"` to
`subprocess.run(..., text=True)`.

## Response logging

After every query response, save the exchange to `responses/` in the project root:
- Filename: `YYYY-MM-DD_HH-MM-SS.md` (the time the query was received)
- Contents: `## Prompt` (exact user message) + `## Response` (the work produced)

In plan mode, also save the plan to `plan/YYYY-MM-DD_HH-MM-SS_plan.md`. Both folders
are append-only logs — never modify a saved file after writing it.
