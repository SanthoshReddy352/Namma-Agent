# Namma Agent — Hermes Port & Feature Tracker

> **Source of truth** for the "make Namma Agent match/beat Hermes Agent" effort.
> All work is processed against this file. Update statuses here as phases land so
> we never lose the intended final outcome.
>
> **Reference:** Hermes Agent = [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) (MIT — porting with attribution is fine).
> Desktop app = Electron + React over a Python agent core.

## Status legend
- `[ ]` Not started
- `[~]` In progress
- `[x]` Done (verified)
- `[!]` Blocked / needs decision
- `[✗]` Declined (with reason)

## Guiding goals
- Seamless, cross-platform (Windows / macOS / Linux) installation for end users.
- Pull in **all interesting Hermes UI + backend features**; aim to exceed Hermes.
- Keep Namma's invariants: cloud-only brain, `assistant.name` configurable (never hard-coded), package stays `namma_agent`.

---

## Phase 0 — Token / TTFT accuracy  ✅
- [x] **Fix token over-counting** (reported 3.1M vs real ~108K). Root cause: `_accumulate_usage` summed `input_tokens` across every tool-loop step, re-counting the growing prefix; only the system prompt was cached.
  - [x] Capture full usage breakdown in all providers (`input / output / cache_read / cache_write`).
  - [x] Cache the conversation prefix on Anthropic (ephemeral breakpoint on last block) — real cost win.
  - [x] Headline = fresh input + cache writes + output; cache reads excluded & shown separately.
  - [x] Thread `cached` through server → `api.js` → `Message.jsx` footer tooltip.
- [x] **Fix TTFT** — stamp first model delta at provider boundary (not deferred replay / after media-filter buffering).
- [x] Tests: `test_cache_reads_excluded_from_headline_tokens` + full suite (392 passed, 4 skipped).
- Files: `core/providers/{base,anthropic_provider,openai_compat,google_provider}.py`, `core/agent.py`, `server/api.py`, `webui/src/api.js`, `webui/src/components/Message.jsx`, `tests/test_agent_loop.py`.

---

## Phase 1 — Comms channels (parity with Hermes)  ✅ COMPLETE
Hermes connects: Telegram, Discord, Slack, WhatsApp, Signal, CLI — one gateway process.
Namma now matches: outbound on all five + two-way (inbound) on Telegram, Signal, Slack, WhatsApp, and a local CLI gateway.

### Outbound channels
- [x] **Slack** (`comms/slack.py`) — incoming webhook (`NAMMA_SLACK_WEBHOOK_URL`).
- [x] **WhatsApp** (`comms/whatsapp.py`) — Cloud API (`NAMMA_WHATSAPP_TOKEN/PHONE_ID/TO`).
- [x] **Signal** (`comms/signal.py`) — signal-cli REST API (`NAMMA_SIGNAL_API_URL/NUMBER/RECIPIENT`).
- [x] Wired into `comms/manager.py` (single routing table), `comms/__init__.py`, `send_notification` tool.
- [x] Env vars in `.env.example` + `/api/settings` env_set + **Messaging** settings tab.
- [x] Stdlib-only (urllib); degrade gracefully when unconfigured.

