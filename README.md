# Namma Agent

### The trustworthy personal agent that measurably knows you — first-class on Windows.

Namma Agent is a **self-hosted personal AI agent**. The brain is a single API
call — native Anthropic, OpenAI, or Google, or any OpenAI-compatible endpoint
(Ollama, LM Studio, a custom base URL). Around that one call sits everything
that makes it an *agent*: a tool-calling loop with ~90 native tools, an
in-process memory engine with a **published, reproducible recall benchmark**,
event-driven **watchers** that reach out when things happen, a weekly
**self-review** that turns "it learns you" into a number with a trend line, and
a **layered trust model that is on by default and visible in the UI**.

<!-- TODO(Phase 4 demo assets): 30-second GIF here — watcher catches an email →
     Telegram ping → injection quarantine → weekly learning report. -->

Everything lives in the [`namma_agent/`](namma_agent/) Python package. No local-model
stack, no Docker requirement, no vendor server holding your data — it runs
anywhere Python does, from a Windows laptop to a 1 GB VPS.

> **Name your assistant whatever you like.** The *project* is Namma Agent; the
> *assistant you chat with* has a configurable display name. Set `assistant.name`
> in [`namma_agent/config.yaml`](namma_agent/config.yaml) (or the `ASSISTANT_NAME` env var)
> and it changes everywhere. See [Name your assistant](#name-your-assistant).

---

## Why Namma Agent?

Personal agents are having a moment — and a trust crisis. The category's public
wound is real: prompt-injection exfiltration, hijacked always-on agents,
Microsoft's guidance to treat agents as "untrusted code execution with
persistent credentials." Most projects answer with features. Namma's position
is different, and it rests on four pillars:

1. **Trust is a product surface, not plumbing.** Per-channel sender trust,
   injection screening on *everything* the agent reads, an approval gate with a
   decline audit trail, a sandboxed shell, and a secrets vault with output
   redaction — all **on by default** and all **observable live** in
   Settings → System → Security. The whole model is published in
   [docs/SECURITY.md](docs/SECURITY.md), including what Namma does *not* claim.

2. **Memory you can measure.** Long-term memory is **Engram** — native,
   in-process, SQLite-backed. Zero infrastructure: no Docker, no vector DB
   service, works offline. And it ships with a reproducible benchmark
   (`python scripts/memory_eval.py --mock`, no API key needed) currently
   scoring **recall@5 = 92%** on the offline retrieval suite — see
   [docs/BENCHMARKS.md](docs/BENCHMARKS.md). "It remembers you" is a claim;
   a recall number with a weekly trend line is a fact.

3. **Event-driven, not just scheduled.** Watchers monitor files, email, web
   pages, and your calendar with cheap zero-LLM polls, pass changes through an
   "only if it matters" gate, and reach you over Telegram (or any configured
   channel) — with destructive tools always declined in autonomous runs.

4. **Windows is a first-class target**, not a port afterthought. Job-Object
   shell sandboxing, Credential Manager secrets, DPAPI-sealed fallbacks, and
   one-click installers — built on and for Windows (and Linux/macOS too).

### How it compares (honestly)

| | **Namma Agent** | **Hermes** | **OpenClaw** |
|---|---|---|---|
| Trust model | Layered, on by default, visible in a Security tab; published threat model | Approval prompts; hosted Tool Gateway | Plugin permissions; hardening in progress after public incidents |
| Memory | Native in-process engine, **measured** (published recall benchmark) | Curated bounded memory files (excellent design, unmeasured) | Session memory + integrations |
| Proactivity | Event watchers (file/email/web/calendar) + routines | Scheduled routines | Scheduled + some triggers |
| Self-improvement | Weekly self-review: mined evidence → proposals you approve, metrics snapshots | Skill authoring | Community skill marketplace |
| Channels | 5 + CLI (deliberately few — each channel is attack surface) | Many | 29 |
| Skills ecosystem | Self-authored + self-review drafts (no marketplace) | Large ecosystem, $1.5B backing | 100+ community skills |
| Windows | First-class (Job Objects, Credential Manager, installers) | Linux/macOS-first | macOS-leaning |
| Hosting | Self-hosted only; runs on a $0 free-tier VPS | Self-hosted + hosted gateway | Self-hosted |

If you want the biggest ecosystem, pick Hermes. If you want the most channels
and community skills, pick OpenClaw. If you want an always-on agent you can
*audit* — one that quarantines what strangers tell it, sandboxes what it runs,
redacts your secrets from its own output, and shows you a number for how well
it remembers you — that's Namma.

---

## Quick start

**Want the desktop app?** The one-click installers create the environment,
install dependencies, configure your first AI provider, add a shortcut, and
launch. See **[docs/INSTALL.md](docs/INSTALL.md)**:

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

**That's it — memory included.** Engram is in-process and needs no setup, no
Docker, no extra services. Tell the assistant something about yourself, open a
new chat later, and ask it back.

### Want it always-on? Run it on a server for $0

Watchers, routines, and the messaging gateway only shine when the agent never
sleeps. **[docs/DEPLOY.md](docs/DEPLOY.md)** has the paths — including the
flagship **[Oracle free-tier walkthrough](docs/DEPLOY_ORACLE.md)** (your own
agent, $0/month, ~30 minutes, written for someone who has never opened a cloud
console) and a `docker compose up -d` path. One installer line, an access
token, and the zero-open-ports Telegram gateway by default.

---

## Memory (Engram)

Namma's long-term memory is **Engram** — a native, in-process engine, not an
external service. Design doc: [docs/MEMORY_SYSTEM_DESIGN.md](docs/MEMORY_SYSTEM_DESIGN.md).

- **Instant identity.** Who you are, your preferences, and standing
  instructions live in a bounded core memory injected into *every* turn —
  zero tool calls, zero latency.
- **Always learning.** Every message is considered for memory through an LLM
  salience gate (only durable facts are kept), then an extract → resolve
  pipeline that ADDs, UPDATEs, or invalidates facts instead of piling up
  contradictions. Facts are **bi-temporal** — the graph knows *when* something
  was true, not just that it was said.
- **Fast, fused recall.** BM25 + entity graph + optional vector embeddings,
  fused, in milliseconds — SQLite, in-process, no network hop. Works fully
  offline (recall stays BM25-only without an embeddings endpoint).
- **One brain.** All memory model calls use the model *you* picked in
  Settings — never a separately configured extractor.
- **Sleep-time self-improvement.** An idle/daily consolidation cycle merges,
  promotes, decays, and reflects, so memory quality goes up while you're away.
- **Environment memory.** A persistent model of the host machine (OS, drives,
  folders, installed tools) so file paths are never guessed.
- **Transparent and editable.** The Memory tab shows every fact, entity, and
  relation — searchable, editable, deletable, with a live graph view.
- **Measured.** `python scripts/memory_eval.py --mock` scores retrieval with
  no API key; the weekly self-review re-runs it and trends the number. See
  [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

External memory services (Cognee, Mem0, Zep, …) can still be attached as MCP
plugins under `mcp.servers` — additive, never load-bearing.

---

## Trust & security

The full model is in **[docs/SECURITY.md](docs/SECURITY.md)** — threat model,
the seven trust boundaries, and an honest "what Namma does NOT claim" section.
Every claim is observable live in **Settings → System → Security**. In one
paragraph:

Inbound messages carry a **per-channel trust level** (`owner` / `trusted` /
`untrusted`); untrusted senders get destructive tools stripped, their text
wrapped as data-not-instructions, and their would-be memory writes
**quarantined** — a stranger on Slack can't teach your agent "facts" or wipe
a folder. Everything the agent *reads* (uploads, web pages, search snippets,
RSS) passes **injection screening**; flagged content is delivered wrapped and
marked, never silently dropped. Destructive tools are **approval-gated** in
chat and **always declined** in autonomous runs (routines, watchers,
sub-agents); declines are audit-logged so the trail shows what was *asked*,
not just what ran. `run_shell` children run in a **Windows Job Object** (memory
cap, fork-bomb guard, kill-on-close) or POSIX rlimits. Secrets live in a
**vault** (Windows Credential Manager / keyring / DPAPI-sealed file), and known
secret values are **redacted** from every tool result and log line.

---

## What it can do

Namma Agent acts through tools the model calls natively — no intent regexes, no
routing graph. Adding a capability is dropping one file in `namma_agent/tools/`.

| Area            | Tools                                                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Files           | `read_file` `write_file` `list_dir` `move_path` `copy_path` `delete_path` `make_dir` `find_files` `organize_dir`                  |
| Shell / System  | `run_shell` (sandboxed) `system_info` `open_app` `list_open_apps`                                                                |
| Web             | `web_search` `web_extract` `web_crawl` (all injection-screened)                                                                  |
| Browser / Media | `open_browser_url` `search_google` `play_youtube` `play_youtube_music` `media_control`                                           |
| Network         | `ping_host` `dns_lookup` `check_port` `public_ip`                                                                                |
| Security\*      | `port_scan` `ping_sweep` `dir_enum` `dns_enum`                                                                                   |
| Weather / News  | `get_weather` `get_news`                                                                                                         |
| Smart home†     | `ha_turn_on` `ha_turn_off` `ha_get_state` `ha_set_temperature`                                                                   |
| Vision          | `take_screenshot` `read_text_from_image`                                                                                         |
| Documents       | `read_document` (pdf/docx/pptx/xlsx/html via MarkItDown) · `convert_document` (Markdown → docx/pdf/pptx/html/txt/odt/… via pandoc) |
| Scheduler       | `add_reminder` `list_reminders` `remove_reminder` (fire in background)                                                           |
| Watchers        | `create_watcher` `list_watchers` `toggle_watcher` `delete_watcher` `run_watcher_now`                                             |
| Memory (Engram) | `memory_save` `memory_search` `memory_forget` · transcripts: `search_conversations` `recall_sessions` `summarize_session` · `clear_memory` |
| Projects‖       | `search_project_documents` `search_project_history` `remember_project_note`                                                      |
| Learning Room¶  | `set_learning_plan` `mark_module_complete` `record_understanding` `remember_learning_note` `set_teaching_preference` `render_diagram` `fetch_image` `render_simulation` |
| Agent           | `delegate_task` `switch_persona` `list_personas` `about_namma`                                                                  |
| Tasks / Goals   | `add_task` `list_tasks` `complete_task` `remove_task` · `add_goal` `list_goals` `update_goal_progress` `remove_goal`             |
| Focus           | `start_focus` `focus_status` `end_focus`                                                                                         |
| Skills          | `list_skills` `use_skill` `create_skill` `update_skill`                                                                          |
| Self-authoring  | `create_tool` (writes + hot-loads new Python tools, approval-gated)                                                             |
| Comms‡          | `send_notification` (+ inbound Telegram/Discord/Slack/WhatsApp/Signal bridges)                                                  |
| Workspace       | `gmail_list` `gmail_read` `gmail_send` `calendar_agenda` `calendar_create_event`                                               |
| MCP             | `mcp_list_servers` + `mcp_<server>_<tool>` per connected server                                                                 |

\* off until `security.lab_mode: true` + `authorized_scopes` in config.
† off until `smart_home.url` + `HASS_TOKEN` are set.
‡ off until the channel's credentials are in `.env` — see [docs/COMMS.md](docs/COMMS.md).
‖ active inside a project chat with indexed documents.
¶ active inside the Learning Room.

Sensitive/destructive tools are approval-gated by default; set
`conversation.auto_approve: true` to run them without prompting (autonomous
runs still decline them regardless).

---

## Highlights

### 🛡️ Trust you can inspect

Settings → System → Security shows the live trust map per channel, the shell
sandbox state, the secrets inventory (names only), the quarantine log (what
untrusted senders tried to store, which documents and pages were flagged), and
the full approval audit trail — including destructive calls that were
*declined*. See [Trust & security](#trust--security).

### 🧠 One agent, any brain

A turn is `generate → run tools → loop → answer`. The model calls tools
natively, chains them, and streams tokens straight to the UI. Swap Anthropic
for a local Ollama model by editing one config key, and a `ProviderChain` falls
back across providers automatically when one is down.

### 🔔 Watchers — it reaches out when things happen

A watcher is *trigger + condition + action*: watch a folder, a Gmail query, a
web page, or your calendar. Polls are cheap and zero-LLM; when something
changes, one "only if it matters" model pass decides notify / act / ignore
against your stated intent — so a noisy page doesn't spam you, and the change
summary is treated as untrusted data. Actions run as scoped agent runs
(destructive tools declined) and deliver over your messaging channel. Manage
them in chat ("watch my Downloads for new PDFs") or Settings → Watchers.

### 📈 Measured self-improvement

Once a week (opt-in), Namma mines its own transcripts — failed tool runs, your
corrections, retries, repeated workflows — and drafts up to five proposals:
new skills, routines, watchers, or notes. **Proposals, never actions**: each
waits for one-click accept/reject in Settings → Learning, and accepted
automations arrive disabled. Alongside: a "what I learned this week" report
with metric snapshots (memory recall@k, fact/entity counts, tool failure rate,
token spend) so growth is a trend line, not a vibe. See
[docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### 📚 Projects with document intelligence

Group chats into **projects** with a document shelf. Every upload is
text-extracted, **screened for prompt injection**, chunked structure-aware,
and indexed into SQLite FTS5; answers are grounded with BM25 retrieval,
citations, and a data-not-instructions guard. Flagged files are quarantined
out of retrieval until you trust them.

### 🎓 Learning Room

Turn any goal — or an uploaded syllabus — into a structured learning path with
research-backed pedagogy: recall warm-ups, a running example, Socratic hints,
server-rendered diagrams and simulations, and an explicit confidence gate per
module. Completed modules flow into memory, so what you study becomes part of
what your agent knows about you.

### 🧩 Skills & self-extension

Skills are Markdown playbooks (`SKILL.md`) the assistant loads on demand and
can **author itself** after solving a novel task. When no tool covers a need,
`create_tool` writes a brand-new Python tool and hot-loads it in the same turn
(approval-gated). See [docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md).

### 🗣️ Voice & messaging

Voice is 100% browser-native (Web Speech API) — no server audio. Chat with
your assistant from your phone over Telegram, Discord, Slack, WhatsApp, or
Signal — each channel with its own trust level (see
[docs/COMMS.md](docs/COMMS.md)).

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
- **Secrets**: the built-in vault (Settings → Security) or `.env` at the project
  root (never commit it; the vault can migrate your `.env` in one click)
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
- **Document conversion:** with [`pandoc`](https://pandoc.org/installing.html) on
  PATH, `convert_document` handles every format at high fidelity; without it the
  built-in fallbacks still cover `md`, `txt`, `html`, and `docx`.
- **Diagrams (Learning Room):** `render_diagram` renders PNGs entirely
  server-side — hosted `mermaid.ink` first, local `mermaid-cli` fallback,
  text outline if neither is available.
- **Google Workspace:** the [`gws` CLI](https://github.com/googleworkspace/cli) for
  the Gmail/Calendar tools (`gws auth login` once).

---

## Documentation

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the system works, UML diagrams,
  and the reasoning behind every major technical decision. Start here.
- **[docs/SECURITY.md](docs/SECURITY.md)** — the threat model and the six trust
  boundaries; what's claimed, what isn't.
- **[docs/MEMORY_SYSTEM_DESIGN.md](docs/MEMORY_SYSTEM_DESIGN.md)** — Engram in depth:
  research survey, schema, write pipeline, recall fusion, consolidation.
- **[docs/BENCHMARKS.md](docs/BENCHMARKS.md)** — the memory eval: methodology,
  current numbers, how to reproduce them without an API key.
- **[docs/COMMS.md](docs/COMMS.md)** — connect Telegram, Signal, Slack, WhatsApp, Discord.
- **[docs/SKILLS.md](docs/SKILLS.md)** — how skills (procedural memory) work.
- **[docs/EXTENDING.md](docs/EXTENDING.md)** — create your own tools and skills.
- **[docs/PLUGINS.md](docs/PLUGINS.md)** — attach external MCP servers (memory
  providers included).
- **[docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md)** — how the assistant extends
  and reconfigures itself at runtime, and the safety model.

---

## Testing

```bash
python -m pytest namma_agent/tests/ -q       # full suite, offline/mocked, no API key
python scripts/memory_eval.py --mock         # memory benchmark, offline
```

---

## Troubleshooting

- **`ModuleNotFoundError: anthropic`** → install your provider SDK
  (`pip install anthropic` / `openai` / `google-genai`).
- **Native window doesn't open** → pywebview missing or no display; use
  `python -m namma_agent --server` and open the browser.
- **Provider/auth errors on first chat** → key missing/typo in `.env`, or
  `provider.type` doesn't match the key you set.
- **Assistant doesn't remember something you told it** → short/ephemeral
  messages are filtered by the salience gate; say "remember this: …" to force
  it, and check Settings → Memory to see exactly what's stored.

---

## License

[MIT](LICENSE). © 2026 Santhosh Reddy and the Namma Agent contributors.
