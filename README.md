# FRIDAY

A cloud-only personal AI assistant. The brain is an API call — native
Anthropic, OpenAI, or Google, or any OpenAI-compatible endpoint (Ollama,
LM Studio, opencode, or a custom base URL). One agent loop, a tool registry,
cross-session memory, a learning-loop skill system, voice (Piper TTS + local
STT), a web UI, and messaging bridges.

Everything lives in the [`friday/`](friday/) package. There is no local-model or
PyQt stack — the assistant is provider-agnostic and runs anywhere Python does.

> **Rename it to whatever you like.** FRIDAY is just the default name. Set
> `assistant.name` in [`friday/config.yaml`](friday/config.yaml) (or the
> `ASSISTANT_NAME` env var) and it changes everywhere — the system prompt, the
> web UI, the voice, and the messaging bridges. See [Rename](#rename-the-assistant).

## Quick start

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r friday/requirements.txt
```

Don't need voice or the desktop window? Install just the core + your provider:

```bash
pip install fastapi "uvicorn[standard]" pydantic PyYAML anthropic
```

### Add your API key

```bash
cp friday/.env.example .env          # .env is read from the project root
```

Edit `.env` and set the key for the provider you'll use, e.g.:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Pick the provider in [`friday/config.yaml`](friday/config.yaml) → `provider.type`
(`anthropic` · `openai` · `google` · `ollama` · `lmstudio` · `openai_compat`).
**Local Ollama / LM Studio need no key** — point `provider.type: ollama` at a
running server for a fully offline setup.

### Build the web UI

Both the desktop window and `--server` mode serve a **pre-built** React bundle
from `friday/webui/dist`. Build it once before the first run (and again after any
UI change). Node 18+ is required:

```bash
cd friday/webui
npm install        # install JS dependencies
npm run build      # emit friday/webui/dist
cd ../..
```

For UI development with hot-reload, run `npm run dev` in `friday/webui` (Vite dev
server) alongside `python -m friday --server`.

### Run it

```bash
python -m friday              # native desktop window (pywebview)
python -m friday --server     # backend only — open http://127.0.0.1:8000
```

`--server` is the most reliable first run (no GUI dependency). The chat UI is at
**http://127.0.0.1:8000**.

## Rename the assistant

One switch, applied everywhere. Either:

```yaml
# friday/config.yaml
assistant:
  name: Jarvis
```

or, without editing any file:

```bash
ASSISTANT_NAME=Jarvis python -m friday --server
```

The name flows into the model's system prompt (its self-identity), the web UI
(title, greeting, sidebar, composer), the `about_*` self-knowledge tool, and the
Telegram `/help`. `FRIDAY_*` environment-variable names (API keys, Telegram
tokens) are intentionally left unchanged.

## What it can do

| Area           | Tools                                                                                                                              |
| ----------------| ------------------------------------------------------------------------------------------------------------------------------------|
| Files          | `read_file` `write_file` `list_dir` `move_path` `copy_path` `delete_path` `make_dir` `find_files` `organize_dir`                   |
| Shell / System | `run_shell` `system_info` `open_app` `list_open_apps`                                                                              |
| Web            | `web_search` `web_extract` `web_crawl`                                                                                             |
| Browser        | `open_browser_url` `search_google` `play_youtube` `play_youtube_music` `media_control`                                             |
| Network        | `ping_host` `dns_lookup` `check_port` `public_ip`                                                                                  |
| Security\*     | `port_scan` `ping_sweep` `dir_enum` `dns_enum`                                                                                     |
| Weather / News | `get_weather` `get_news`                                                                                                           |
| Smart home†    | `ha_turn_on` `ha_turn_off` `ha_get_state` `ha_set_temperature`                                                                     |
| Vision         | `take_screenshot` `read_text_from_image`                                                                                           |
| Documents      | `read_document` (pdf/docx/pptx/xlsx/html via MarkItDown) · `convert_document` (Markdown → docx/pdf/pptx/html/txt/odt/… via pandoc) |
| Scheduler      | `add_reminder` `list_reminders` `remove_reminder` (fire in background)                                                             |
| Memory         | `remember_fact` `recall_facts` `forget_fact` `remember_note` `read_memory` `search_conversations` `recall_sessions`                |
| Agent          | `delegate_task` `switch_persona` `list_personas` `about_friday`                                                                    |
| Tasks / Goals  | `add_task` `list_tasks` `complete_task` `remove_task` · `add_goal` `list_goals` `update_goal_progress` `remove_goal`               |
| Focus          | `start_focus` `focus_status` `end_focus`                                                                                           |
| Skills         | `list_skills` `use_skill` `create_skill` `update_skill`                                                                            |
| Comms‡         | `send_notification` (+ inbound Telegram chat bridge)                                                                               |
| Workspace      | `gmail_list` `gmail_read` `gmail_send` `calendar_agenda` `calendar_create_event`                                                   |
| MCP§           | `mcp_list_servers` + `mcp_<server>_<tool>` per connected server                                                                    |

\* off until `security.lab_mode: true` + `authorized_scopes` in config.
† off until `smart_home.url` + `HASS_TOKEN` are set.
‡ off until Telegram/Discord credentials are in `.env`.
§ only when `mcp.servers` are configured.

Sensitive/destructive tools are approval-gated by default; set
`conversation.auto_approve: true` to run them without prompting.

## Configuration

- **Base config** (documented, commented): [`friday/config.yaml`](friday/config.yaml)
- **UI / runtime overrides**: `friday/config.local.yaml` (written by the Settings
  panel; the base file is never rewritten)
- **Secrets**: `.env` at the project root (never commit it)
- **Provider override**: `FRIDAY_CONFIG=/path/to/config.yaml` to use a different file

## Optional system tools

Each degrades gracefully — if the binary is missing, the tool returns a clear
"install X" message instead of crashing.

- **Voice TTS:** the `piper` binary + a `.onnx` voice model on PATH.
- **Vision:** `grim` / `scrot` / `gnome-screenshot` (capture), `tesseract` (OCR).
- **Security:** `nmap`, `gobuster`, `dig`.
- **Real browser control:** Playwright (`pip install playwright && playwright install chromium`).
- **Document conversion:** `convert_document` turns the Markdown the agent writes
  into the format a user actually asks for (Word, PDF, PowerPoint, etc.). With
  [`pandoc`](https://pandoc.org/installing.html) on PATH (a system binary, not a pip
  package) it handles every format at high fidelity. Without it, the built-in
  fallbacks still cover `md`, `txt`, `html`, and `docx` (the last via
  `python-docx`); any other target returns an "install pandoc" message.
- **Diagrams (Learning Room):** `render_diagram` produces PNGs **entirely
  server-side** — the browser never renders mermaid. It uses the hosted
  `mermaid.ink` API first (needs `requests`), then falls back to a fully local
  renderer for offline use (`pip install mermaid-cli && playwright install
  chromium`). If both are unavailable it degrades to a text outline.

## Documentation

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the system works, UML diagrams,
  and the reasoning behind every major technical decision.
- **[docs/SKILLS.md](docs/SKILLS.md)** — how skills (procedural memory) work and are created.
- **[docs/EXTENDING.md](docs/EXTENDING.md)** — create your own tools and skills.
- **[docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md)** — how the assistant extends
  and reconfigures itself at runtime.

## Testing

```bash
python -m pytest friday/tests/ -q       # full suite, offline/mocked, no API key
```

## Troubleshooting

- **`ModuleNotFoundError: anthropic`** → install your provider SDK
  (`pip install anthropic` / `openai` / `google-genai`).
- **Native window doesn't open** → pywebview missing or no display; use
  `python -m friday --server` and open the browser.
- **Provider/auth errors on first chat** → key missing/typo in `.env`, or
  `provider.type` doesn't match the key you set.

## License

[MIT](LICENSE).