### Inbound + gateway
- [x] **Platform-agnostic `InboundBridge`** (`comms/inbound.py`) — shared sessions, `/commands`, model picker, `!shell`, sudo askpass, turns. `TelegramInbound` refactored onto it (behavior preserved; all Telegram tests green).
- [x] **Signal inbound** via polling (`SignalInbound`, signal-cli REST `/v1/receive`) — two-way, no public URL.
- [x] **CLI gateway** — `python -m namma_agent --chat` (`comms/console.py`, `ConsoleInbound`), same agent/memory/tools/commands.
- [x] **Single gateway process** — `CommsManager.start_inbound` launches all available pollable bridges (Telegram + Signal) in the one service process; service activates on `any_available`.
- [x] **Slack + WhatsApp inbound** via FastAPI webhooks (`/webhooks/slack`, `/webhooks/whatsapp`) reusing the bridge — Slack signature verification + url_verification handshake; WhatsApp verify-token GET handshake. Fast ACK, turn runs on a background thread.
- [x] Tests: shared bridge logic (via console), Signal receive/route, Slack/WhatsApp parsers + verification, manager wiring, webhook routes — `tests/test_comms.py` (41 pass; full suite **412 pass, 4 skipped**). `--chat` smoke-tested.
- Note: Slack/WhatsApp inbound need the server publicly reachable (+ Slack signing secret / WhatsApp verify token); Telegram + Signal work fully local (polling).
- [x] **Gateway start/stop from the GUI** — Settings → Messaging now has a **Gateway** control (status + Start/Stop). Start rebuilds channels from the current env (so a token just saved takes effect with no app restart), then launches every available bridge; Stop tears them down (outbound notifications still work). Backend: `CommsManager.{running,status,reload}` + `stop()` now clears state so it can restart; `NammaAgentService.{comms_status,start_comms,stop_comms}`; API `GET /api/comms/status`, `POST /api/comms/{start,stop}`.
- Files: `comms/{_util,inbound,console,slack,whatsapp,signal,telegram,manager,__init__}.py`, `tools/comms.py`, `service.py`, `__main__.py`, `.env.example`, `server/api.py`, `webui/src/{components/Settings.jsx,api.js}`, `tests/test_comms.py`.

