# Running & Testing FRIDAY v2 (cloud version)

This is the practical "I just want to run it" guide for the new cloud-only
`friday/` app. It assumes nothing is installed yet.

> The legacy root `requirements.txt` / `.env.example` are for the **old** local
> (PyQt + llama.cpp) build. For the cloud version use **`friday/requirements.txt`**
> and **`friday/.env.example`** described below.

---

## 1. Create a virtualenv & install

From the project root (`Friday_Linux-Web/`):

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r friday/requirements.txt
```

Don't need voice or the desktop window? Install just the core + your provider:

```bash
pip install fastapi "uvicorn[standard]" pydantic PyYAML anthropic
```

## 2. Add your API key

```bash
cp friday/.env.example .env          # .env is read from the project root
```

Edit `.env` and set the key for the provider you'll use, e.g.:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The default provider is Anthropic (`claude-sonnet-4-6`). To use something else,
edit `friday/config.yaml` → `provider.type` (`openai`, `google`, `ollama`,
`lmstudio`, `openai_compat`). **Local Ollama/LM Studio need no key.**

> No key at all? Point `provider.type: ollama` at a running Ollama and pull a
> model — fully offline, still cloud-style API.

## 3. Run it

```bash
python -m friday              # opens a native desktop window (pywebview)
python -m friday --server     # backend only — then open http://127.0.0.1:8000
```

`--server` is the most reliable first run (no GUI dependency). You should see the
chat UI at **http://127.0.0.1:8000**.

## 4. Smoke-test without the GUI

With the server running (`python -m friday --server` in another terminal):

```bash
curl http://127.0.0.1:8000/api/health      # -> {"ok": true}
curl http://127.0.0.1:8000/api/tools       # -> the full tool list (40 tools)
```

A full chat turn goes over the WebSocket at `/ws` (the GUI uses it). Quick check
of one turn from Python:

```bash
python - <<'PY'
from fastapi.testclient import TestClient
from friday.config import load_config
from friday.service import FridayService
from friday.server.api import create_app
svc = FridayService(config=load_config())          # uses your real provider+key
c = TestClient(create_app(svc))
with c.websocket_connect("/ws") as ws:
    ws.send_json({"type": "user_input", "text": "what's the weather in Mumbai?"})
    while True:
        msg = ws.receive_json()
        print("event:", msg.get("type"))
        if msg.get("type") == "turn_result":
            print("FINAL:", msg.get("content")); break
PY
```

## 5. Run the test suite (no API key needed)

```bash
python -m pytest friday/tests/ -q       # 116 tests, all offline/mocked
```

Per-wave tool tests:

```bash
python -m pytest friday/tests/test_tools_wave1.py   # file/shell/system/apps
python -m pytest friday/tests/test_tools_wave2.py   # web/browser/network/security
python -m pytest friday/tests/test_tools_wave3.py   # weather/smart_home/news/vision/docs/scheduler
python -m pytest friday/tests/test_tools_wave4.py   # memory/delegate_task/persona
```

---

## What works today (40 tools)

| Area | Tools |
|------|-------|
| Files | `read_file` `write_file` `list_dir` |
| Shell/System | `run_shell` `system_info` `open_app` |
| Web | `web_search` `web_extract` `web_crawl` |
| Browser | `open_browser_url` `search_google` `play_youtube` `play_youtube_music` |
| Network | `ping_host` `dns_lookup` `check_port` `public_ip` |
| Security* | `port_scan` `ping_sweep` `dir_enum` `dns_enum` |
| Weather/News | `get_weather` `get_news` |
| Smart home† | `ha_turn_on` `ha_turn_off` `ha_get_state` `ha_set_temperature` |
| Vision | `take_screenshot` `read_text_from_image` |
| Documents | `read_document` |
| Scheduler | `add_reminder` `list_reminders` `remove_reminder` |
| Memory | `remember_fact` `recall_facts` `forget_fact` `search_conversations` |
| Agent | `delegate_task` (research/sub-tasks) `switch_persona` `list_personas` |

\* off until `security.lab_mode: true` + `authorized_scopes` in config.yaml.
† off until `smart_home.url` + `HASS_TOKEN` are set.

## Optional system tools (only if you use that feature)

- **Voice TTS:** the `piper` binary + a `.onnx` voice model on PATH.
- **Vision:** `grim`/`scrot`/`gnome-screenshot` (capture), `tesseract` (OCR).
- **Security:** `nmap`, `gobuster`, `dig`.

All of these degrade gracefully — the tool returns a clear "install X" error
instead of crashing.

## Troubleshooting

- **`ModuleNotFoundError: anthropic`** → you installed core but not your provider
  SDK. `pip install anthropic` (or openai / google-genai).
- **Native window doesn't open** → pywebview isn't installed or no display; use
  `python -m friday --server` and open the browser.
- **Provider/auth errors on first chat** → key missing/typo in `.env`, or
  `provider.type` doesn't match the key you set.
