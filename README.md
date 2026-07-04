# Namma Agent

### Intelligence for Everyone.

> **Your Trusted AI Companion. Your Agent, Your Advantage.**

Namma Agent is a **cloud-only personal AI assistant** you run yourself. The brain is
a single API call — native Anthropic, OpenAI, or Google, or any OpenAI-compatible
endpoint (Ollama, LM Studio, opencode, or a custom base URL). Around that one call
sits everything that makes it an *agent*: one tool-calling loop, a registry of ~85
tools, a **Cognee knowledge-graph memory** that remembers you across every session,
a learning-loop skill system, project knowledge bases with document RAG, a built-in
Learning Room, browser-native voice, a streaming web UI, and messaging bridges.

Everything lives in the [`namma_agent/`](namma_agent/) Python package. There is no local-model
or PyQt stack — Namma Agent is provider-agnostic and runs anywhere Python does, from
a laptop to a tiny server.

> **Name your assistant whatever you like.** The *project* is Namma Agent; the
> *assistant you chat with* has a configurable display name. Set `assistant.name`
> in [`namma_agent/config.yaml`](namma_agent/config.yaml) (or the `ASSISTANT_NAME` env var)
> and it changes everywhere — the system prompt, the web UI, the voice, and the
> messaging bridges. See [Name your assistant](#name-your-assistant).

---

## Why Namma Agent?

Claude, ChatGPT, Hermes, OpenClaw, Open Interpreter — plenty of agents already exist.
Namma is the one that stays **yours on every axis**:

- **Any brain, no lock-in.** Native Anthropic / OpenAI / Google, or any
  OpenAI-compatible endpoint (Ollama, LM Studio, opencode, …), swapped with one config
  key and an automatic fallback chain across providers. Run it fully offline on a local
  model if you want.
- **You host it; you own the data.** No walled garden, no vendor server quietly holding
  your memory.
- **It remembers you — as a knowledge graph.** All long-term memory is
  [Cognee](https://www.cognee.ai): a semantic + graph memory that connects the people,
  projects, and preferences you mention, and recalls them by *meaning*, not keywords —
  in normal chat, in Projects, and in the Learning Room. Self-hosted (fully local, no
  API key needed) or on managed Cognee Cloud. See [Memory setup](#memory-setup-cognee--ollama).
- **It acts on your real machine and life** — ~85 native tools spanning files, shell,
  browser, smart home, Gmail/Calendar, weather/news, and a security lab — not a chat
  box, and not a coding-only agent.
- **It extends itself.** `create_tool` writes and hot-loads new Python tools mid-turn;
  it authors its own `SKILL.md` playbooks after solving a novel task.
- **It teaches.** The Learning Room turns any goal or uploaded syllabus into a
  pedagogy-backed course — and what you learn flows into the memory graph.
- **It's yours to name and shape.** Configurable identity and personas.

Built in the open-source personal-agent tradition (parity-and-beyond with projects like
Hermes on comms bridges, skills, and toolsets) — but self-extending, teaching-capable,
and safe by default (we declined to port jailbreak-style "God Mode" skills).

---

## Quick start

**Want the desktop app?** The one-click installers do everything below for you —
create the environment, install dependencies, configure your first AI provider,
add a shortcut, and launch. See **[docs/INSTALL.md](docs/INSTALL.md)**:

- **Windows:** double-click `installers\install.bat`
- **macOS:** double-click `installers/Install Namma Agent.command`
- **Linux:** `bash installers/install.sh`

To set it up manually instead, from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r namma_agent/requirements.txt
```

Don't need voice or the desktop window? Install just the core + your provider:

```bash
pip install fastapi "uvicorn[standard]" pydantic PyYAML anthropic
```

### 1 · Add your API key

```bash
cp namma_agent/.env.example .env          # .env is read from the project root
```

Edit `.env` and set the key for the provider you'll use, e.g.:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Pick the provider in [`namma_agent/config.yaml`](namma_agent/config.yaml) → `provider.type`
(`anthropic` · `openai` · `google` · `ollama` · `lmstudio` · `openai_compat`).
**Local Ollama / LM Studio need no key** — point `provider.type: ollama` at a
running server for a fully offline setup.

### 2 · Build the web UI

Both the desktop window and `--server` mode serve a **pre-built** React bundle from
`namma_agent/webui/dist`. Build it once before the first run (and again after any UI
change). Node 18+ is required:

```bash
cd namma_agent/webui
npm install        # install JS dependencies
npm run build      # emit namma_agent/webui/dist
cd ../..
```

For UI development with hot-reload, run `npm run dev` in `namma_agent/webui` (Vite dev
server) alongside `python -m namma_agent --server`.

### 3 · Run it

```bash
python -m namma_agent              # native desktop window (pywebview)
python -m namma_agent --server     # backend only — open http://127.0.0.1:8000
```

`--server` is the most reliable first run (no GUI dependency). The chat UI is at
**http://127.0.0.1:8000**.

### 4 · Set up memory (next section)

Without Cognee the assistant still chats and uses every tool, but it won't
**remember you across sessions**. Setting it up is one script + one click.

---

## Memory setup (Cognee + Ollama)

Namma's long-term memory **is** [Cognee](https://www.cognee.ai) — a semantic +
knowledge-graph memory served by the official `cognee/cognee-mcp` container and
reached through Namma's built-in MCP client. It adds **zero** Python dependencies
to Namma; the only prerequisite is **Docker**.

Two ways to run it — the app works identically either way:

| Track | What runs | Needs |
| ----- | --------- | ----- |
| **Self-hosted** (default) | Cognee container + Ollama container on your machine. Fully local, key-free. | Docker |
| **Cognee Cloud** | The same container in serve mode against a managed instance. Zero local storage. | An account at [platform.cognee.ai](https://platform.cognee.ai) |

### Self-hosted, fully local (recommended first run)

**Step 1 — install Docker.** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
on Windows/macOS, or your distro's `docker` + `docker compose` on Linux. Start it.

**Step 2 — run the setup script** from the project root:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts/setup_cognee.ps1
```

```bash
# Linux / macOS
bash scripts/setup_cognee.sh
```

The script is idempotent (safe to re-run) and does five things:

1. Starts the **Ollama** container (`namma-cognee-ollama`) on the pinned
   `agi_default` Docker network.
2. Pulls **nomic-embed-text** (~275 MB) — the embedding model for semantic search.
3. Pulls **qwen2.5:7b** (~4.7 GB) — the local extraction LLM that builds the graph.
   *Using a cloud LLM instead? Skip this pull with `-SkipLocalLLM` (PowerShell) or
   `SKIP_LOCAL_LLM=1` (bash).*
4. Pulls the **`cognee/cognee-mcp:main`** image (large — first time only) and
   creates `.env.cognee` from [.env.cognee.example](.env.cognee.example) (key-free
   local defaults).
5. Creates the **`cognee-data`** volume with the right permissions, so your memory
   **persists** across restarts.

**Step 3 — one click in the app.** Start Namma, open
**Settings → MCP → Cognee**, and click **Register Cognee server**. It connects in
~30 s (the container cold-starts). The dot turns green — you're done.

From then on it just works: every chat grows the knowledge graph in the background
(`Auto-ingest`, on by default), completed Learning-Room modules are pushed into the
graph, project notes land in it, and "what do you know about me?" questions are
answered from it — even in a brand-new chat.

**Try it:** tell the assistant *"I'm Santhosh, I study CS in Bengaluru and I'm
building a drone."* Open a **new** chat later and ask *"what am I building?"* —
then watch the graph grow under **Memory** in the sidebar (recall / remember /
consolidate / forget, plus the live graph view).

### Configuring the models (Ollama or anything else)

The graph is built by an *extraction LLM* and searched with an *embedding model*.
Both are configured in **Settings → MCP → Cognee → Models & embeddings** — no file
editing needed. Three one-click presets:

| Preset | Extraction LLM | Embeddings | Character |
| ------ | -------------- | ---------- | --------- |
| **Fully local (Ollama)** *(default)* | `qwen2.5:7b` via local Ollama | `nomic-embed-text` via local Ollama | Free, private, no key. Slow graph builds on CPU (~1–3 min per memory, in the background). |
| **Hybrid (Groq + local Ollama)** | `groq/llama-3.3-70b-versatile` (free key from [console.groq.com](https://console.groq.com)) | local Ollama | Fast graph builds; embeddings stay local. |
| **OpenAI** | `gpt-4o-mini` | `text-embedding-3-small` | Fastest, everything cloud. |

Any OpenAI-compatible endpoint works too — set **Provider** to `custom`, point
**Endpoint** at `https://<host>/v1`, name the model `openai/<model-id>`, and paste
the key. Click **Save & reconnect** (takes ~30 s; it only reconnects when something
actually changed). The same settings live in [.env.cognee](.env.cognee.example) if
you prefer a file.

Local-model notes:

- `qwen2.5:7b` is the **smallest** local model that reliably produces Cognee's
  structured JSON — 3B models fail extraction. Pull others with
  `docker exec namma-cognee-ollama ollama pull <model>`.
- `LLM_ENDPOINT` must end in `/v1`; `EMBEDDING_ENDPOINT` must be the **full**
  `/api/embed` URL. The presets get this right.
- If you change the embedding model, update `EMBEDDING_DIMENSIONS` to match
  (768 for nomic-embed-text) — and re-build memory, since old vectors won't match.

### Cognee Cloud instead (zero local infra)

1. Sign up at [platform.cognee.ai](https://platform.cognee.ai) and create an
   instance — you get an instance URL (`https://….cognee.ai`) and an API key.
2. In **Settings → MCP → Cognee → Backend**, pick **Cognee Cloud**, paste both,
   and click **Connect to Cognee Cloud**.

Switching between Self-hosted and Cloud is the same panel; your instance URL and
key are remembered (in the git-ignored `.env.cognee.cloud`), so you paste them once.
Only the small MCP bridge container runs locally in cloud mode — the graph, vectors,
and embeddings all live in your cloud instance.

### Memory troubleshooting

| Symptom | Fix |
| ------- | --- |
| "server not registered" in the Cognee tab | Run the setup script, then click **Register Cognee server**. |
| Not connected / red dot | Is Docker running? `docker ps` should list `namma-cognee-ollama`. Click **↻ Reconnect**. |
| Register fails with a network error | Re-run the setup script — it (re)creates the `agi_default` network the containers share. |
| Recall works but nothing new is remembered | Graph building is backgrounded; on the fully-local preset give it a few minutes. Check **Settings → MCP → Cognee → Auto-ingest** is on. |
| Memory resets after restart | The `cognee-data` volume is missing its write perms — re-run the setup script (step 5 fixes it). |
| Extraction errors with a local model | Use `qwen2.5:7b` or larger (3B models can't produce the structured output), or switch to the Groq preset. |
| Want to start over | **Settings → MCP → Cognee → Danger zone → Forget everything**, or `docker volume rm cognee-data` while the app is stopped (then re-run the setup script). |

---

## What it can do

Namma Agent acts through tools the model calls natively — no intent regexes, no
routing graph. Adding a capability is dropping one file in `namma_agent/tools/`.

| Area            | Tools                                                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Files           | `read_file` `write_file` `list_dir` `move_path` `copy_path` `delete_path` `make_dir` `find_files` `organize_dir`                  |
| Shell / System  | `run_shell` `system_info` `open_app` `list_open_apps`                                                                            |
| Web             | `web_search` `web_extract` `web_crawl`                                                                                           |
| Browser / Media | `open_browser_url` `search_google` `play_youtube` `play_youtube_music` `media_control`                                           |
| Network         | `ping_host` `dns_lookup` `check_port` `public_ip`                                                                                |
| Security\*      | `port_scan` `ping_sweep` `dir_enum` `dns_enum`                                                                                   |
| Weather / News  | `get_weather` `get_news`                                                                                                         |
| Smart home†     | `ha_turn_on` `ha_turn_off` `ha_get_state` `ha_set_temperature`                                                                   |
| Vision          | `take_screenshot` `read_text_from_image`                                                                                         |
| Documents       | `read_document` (pdf/docx/pptx/xlsx/html via MarkItDown) · `convert_document` (Markdown → docx/pdf/pptx/html/txt/odt/… via pandoc) |
| Scheduler       | `add_reminder` `list_reminders` `remove_reminder` (fire in background)                                                           |
| Memory (Cognee)§ | `mcp_cognee_remember` `mcp_cognee_recall` `mcp_cognee_forget` (+ `remember_fact`/`recall_facts` aliases) · transcripts: `search_conversations` `recall_sessions` `summarize_session` · `clear_memory` |
| Projects‖       | `search_project_documents` `search_project_history` `remember_project_note`                                                      |
| Learning Room¶  | `set_learning_plan` `mark_module_complete` `record_understanding` `remember_learning_note` `set_teaching_preference` `render_diagram` `fetch_image` `render_simulation` |
| Agent           | `delegate_task` `switch_persona` `list_personas` `about_namma`                                                                  |
| Tasks / Goals   | `add_task` `list_tasks` `complete_task` `remove_task` · `add_goal` `list_goals` `update_goal_progress` `remove_goal`             |
| Focus           | `start_focus` `focus_status` `end_focus`                                                                                         |
| Skills          | `list_skills` `use_skill` `create_skill` `update_skill`                                                                          |
| Self-authoring  | `create_tool` (writes + hot-loads new Python tools, approval-gated)                                                             |
| Comms‡          | `send_notification` (+ inbound Telegram chat bridge)                                                                            |
| Workspace       | `gmail_list` `gmail_read` `gmail_send` `calendar_agenda` `calendar_create_event`                                               |
| MCP             | `mcp_list_servers` + `mcp_<server>_<tool>` per connected server                                                                 |

\* off until `security.lab_mode: true` + `authorized_scopes` in config.
† off until `smart_home.url` + `HASS_TOKEN` are set.
‡ off until Telegram/Discord credentials are in `.env`.
§ needs the Cognee server connected — see [Memory setup](#memory-setup-cognee--ollama).
‖ active inside a project chat with indexed documents.
¶ active inside the Learning Room.

Sensitive/destructive tools are approval-gated by default; set
`conversation.auto_approve: true` to run them without prompting.

---

## Highlights

### 🧠 One agent, any brain

A turn is `generate → run tools → loop → answer`. The model calls tools natively,
chains them, and streams tokens straight to the UI. Swap Anthropic for a local
Ollama model by editing one config key, and a `ProviderChain` falls back across
providers automatically when one is down. Missing a system binary (e.g. `nmap`)?
The tool returns a clear "install X" message instead of crashing.

### 🕸️ Memory that's a knowledge graph, not a keyword index

All long-term memory is Cognee. Chats, project notes, and finished learning modules
are ingested in the background (off the reply path) into a graph of entities and
relationships with semantic embeddings — so *"what's that thing I'm building?"*
finds the drone project even though you never used those words. The **Memory** page
in the sidebar exposes the whole lifecycle — remember, recall, consolidate, forget —
plus a live graph view, and a side-by-side compare against plain keyword search.
Chat transcripts stay in a local SQLite file (that's your chat *history*, not the
assistant's memory) and everything can be wiped from Settings.

### 📚 Projects with document intelligence

Group chats into **projects** and give each one its own document shelf (up to 25
files, 10 MB each). Every upload is text-extracted, **screened for prompt
injection**, chunked structure-aware, and indexed into SQLite FTS5. In a project
chat the assistant grounds its answers with `search_project_documents` (BM25
ranking, per-document diversity, neighbour stitching, file/section citations) —
wrapped in a *data-not-instructions* guard. Flagged files are quarantined out of
retrieval until you trust them. A project chat also carries summaries of the
project's earlier conversations, and every saved project note flows into the
Cognee graph, so it's recallable from any chat.

### 🎓 Learning Room

Turn any goal — or an uploaded **syllabus** — into a structured learning path.
Namma Agent infers your level, builds a module path (browse it as a list or on a
pannable React Flow canvas), and teaches one module at a time — each in its own
chat — with research-backed pedagogy: recall warm-ups, a running example carried
across modules, Socratic hints, and inline server-rendered diagrams, images, and
interactive simulations. It **assesses through conversation** (not multiple-choice
cards), keeping a persistent **learner model** of how you think, and a module only
advances through an explicit **confidence gate**. Every completed module's recap is
pushed into the Cognee graph — your memory literally grows from what you study.

### 🧩 Skills & self-extension

Skills are Markdown playbooks (`SKILL.md`) the assistant loads on demand and can
**author itself** after solving a novel task. When no tool covers a need at all,
`create_tool` writes a brand-new Python tool and hot-loads it in the same turn
(approval-gated). See [docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md).

### 🗣️ Browser-native voice & messaging

Voice is 100% browser-native (Web Speech API): the UI reads answers aloud and the
mic dictates input — no server audio, no models to install. Chat with your
assistant from your phone over Telegram (and Discord), with voice-message
transcription when an STT key is configured.

---

## Name your assistant

The project is **Namma Agent**, but the assistant you talk to can be called
anything. One switch, applied everywhere:

```yaml
# namma_agent/config.yaml
assistant:
  name: Jarvis
```

or, without editing any file:

```bash
ASSISTANT_NAME=Jarvis python -m namma_agent --server
```

The name flows into the model's system prompt (its self-identity), the web UI
(title, greeting, sidebar, composer), the `about_namma` self-knowledge tool, and
the Telegram `/help`. `NAMMA_*` environment-variable names (API keys, Telegram
tokens) are intentionally left unchanged — they're stable identifiers, not display
text.

---

## Configuration

- **Base config** (documented, commented): [`namma_agent/config.yaml`](namma_agent/config.yaml)
- **UI / runtime overrides**: `namma_agent/config.local.yaml` (written by the Settings
  panel; the base file is never rewritten)
- **Secrets**: `.env` at the project root (never commit it)
- **Cognee container env**: `.env.cognee` (models/embeddings; git-ignored) and
  `.env.cognee.cloud` (Cloud instance URL + key; git-ignored)
- **Provider override**: `NAMMA_CONFIG=/path/to/config.yaml` to use a different file

Configure several providers (each with its own API key) and a curated list of
switchable models from **Settings → Providers / Models** — then switch brains from
the picker at the top of any chat.

---

## Optional system tools

Each degrades gracefully — if the binary is missing, the tool returns a clear
"install X" message instead of crashing.

- **Vision:** `grim` / `scrot` / `gnome-screenshot` (capture), `tesseract` (OCR).
- **Security:** `nmap`, `gobuster`, `dig`.
- **Real browser control:** Playwright (`pip install playwright && playwright install chromium`).
- **Document conversion:** `convert_document` turns the Markdown the agent writes
  into the format a user actually asks for (Word, PDF, PowerPoint, etc.). With
  [`pandoc`](https://pandoc.org/installing.html) on PATH (a system binary, not a pip
  package) it handles every format at high fidelity. Without it, the built-in
  fallbacks still cover `md`, `txt`, `html`, and `docx` (the last via `python-docx`);
  any other target returns an "install pandoc" message.
- **Diagrams (Learning Room):** `render_diagram` produces PNGs **entirely
  server-side** — the browser never renders mermaid. It uses the hosted
  `mermaid.ink` API first (needs `requests`), then falls back to a fully local
  renderer for offline use (`pip install mermaid-cli && playwright install
  chromium`). If both are unavailable it degrades to a text outline.
- **Google Workspace:** the [`gws` CLI](https://github.com/googleworkspace/cli) for
  the Gmail/Calendar tools (`gws auth login` once).

---

## Documentation

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the system works, UML diagrams,
  and the reasoning behind every major technical decision. Start here.
- **[docs/COGNEE.md](docs/COGNEE.md)** — the Cognee memory in depth: architecture,
  the four lifecycle ops, cloud vs self-hosted, and troubleshooting.
- **[docs/SKILLS.md](docs/SKILLS.md)** — how skills (procedural memory) work and are created.
- **[docs/EXTENDING.md](docs/EXTENDING.md)** — create your own tools and skills.
- **[docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md)** — how the assistant extends
  and reconfigures itself at runtime.

---

## Testing

```bash
python -m pytest namma_agent/tests/ -q       # full suite, offline/mocked, no API key
```

---

## Troubleshooting

- **`ModuleNotFoundError: anthropic`** → install your provider SDK
  (`pip install anthropic` / `openai` / `google-genai`).
- **Native window doesn't open** → pywebview missing or no display; use
  `python -m namma_agent --server` and open the browser.
- **Provider/auth errors on first chat** → key missing/typo in `.env`, or
  `provider.type` doesn't match the key you set.
- **Assistant doesn't remember you across chats** → the Cognee server isn't
  connected. See [Memory setup](#memory-setup-cognee--ollama) — and the memory
  troubleshooting table there.

---

## License

[MIT](LICENSE). © 2026 Santhosh Reddy and the Namma Agent contributors.