## Phase 2 — Skills system + UI tab  ✅ COMPLETE
> **2026-06-22 — Hermes-ported skills DELETED.** Per user request (suspected per-request
> prompt bloat / perf drop), the 60 Hermes-provenance skill folders (those whose
> `SKILL.md` carries an `author:` frontmatter field) were **removed from
> `namma_agent/skills/`**. A backup zip (`hermes_skills_backup_2026-06-22.zip`, repo root)
> was written first since `skills/` is untracked in git. Only the 19 original Namma skill
> folders remain (14 advertised, 5 left disabled as the user had them). The agent's
> system-prompt skill catalog dropped from ~69 → 14 lines. `skills.disabled` in
> `config.local.yaml` was pruned to the 5 still-existing originals the user had off.
> `ATTRIBUTION.md` + `HERMES-LICENSE` kept (conservative attribution). No code/UI/tool
> changes; Skills + Toolsets tabs untouched. Tools (Phase 3) left fully intact — none were
> actually ported from Hermes (all are Namma's own Phase 7 Wave tools).
Hermes: agentskills.io-compatible skills, self-improving; UI tab to activate/deactivate.
Namma now ships its 8 original skills **plus all 71 ported Hermes skills** (79 folders;
macOS-only ones platform-filtered off Windows). Decision: "port all, mark unsupported".
- [x] **Port all Hermes skills** (excluding God Mode — see Declined). All 71 `SKILL.md`
  folders copied verbatim (incl. reference assets/scripts) into `namma_agent/skills/`,
  flattened, with `category:` injected from the Hermes folder. Attribution +
  Hermes MIT LICENSE in `skills/ATTRIBUTION.md` + `skills/HERMES-LICENSE`.
- [x] **Skills tab** in web UI — grouped by category, search box, per-skill on/off
  switch, `yours`/`needs setup` badges, and a "Requires: …" line for skills with
  declared prerequisites (`Settings → Skills`).
- [x] Backend: enabled/disabled persisted to `config.local.yaml` (`skills.disabled`);
  the agent catalog only advertises **enabled + prerequisite-satisfied** skills, and
  `use_skill`/`render` refuse disabled ones. Hermes `prerequisites.{commands,env_vars}`
  drive a live `supported`/`missing` computation (CLI on PATH? env var set?).
- [x] API endpoints: `GET /api/skills` (list w/ enabled/supported/requires/category),
  `POST /api/skills/toggle` `{name, enabled}`.
- [x] Tests: prerequisites parsing, support detection, disabled excluded from agent
  catalog, unsupported excluded, toggle round-trip + persistence, `use_skill` refuses
  disabled, ported-catalog presence — `tests/test_skills.py` (17 pass, 1 skipped;
  full suite **422 pass, 4 skipped**).
- Files: `core/skills.py`, `core/builtins.py`, `service.py`, `server/api.py`,
  `webui/src/{api.js,components/Settings.jsx}`, `skills/**` (71 ported + ATTRIBUTION/LICENSE),
  `tests/test_skills.py`.

## Phase 3 — Toolsets tab + port all tools  ✅ COMPLETE
Hermes: ~14 toolsets (web, browser, terminal, file, code-exec, vision, image-gen, TTS, skills, memory, session-search, clarify, delegation, MoA, task-planning); UI to turn tools on/off.
Namma ships **~90 tools across ~28 toolsets** — every tool now carries a `category`
(toolset) and an enable/disable flag, toggled from a new Toolsets tab and honored
per turn.
- [x] **Toolsets tab** in web UI — tools grouped by toolset, search box, per-tool
  on/off switch, per-toolset "Enable/Disable all", `needs approval` badge for
  destructive tools (`Settings → Toolsets`).
- [x] Backend: every `Tool` has `category` + `enabled`; the registry's `definitions()`
  excludes disabled tools (so the model never sees them) and `execute()` refuses them.
  Tools are auto-grouped by the module they come from (`load_tools` uses
  `registry.categorize(<module>)`); builtins are grouped via `categorize("memory"/
  "learning"/"skills"/"agent"/"system"/"mcp")`. Disabled-set persisted to
  `config.local.yaml` (`tools.disabled`); takes effect next turn, survives restart.
- [x] API endpoints: `GET /api/tools` (now returns rich detail — name/description/
  category/enabled/destructive), `POST /api/tools/toggle` `{name, enabled}`,
  `POST /api/toolset/toggle` `{category, enabled}` (whole-toolset flip).
- [x] **Gap-analysis vs Hermes's 14 toolsets** — Namma already meets/exceeds 11/14
  and adds ~15 toolsets Hermes lacks (weather, news, smart_home, Gmail+Calendar,
  network, security, focus, goals, convert, apps, documents, comms, scheduler,
  system, self-doc). Mapping: web✓ browser✓ terminal(shell)✓ file(file_ops)✓
  code-exec(via run_shell)✓ vision✓ skills✓ memory✓ session-search(recall_sessions)✓
  delegation(delegate_task)✓ task-planning(tasks+goals)✓. TTS exists as a feature
  (browser Web Speech narration), not a callable tool. **Deferred (need new
  subsystems, not simple ports):** `image-gen` (requires an image API/provider —
  revisit in Phase 8 once an image provider lands), `MoA` (mixture-of-agents), and an
  explicit `clarify` tool (today the agent just asks inline in its reply).
- [x] Tests: categorization (default + `categorize` context + per-module grouping),
  disabled excluded from `definitions()`/`only`-scope, `execute` refuses disabled,
  set_enabled/set_category_enabled round-trips, stale-name pruning, detail shape,
  config persistence — `tests/test_toolsets.py` (14) + API toggle round-trips in
  `tests/test_server.py` (full suite **447 pass, 4 skipped**).
- Files: `core/tools.py`, `tools/__init__.py`, `service.py`, `server/api.py`,
  `webui/src/{api.js,components/Settings.jsx}`, `tests/{test_toolsets.py,test_server.py}`.

## Phase 4 — Chat transparency UI (tool calls + thinking)  ✅ COMPLETE
Extended the existing event timeline (didn't rebuild): tool steps + thinking now
render with friendly labels, persist under each reply, and survive reload.
- [x] **Tool-call UI** matching Hermes — friendly labels via `toolLabel(tool, args)`
  ("Searched the web — …", "Ran a command", "Read a file — …", "Captured a
  screenshot", …; unknown tools humanized) with running/ok/fail dots. Shared row
  renderer (`components/Activity.jsx` → `StepList`) used by both the live working
  panel (`Timeline.jsx`) and the persisted strip, so live and replayed look identical.
- [x] **Model thinking** surfaced inline — new provider `on_thinking` channel
  (`base.ThinkingCallback`) threaded through the chain + all four providers. Fires
  for reasoning models: openai_compat streams `reasoning_content`/`reasoning`
  (zero-config), Anthropic routes `thinking_delta` (stream refactored to split
  text/thinking blocks; extended-thinking left opt-in to avoid tool-loop block-replay
  issues), Gemini routes `part.thought`. Agent emits a `thinking` event (coalesced),
  shown as a collapsible "Thinking" section live and under the reply.
- [x] **Removed the trailing `· used: …` list** from the assistant footer
  (`Message.jsx`) — tool activity now lives only in the inline/collapsible Activity
  strip, never re-listed under the reply.
- [x] **Streaming look/feel** — live panel shows "thinking"/"working" with streamed
  reasoning; on turn end the steps pin under the reply as a compact, expandable
  "Thought it through · N steps" summary.
- [x] Backend plumbing: agent collects a structured `steps` timeline
  (`_record_step`, same reducer shape as the UI's `foldStep`), returns it on
  `AgentResult.steps`, and persists it in the assistant turn's `meta.steps`; server
  forwards `steps` on `turn_result`; `api.js` attaches them to the message live and
  restores them from `meta.steps` on `loadSession`.
- [x] Tests: `_record_step` (preamble/tool ok+fail/thinking-coalesce), steps
  collected + persisted to turn meta, thinking streams to event + steps, no steps on a
  plain chat, openai_compat `reasoning_content` → thinking channel — `tests/
  test_transparency.py` (7). All 18 mock providers updated for the new `on_thinking`
  kwarg. Full suite **454 pass, 4 skipped**; web UI build clean.
- Files: `core/providers/{base,registry,anthropic_provider,openai_compat,google_provider}.py`,
  `core/agent.py`, `server/api.py`, `webui/src/{api.js,components/{Activity.jsx,
  Timeline.jsx,Message.jsx}}`, `tests/test_transparency.py` (+ mock-provider sigs).

## Phase 5 — Interaction sounds  ✅ COMPLETE
Hermes plays clean sounds on interactions (message sent, response completed, etc.).
Completion-sound presets seen: Two-note comfort, Glass ping, Soft marimba, Tri-tone message, Airy whoosh, Discovery cluster, Systems online, IBM terminal, Modem chirp, Wind chimes.
- [✗→x] **Sound assets** — chose *not* to bundle Hermes's audio files (the tracker
  twice flags "verify asset license separately"; MIT covers code, not media).
  Instead every cue is **synthesised in the browser with the Web Audio API**
  (`webui/src/sounds.js`) — zero binary assets, nothing to license, identical on
  Windows/macOS/Linux, a few hundred bytes. All ten completion presets above are
  reproduced procedurally (oscillators + gain envelopes), plus distinct fixed cues
  for sent / approval / input / error.
- [x] **Wired to events** — `playSound(...)` fires from `webui/src/api.js`:
  `sent` on send, `complete` on `turn_result`, `approval` on `approval_request`,
  `input` on `password_request`, `error` on `error`. Honours a master switch +
  per-event toggle; `complete` plays the chosen completion preset.
- [x] **Preset picker + preview + per-event toggles** — new **Settings → Sounds**
  tab: master enable, volume slider, a grid of the 10 completion presets (click to
  set & hear, ▶ to preview without selecting), and per-event on/off toggles. Prefs
  are client-only (localStorage, like the theme) — no server round-trip; the
  AudioContext is created lazily on first gesture and `try/catch`-degrades where
  there's no audio device.
- [x] Verified in the live app (preview on an isolated port): Sounds tab renders all
  presets, selecting a preset persists + rings, master/volume/event toggles persist,
  no console errors, web build clean.
- Files: `webui/src/sounds.js` (new), `webui/src/api.js`, `webui/src/components/Settings.jsx`.

## Phase 6 — Settings redesign + Notifications  ✅ COMPLETE
- [x] **Removed the Voice tab.** Its single "Enable Piper voice" toggle (server-side
  Piper TTS / local STT) was relocated into **Behavior** rather than dropped, so no
  setting is lost.
- [x] **Settings redesigned, Hermes-style.** The flat tab list became a **grouped,
  icon + label** left nav with five labelled sections — General (Behavior, Persona,
  Appearance, Notifications), Intelligence (Providers, Models), Capabilities (Skills,
  Toolsets, Packs, Browser), Channels (Messaging), System (Memory, About). Each tab
  has a compact stroke icon; default landing tab is Behavior.
- [x] **Native desktop notifications — backend-delivered** (reworked after the web
  Notification API proved unreliable inside the pywebview/WebView2 desktop window;
  it doesn't surface toasts there, so notifications silently did nothing). Now the
  **server** shows the toast via the OS's own mechanism — `core/notifications.py`
  (`send_native_notification`): Windows = `NotifyIcon` balloon (routes to the Action
  Center), macOS = `osascript display notification`, Linux = `notify-send`. All
  stdlib/OS built-ins, spawned **detached + non-blocking**, never raises. Exposed at
  `POST /api/notify {title, body}`. The frontend (`notify.js`) keeps only the
  client-side prefs (master + per-event toggles, localStorage) and POSTs when an event
  fires — **no OS-permission dance, no focus gating** (a reply landing notifies you
  whether or not the window is focused). Wired from `api.js`: `response` on the viewed
  chat's `turn_result`, `background` on any other chat's, `approval`/`input`/`error`
  on their events. Title uses the configurable assistant name.
- [x] **Intermediate-action sounds** (user ask) — added a sixth sound cue, a very soft
  `tool` tick on every `tool_started`, so a multi-step turn feels alive. Sounds now
  cover sent → each tool step → reply ready, plus approval/input/error.
- [x] **Completion Sound selector + Preview** and **Send test notification** button —
  both live in the new **Notifications** panel (the Phase-5 standalone Sounds tab was
  folded in here). Panel rebuilt with **proper spacing** (user ask): titled `Block`s
  with breathing room + carded, divided `ToggleCard` rows. Two halves — Desktop
  notifications (master + 5 event toggles + test button that reports sent/failed) and
  Sounds (enable + volume row + 10-preset completion picker w/ ▶ preview + 6 per-event
  sound toggles).
- [x] **Settings redesigned, Hermes-style.** The flat tab list became a **grouped,
  icon + label** left nav with five labelled sections — General (Behavior, Persona,
  Appearance, Notifications), Intelligence (Providers, Models), Capabilities (Skills,
  Toolsets, Packs, Browser), Channels (Messaging), System (Memory, About).
- [x] Tests: `tests/test_notifications.py` — native dispatch per platform, never-raises
  on spawn failure, `/api/notify` route round-trip (3 tests). Full backend suite green
  bar one **pre-existing, unrelated** failure (`test_skills.py::test_ported_hermes_skills_present`
  — the user removed the Hermes-ported skills on 2026-06-22; see Phase 2 note).
- [x] Verified end-to-end in the live app (preview): `POST /api/notify` returns `{ok:true}`
  and pops a real Windows toast; grouped nav + redesigned Notifications panel render with
  the 4 carded sections; master + per-event toggles persist; the test button fires a real
  toast and reports "Sent — check your desktop"; Behavior carries the Piper toggle; no
  console errors; web build clean.
- Files: `core/notifications.py` (new), `server/api.py` (NotifyBody + `/api/notify`),
  `webui/src/notify.js` (rewritten → backend delivery), `webui/src/sounds.js` (+tool cue),
  `webui/src/api.js`, `webui/src/App.jsx`, `webui/src/components/Settings.jsx`,
  `tests/test_notifications.py` (new).

## Phase 7 — Installer / Desktop app (Hermes-style)  ✅ COMPLETE
End-user installs an executable → prompted → on Install, the flow runs (mirrors Hermes's 16-step installer).
Two delivery paths, both cross-platform: a **branded native installer** (PyInstaller-frozen React/pywebview
window, `installer/` + `installers/native/build.py`) and **plain bootstrap scripts** (`installers/install.{ps1,sh,bat}`).
- [x] Installer prompts user about the installation. — Welcome screen (`installer/webui` React flow:
  Welcome → Progress → Provider → Onboarding → Done) + a native folder picker (`choose_dir`, run
  out-of-process on Windows so it can't freeze the WebView2 UI thread).
- [x] Check prerequisites; install if missing:
  - [✗] **uv package manager** — *intentional deviation:* Namma bootstraps with the stdlib `venv` + `pip`
    (`--no-cache-dir`), no third-party package manager. Keeps the installer dependency-free; no uv to install/verify.
  - [x] Python 3.11 (verify) — `find_python()` accepts **3.10+**, auto-installs via winget/brew/apt/dnf/pacman/zypper.
  - [x] Git — `ensure_dependencies` (auto-install if missing).
  - [x] Detect Node.js — `dependency_status` checks `npm`; auto-install.
  - [x] **ripgrep + ffmpeg** — `OPTIONAL_TOOLS` + `ensure_optional_tools` (best-effort, never fatal; the
    app degrades gracefully without them). Wired into `install_dep_command` for every OS + both shell scripts.
- [x] Clone repository — `fetch_source` (git clone --depth 1, or copies the bundled source when frozen).
- [x] Create Python virtual environment — `create_venv`.
- [x] Install Python dependencies — `install_requirements` (venv pip, `--no-cache-dir`).
- [x] Install Node.js dependencies — `build_ui` (npm install/build; skipped if the UI is already bundled).
- [x] Build OS-specific desktop app — `installers/native/build.py` (PyInstaller → `.exe` / `.dmg` / `.AppImage`).
- [x] **Add agent to PATH** — installs a `namma` command (`namma`, `namma --chat`, `namma --server`).
  Windows: `<install>/bin/namma.cmd` (GUI detached when bare, console when args) + idempotent **User PATH** append;
  macOS/Linux: `~/.local/bin/namma` launcher (chmod +x). `add_to_path` + pure builders, in both shell scripts too.
- [x] Write configuration templates — `write_provider` / `write_onboarding` (→ `--configure`/`--onboard` CLI →
  `config.local.yaml` + `.env`); fails loudly (logged to `logs/installer-actions.log`).
- [x] Install messaging platform SDKs — N/A by design: all comms bridges are **stdlib-only** (urllib), so
  `requirements.txt` already covers them (see Phase 1) — nothing extra to install.
- [x] Mark install complete — `bootstrap` returns + `onInstallDone`; Done screen.
- [x] Configure the provider — Provider screen (`PROVIDERS` presets mirror `setup_wizard.PROVIDER_PRESETS`).
- [x] Configure the model from the configured provider — model carried per-provider in the Provider screen.
- [x] Start the agent — `launch` (detached, windowless) + `verify_launch` (boots `--server`, polls `/api/health`
  so the Done screen confirms the backend really starts).
- [x] **Cross-platform**: Windows / macOS / Linux — every step guards `os.name`/`platform.system()`; native
  build emits per-OS artifacts; CI in `.github/workflows/release.yml`.
- [x] **Uninstaller** — `installers/uninstall.{ps1,sh}` + `core/uninstaller.py` (in-app Danger-zone button).
  Re-execs from TEMP/`/tmp` to delete its own install dir, stops the running app by command-line match,
  `keep-data` backs up chats/config first, removes shortcuts + the Add/Remove-Programs regkey **+ the
  `namma` PATH entry / launcher** added above. Windows registers in Add/Remove Programs (`register_windows_app`).
- [x] Tests: optional-tool install commands + `_tool_command` (ripgrep→rg) + `ensure_optional_tools` never-raises,
  `namma` launcher builders (cmd/ps1 PATH-append/posix script), `path` step present, uninstaller PATH teardown —
  `tests/test_installer.py` (**25 pass**; full suite 463 pass, 4 skipped, + the 1 pre-existing unrelated
  `test_ported_hermes_skills_present` failure from the Phase-2 skill removal).
- Files: `installer/core.py`, `installer/app.py`, `installers/{install.ps1,install.sh,uninstall.ps1,uninstall.sh}`,
  `installers/native/build.py`, `namma_agent/core/{uninstaller.py,setup_wizard.py}`, `tests/test_installer.py`.

## Phase 8 — "Better than Hermes" extras
- [ ] Gap-analysis pass: catalog Hermes UI/backend features not yet captured above; pull the worthwhile ones in.
- [ ] Identify Namma-only improvements that push past Hermes.

---

## Declined
- [✗] **God Mode skill** — Hermes's GODMODE is an auto-jailbreak skill whose explicit purpose is to defeat a model's safety filters and "lock it jailbroken." Will not build or port. Everything else on the list stands.

## Open notes
- Shell defaults to the **Hermes venv** (`AppData\Local\hermes\hermes-agent\venv`); use Namma's `.venv\Scripts\python.exe` for this project. Consider fixing PATH.
- Verify asset licenses (sounds/icons) separately — MIT covers code, not necessarily bundled media.
