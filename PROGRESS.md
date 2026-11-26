# Namma Agent — PROGRESS

> **The single source of truth** for implementation status, roadmap, known issues,
> and technical decisions. It replaced `Namma_Agent_Port.md` (Hermes parity) and
> `STAND_OUT.md` (stand-out plan) on 2026-11-25. Both live on in git history.
>
> **Last updated:** 2026-11-25 · **Version:** 2.3.2 · **Tests:** see §1

## How to use this file (rules)

1. **Read it first** at the start of every development session.
2. **Verified work only.** `[x]` means implemented, tested, and verified. Creating a
   plan, writing a stub, or "should work" is not done. Never mark incomplete work done.
3. **Update it in the same change as the code.** Every item that lands records its
   files, its tests, and the full-suite count after the change.
4. **Record blockers explicitly** as `[!]` with what is needed to unblock.
5. **Every change gets a dated line** in the [Change log](#10-change-log).
6. **Decisions go in the [Decision log](#6-decision-log)** with a one-line reason.
7. Product invariants (inherited, non-negotiable):
   - Cloud-only brain. The assistant's name comes from `assistant.name` and is never
     hard-coded. The package stays `namma_agent`. `NAMMA_*` env-var names are stable.
   - Every feature ships with offline/mocked tests **and** a visible UI surface.
   - Prefer the stdlib; every new dependency needs a written reason.
   - Windows is a first-class target, not a port.

**Legend:** `[ ]` not started · `[~]` in progress · `[x]` done (verified) ·
`[!]` blocked / needs decision · `[✗]` declined (with reason)

---

## 1. Current state

| | |
|---|---|
| Version | 2.3.2 (`namma_agent/version.py`) |
| Test suite | **1,437 passed, 3 skipped** (2026-11-26, Phase 9 W1 slice 4; 1,424 after slice 1; 1,420 after Phase 5/6; 1,312 after Phase 3) |
| Web UI tests | **51 passed** — `cd namma_agent/webui && npm test` (Vitest + React Testing Library; 38 after W1 slice 3; 34 after slice 2; 29 after slice 1) |
| Run | `python -m namma_agent --server` → http://127.0.0.1:8000 (desktop: `python -m namma_agent`) |
| Test | `.venv/Scripts/python.exe -m pytest namma_agent/tests -q` (no API key needed) |
| Lint | `.venv/Scripts/python.exe -m ruff check namma_agent` |
| Graph | `graphify update .` → `graphify-out/` (gitignored; regenerate locally) |

### Architecture map (graphify, 2026-11-25)

5,389 nodes · 11,772 edges · 225 communities · no import cycles.

- **Hubs (most connected):** `ToolRegistry` (278 edges), `Database` (239),
  `LLMResponse` (205), `NammaAgentService` (165), `ToolResult` (153), `Provider` (109),
  `create_app()` (102), `EngramStore` (82), `Agent` (71).
- **Cross-community bridges:** `NammaAgentService`, `ToolRegistry` and `Database` have
  the highest betweenness. Almost every subsystem reaches every other through them.
- **Oversized modules (refactor targets):**

  | File | Lines | Problem |
  |---|---|---|
  | `namma_agent/service.py` | ~2,270 | Wiring plus dozens of feature methods (103 internal edges) |
  | `namma_agent/server/api.py` | ~1,760 | 125 routes in one `create_app` |
  | `namma_agent/core/builtins.py` | ~1,560 | Memory, project, learning and delegation tools together |
  | `namma_agent/core/agent.py` | ~1,420 | `process_turn` alone is ~430 lines |
  | `webui/src/components/Settings.jsx` | 2,909 | One 160 KB modal with 21 tabs |

- **Front end:** React 18 + Tailwind 3 + Vite 6, react-router with 6 routes,
  react-markdown + KaTeX + highlight.js. No TypeScript, no lint, no tests. The bundle is
  one 1.13 MB JS chunk.
- **Desktop shell:** pywebview (WebView2 on Windows) + uvicorn thread + pystray tray.

---

## 2. Audit findings (2026-11-25)

Sources:
- three code audits (backend, UI, docs), each with file:line evidence
- the graphify graph
- `Desktop/Namma-Agent-Insights` (16 Nov), `Desktop/hermes-desktop-replication-kit`,
  `Desktop/AGI_HERMES_COMPETITIVE_PRODUCT_REPORT.md`
- the owner's wishlist (`Downloads/Namma Agent.md`)
- four web research tracks: inline artifacts, provider tool limits, pywebview vs
  Tauri, and token-efficiency harnesses

Bugs are tracked in [§5](#5-known-issues--bugs). The gaps below feed the roadmap.

### Architecture & implementation gaps
- **Delegation is a helper, not a runtime.**
  - `delegate_task(task, toolsets)` has no `context`, no fan-out, no depth or
    concurrency cap, and no streaming of child events (they go to a no-op emitter).
  - `background_task` runs on unbounded threads and never reports back into the chat.
- **Self-awareness:**
  - `self_knowledge.md` is stale: it says "FRIDAY", lists non-existent tools, and
    names the wrong default model. It is only returned by `about_namma`, never
    injected into the prompt.
  - The model is not told its install, source or config paths.
  - Writes under `/opt` and Program Files are blocked, which blocks
    self-modification on OCI.
  - Paths containing `..` are rejected.
  - There is no config-editing tool.
  - All of this is why "what's my MCP config?" turned into a filesystem crawl.
- **Token efficiency:**
  - About 113 tool schemas (~10–11K tokens) go out on every model call.
  - The system prompt is ~12–15K chars and contains a minute-resolution date near the
    top, which busts prompt caching every turn. Only Anthropic sets `cache_control`.
  - Token accounting ignores background model calls (compaction, Engram writer,
    titles, the watcher gate). There is no per-turn token budget.
- **Event protocol:** ~17 WebSocket event types with no sequence numbers and no
  replay. A reconnect mid-turn loses the in-flight reply.
- **Chat:**
  - No regenerate, edit, branch or delete.
  - Switching model in a plain chat starts a new session; only Projects and Learning
    carry a recap.
  - Tool calls run one after another.
- **MCP:**
  - Servers connect synchronously inside `NammaAgentService.__init__` (60 s timeout
    each).
  - No discovery (local or Docker), no setup help, no schema validation.
- **Config:**
  - UI edits go to the `config.local.yaml` overlay; the owner wants the real
    `config.yaml`/`.env`.
  - Keys go to plain `.env` although a secrets vault exists.
  - In Docker, the overlay and `.env` live in the image layer, not the data volume.
  - Profile providers ignore `provider.fallback`.
- **Always-registered lab tools:** security and smart-home tools are shown to the
  model even with `lab_mode: false` or no Home Assistant configured.
- **Dead code:**
  - Cognee leftovers: `agent.py` `mcp_cognee_recall` steering, the `builtins.py`
    Cognee branches, the `"cognee"` scope in `service.py`, and UI references.
  - `conversation.memory_nudge_every` (unread), `safety.is_destructive` (unused;
    gating is the `destructive=True` flag), the `Persona.system_prompt(facts, nudge)`
    parameters, and the unused `on_token` in the WebSocket handler.

### UI/UX findings
- **Tokens:**
  - Dark mode is a parallel `night-*` palette, producing 749 `dark:` duplicates; any
    missed pair leaks (error bubble, caret, auth gate).
  - 428 arbitrary font sizes in 12 values (10–17px), 7 radius sizes, 70 hex literals,
    174 raw Tailwind palette colours.
  - Inter and JetBrains Mono are declared but never loaded.
  - The theme doesn't follow the OS.
- **Components:** no shared primitives. Four hand-built modals, 95 inline SVGs with
  duplicates, two Copy buttons.
- **Accessibility:**
  - 1 `aria-label` across 183 buttons; 0 `focus-visible` styles; 30 `outline-none`.
  - No dialog roles, focus trap or consistent Escape; the confirm dialog autofocuses
    the destructive button.
  - No reduced-motion support.
  - Targets of 20–28px; `--ink-faint` on `--paper` is about 2.4:1 contrast.
- **Performance:** every token re-renders and re-parses every message (KaTeX and
  highlight included), with no memoisation and no virtualisation.
- **Information architecture:**
  - 6 routes, with everything else in the Settings modal (no deep links, no search,
    mixed save models).
  - No command palette or shortcuts.
  - No onboarding in the web UI (`/api/onboarding` is never called), no starter
    prompts, and raw error strings.
- **Desktop shell:**
  - Hard-coded light background, so the window flashes for dark users.
  - No window-state persistence, native menu, global hotkey or splash.
  - Closing the window quits the agent.
  - The default WebView context menu is on and all text is selectable.
  - The error page has no logs.
- **Chat rendering:** mermaid is never rendered, so a model-written ```` ```mermaid ````
  block shows as raw code. This is the owner's "Teach me agentic AI with diagrams"
  report.

### Owner wishlist (`Namma Agent.md`) → roadmap

| Wishlist item | Phase |
|---|---|
| Token efficiency, toolset one-click groups, self-awareness and own-file access | 2 |
| No local config overlay (edits go to the real config/.env) | 2 |
| Task delegation that actually spawns, with scoped tools and skills | 3 |
| Chat composition (inline visuals, mermaid, placement control) | 4 |
| MCP: tool limits, rules, discovery (local and Docker), setup help, plugin market | 5 (128-tool crash: stopgap fixed in Phase 1) |
| Setup mode and API-key setup marketplace | 5 |
| Settings, notifications, design rework (UI Playbook) | 6 |
| Native desktop feel, installer and uninstall registration | 7 |
| Multi-device access keys and sync | 8 (design first) |
| Tauri rewrite | Declined for now; see the decision log |

---

## 3. Roadmap

Priority order: critical bugs → architecture → stability → startup and memory → core
functionality → UI/UX → code quality → packaging. Each phase lists acceptance
criteria; a phase is `[x]` only when all of them are verified.

### Phase 0 — Repository cleanup & tracker — `[x]` 2026-11-25
- [x] `PROGRESS.md` created; `Namma_Agent_Port.md` and `STAND_OUT.md` migrated and removed.
- [x] Removed academic, hackathon and presentation material:
  - `SUBMISSION.md`, `DEMO_SCRIPT.md`, `RECORDING_GUIDE*.md` (3), `LAUNCH_POSTS.md`,
    `Cognee_Implementation.md`, `Cognee_Track_Plan.md`
  - `make_research_docx.py`, `make_slide_docx.py`, `docxbuild/`
- [x] Removed obsolete Cognee setup: `docker-compose.cognee.yml`, `.env.cognee.example`,
  `scripts/setup_cognee.{ps1,sh}`, `scripts/seed_demo_memory.py`, `docs/COGNEE.md`, the
  landing `cognee-mcp` diagram, and the landing Cognee docs and marketing (rewritten
  to describe Engram).
- [x] Removed unrelated docs: `docs/MCP_vs_Function_Calling.md`, `docs/hospital_data.json`.
- [x] `AGENTS.md` reduced to a pointer at `CLAUDE.md` + `PROGRESS.md`; it had been a
  duplicate of CLAUDE.md.
- [x] References repaired: `mkdocs.yml`, `docs/{MEMORY_SYSTEM_DESIGN,PLUGINS,ARCHITECTURE}.md`,
  `namma_agent/skills/ATTRIBUTION.md`, `installers/native/README.md` (it said
  "Tkinter"; the installer is React + pywebview).
- [x] Privacy:
  - `data/checkpoints/` (71 tracked files of personal file snapshots) is now
    untracked and gitignored; the local files are kept.
  - The two historical commits of `config.local.yaml` were checked and hold only
    `api_key_env` *names*, no key values, so no rotation or history rewrite is needed.
- [x] Kept deliberately: `scripts/migrate_cognee_to_engram.py` (legacy one-shot
  importer; a test and two docs use it).
- [ ] Re-render `landing/public/assets/diagrams/architecture-overview.png`: its
  `.mmd` source still draws a Cognee box (needs `mmdc`).

### Phase 1 — Critical correctness & security fixes — `[x]` 2026-11-25
All items have regression tests; see [§5](#5-known-issues--bugs) for the bug ids.
- [x] 1.1 Auto mode never overrides an explicit always-decline policy (BUG-01).
- [x] 1.2 Remote-channel turns get a trust-based approval policy instead of
  `approval=None` (BUG-02).
- [x] 1.3 Delegation restores the parent session and cancel check, hands the parent's
  Stop to the child, caps child steps at 25 when the parent is unlimited, and rejects
  unknown toolsets with the list of valid ones (BUG-03).
- [x] 1.4 At most 128 tools per request, keeping native tools and dropping MCP tools
  first; MCP tool names are OpenAI-safe (≤64 chars, unique) (BUG-04).
- [x] 1.5 Safe defaults:
  - `tool_result_max_chars: 24000`, with the overflow spilled to
    `<data>/tool_outputs/` and the path given to the model
  - `tool_loop_limit: 40`
  - `read_file` pages with `offset`/`max_chars`
  - `find_files` skips `.venv`, `node_modules`, `.git`, `dist`, … (BUG-05)
- [x] 1.6 `.env` writes reject line breaks and NUL and invalid key names (400 from
  `/api/settings`); `/api/upload` streams to disk with a cap (`server.max_upload_mb`,
  default 50) and never overwrites a file (BUG-07, BUG-09).
- [x] 1.7 `apply_config` re-applies the agent's loop and context knobs live; the six
  config setters update the shared dict in place (BUG-07).
- [x] 1.8 Single instance: a second launch checks for a running backend before
  building the service, then focuses the existing window (`POST /api/desktop/focus`)
  or attaches a window to a headless backend (BUG-08).
- [x] 1.10 Stop really stops (BUG-19, owner report):
  - model calls abort within ~0.2 s and tokens stop on click
  - the remaining tools in a batch are skipped
  - running shell commands are killed and approval waits release
  - same-chat turns are serialized on the server
- [x] 1.9 Mermaid stopgap: the persona tells the model to use `render_diagram` and not
  to paste raw ```` ```mermaid ```` blocks (BUG-06). The real fix is Phase 4.
- **Tests added:** `test_approval_policy.py` (9), `test_tool_limits.py` (9),
  `test_settings_hardening.py` (13), `test_single_instance.py` (4), `test_stop_turn.py` (6),
  plus 5 delegation cases in `test_tools_wave4.py`.
- **Not done here:** a UI notice for `tools_trimmed`. The event is emitted, but the web
  UI ignores it until Phase 4/6.

### Phase 2 — Token-efficiency harness, self-awareness, config truth — `[~]`
Landed 2026-11-25 except the items marked `[ ]` / `[!]` below.

- [x] **Usage log and turn budget.**
  - Every model call is one row in the new `usage_log` table: input, output, cache
    read and cache write tokens, plus kind, step, session, provider and model.
  - Background calls are counted too. Each is tagged with a kind: `compaction`,
    `memory` (Engram), `title`, `summary`, `watcher`, `skill_capture`,
    `self_review` or `delegate` (sub-agents).
  - How it works: `Provider.__init_subclass__` wraps every concrete `generate`.
    `usage_scope()` and `labeled()` attribute the calls. Chains don't double-count,
    and attribution follows the generate worker thread.
  - Per-turn budget: `conversation.turn_token_budget` (0 = off). The loop stops
    before the next tool round once the budget is spent, says so, and emits
    `turn_budget_exceeded`.
  - UI: Settings → Status shows "Every model call (last 7 days)" by kind, with the
    cache-read ratio. Settings → Behavior has the budget field. There is a new
    `/api/usage/requests` endpoint. Files: `core/usage.py` (new),
    `core/providers/base.py`, `core/memory.py`, `core/agent.py`, `service.py`.
  - Tests: `test_usage_log.py` (15).
- [x] **Tool search.**
  - Past `tools.search.threshold` (default 40), only ~15 core tools plus
    `tool_search` / `tool_describe` / `tool_call` are sent.
  - `tool_search` returns the best matches *with their schemas*.
  - `tool_call` is unwrapped in the agent loop, so the inner tool goes through the
    normal approval gate, checkpoint, audit log, media and verification path. It
    is refused when the tool is outside the turn's scope, so untrusted senders
    still can't reach destructive tools.
  - The deferred tools are listed by toolset in the system prompt.
  - The sent tool list depends only on config and scope, so it is identical on
    every request. The 128-tool cap stays as a backstop when search is off.
  - Measured offline on the real registry: 94 tools / ~9.8K schema tokens → 18
    tools / ~2.9K tokens per request. The system prompt grows by ~450 tokens for
    the index.
  - Files: `core/tool_search.py` (new), `core/agent.py`. Tests:
    `test_tool_search.py` (18), `test_tool_limits.py` (+1).
- [ ] Anthropic native `defer_loading` + `tool_search_tool_bm25`: not done. Our own
  meta-tools work on every provider. The native beta can't be verified offline and
  is a follow-up.
- [x] **Toolset profiles and gated tools.**
  - `tools.profile`: general / productivity / code / research / minimal. Set it in
    Settings → Toolsets (`/api/tools/profile`), together with the tool-search mode
    (`/api/tools/search`). Both apply live. A model's `tools_allow` and the global
    `tools.allow` still win over the profile.
  - Lab (security) and Home Assistant tools have a `requires` check. They stay
    registered and are listed as "hidden — needs …" in the Toolsets tab, but they
    are never sent to the model until `security.lab_mode` / `smart_home` is set up.
    The check runs every turn, so enabling them in config shows them on the next turn.
  - Not done: a profile switcher in the composer (Settings only for now).
- [x] **Cache-stable prompt.**
  - The minute-stamped date is gone from the system prompt. A static date policy
    stays there.
  - The day-resolution date (`Today: …`) and Engram's per-turn memory prefetch now
    ride a `<context>` block on the newest user message. The stored transcript
    keeps the raw text.
  - The system prompt and tool list are byte-identical across turns (tested).
  - OpenAI: a per-chat `prompt_cache_key`, sent to api.openai.com only and dropped
    if an endpoint rejects it.
  - Files: `core/persona.py`, `core/agent.py`, `core/providers/openai_compat.py`.
- [x] **Two-phase in-turn compaction.**
  - Before each model call, if the estimated prompt is over
    `conversation.context_fraction` (default 0.6) of the model's context window:
    first clear old tool outputs (newest 4 kept), then fold earlier history into a
    fixed-section summary in the system prompt.
  - Each step emits a `context_compacted` event and is logged as `compaction`.
  - Windows are guessed from the model id; a model profile can set
    `context_window:`.
  - Files: `core/context_budget.py` (new). Tests: `test_context_budget.py` (8).
- [x] **Self-knowledge.**
  - `self_knowledge.md` is rewritten (no "FRIDAY", accurate claims).
  - `about_namma` now returns a live reference: paths, version, configured
    models/providers, MCP servers with env-var *names* only, and enabled toolsets.
  - A short static "ABOUT YOU" block (install/source/config/data paths, where MCP
    lives, "call `about_namma` first") is in every system prompt.
  - Writes into the app's own install/data dir are allowed even under `/opt` or
    Program Files; write tools stay approval-gated.
  - `..` paths are accepted, and the policy checks the resolved path (tested: `..`
    can't reach a secret dir or a protected tree).
  - Files: `core/self_knowledge.py` (new), `tools/selfdoc.py`, `core/safety.py`.
    Tests: `test_self_knowledge_config.py`, `test_tools_wave1.py`.
- [x] **Config truth.**
  - [x] Secrets edited in Settings go to the vault. Their stale `.env` copy is
    removed so it can't shadow the vault at the next boot. Non-secret values (and
    any secret the vault refuses) still go to `.env`. Clearing a key removes it
    from both (`core/secrets.save_settings_env`).
  - [x] **One user config in the data dir** (owner decision, 2026-11-25).
    - Settings, the setup wizard and `namma config set` now write
      `data/user_config.yaml` (`$NAMMA_DATA_DIR/user_config.yaml` when that is
      set; `$NAMMA_USER_CONFIG` overrides the path). It is merged over the
      documented base `config.yaml`, which is never rewritten. No new dependency.
    - One-shot migration on first load: the legacy `config.local.yaml` (from the
      state dir first, then beside the base) is copied in and renamed
      `config.local.yaml.migrated`. A legacy file that reappears later is ignored.
    - Docker: the image's bundled server-lite profile seeds the volume's user
      config on first boot, so UI edits survive an image rebuild (BUG-11).
      `deploy/install.sh` writes the server-lite profile to
      `data/user_config.yaml`. `.env` follows `$NAMMA_DATA_DIR` too
      (`NAMMA_ENV_FILE` overrides it).
    - A base config passed explicitly (tests, portable tools) keeps a sibling
      `config.local.yaml`. A new `tests/conftest.py` points every test at a
      throwaway user config, so the suite can't read, write or migrate real
      settings (checked: the owner's `config.local.yaml` was untouched after a
      full run).
    - Updated `.gitignore`, the comments in `config.yaml`, `self_knowledge.md`,
      README, `docs/{ARCHITECTURE,DEPLOY,DEPLOY_VPS,INSTALL,PLUGINS,SELF_MODIFICATION}.md`,
      CLAUDE.md, Dockerfile, `deploy/`, and the comments and docstrings in code.
    - Tests: 6 in `test_self_knowledge_config.py` (writes, migration, Docker seed,
      explicit-path isolation, env override, about block). Two Engram settings
      tests now read the user config.
    - Not yet run against the real install: the migration of the owner's
      `config.local.yaml` happens on the next app launch.
- [x] **Dead code removed.**
  - Cognee: the `mcp_cognee_recall` steering, the recall/forget plugin fallbacks,
    the `"cognee"` clear scope, and the UI labels.
  - Also: `conversation.memory_nudge_every` (replaced in the UI by the token
    budget), `safety.is_destructive`, and the `Persona.system_prompt(facts, nudge)`
    parameters.
  - Not done: the unused `on_token` in the WebSocket handler.
- [x] Model profiles honour `provider.fallback`. They are wrapped in a
  `ProviderChain`, skipping a fallback identical to the profile. The chain's
  timeout covers every link.
- **Acceptance (needs live runs, not yet verified):**
  - "What's your MCP config?" under 30K tokens: the path now exists (about block →
    `about_namma`) but hasn't been measured against a real model.
  - Cache-read ratio ≥60% on multi-step turns: now visible in Settings → Status;
    not yet measured live.
  - The GitHub MCP server works on gpt-5 and Claude without manual disabling:
    covered by tool search plus the cap, but not run live.

### Phase 3 — Delegation runtime (Hermes-style contract) — `[x]` 2026-11-25
All acceptance criteria verified: offline tests, the UI, and a live eval on a
real model (100% on gpt-4.1-mini).

- [x] **`delegate_task` v2** (`core/delegation.py`, new; `core/builtins.py`).
  - Inputs: `goal` (alias `task`), `context`, `tasks[]` for fan-out (strings or
    `{goal, context, toolsets, skills, name}`; a task's context adds to the
    shared one), `role` (`leaf` / `orchestrator`), `toolsets`, `skills` (their
    SKILL.md body is injected) and `budget` (`max_steps`, `max_tokens`).
  - Output per child: `{status, summary, exit_reason, truncated}`.
    - `status`: completed / partial / failed / cancelled, or interrupted after a
      restart.
    - `exit_reason`: completed / step_limit / token_budget / cancelled / error.
    - `truncated`: the summary was clipped at `delegation.summary_chars` or the
      child stopped early.
    - `AgentResult` now carries `exit_reason`.
  - Limits:
    - At most `delegation.concurrency` (default 3) children of one call run at
      once; the rest wait their turn.
    - At most 8 tasks per call.
    - Depth cap: a leaf child (depth 1) can't delegate. An orchestrator child
      gets `delegate_task` once, and its children (depth 2) are always leaves.
  - Cancellation tree: each run has its own flag and also checks its parent's
    Stop. Cancelling a run cancels its whole subtree; the turn's Stop reaches
    every child.
  - The child's persona (`SubagentPersona`) lists only the child's own tools,
    plus orchestrator instructions and the selected skills, not the main
    assistant's preamble.
  - Child tools are never destructive, never unavailable (`requires`), never the
    background tools.
- [x] **`DelegationManager`**
  - Runs are persisted in a new `subagent_runs` table. Runs left
    queued/running by a dead process are marked interrupted at boot. The legacy
    JSON background store is imported once.
  - Every state change publishes a `subagent` event through a new process-wide
    `Broadcaster` (`core/events.py`). Each WebSocket subscribes on connect, so
    runs that outlive their turn still reach the UI.
  - API: `/api/runs`, `/api/runs/{id}`, `POST /api/runs/{id}/cancel`.
- [x] **`background_task`**
  - Runs on a bounded pool (`delegation.background_workers`, default 2); extra
    tasks queue.
  - On completion the report is posted into the chat it came from (saved to
    history and pushed live) and sent over the messaging channel.
  - New `cancel_background_task`. `check_background_task` shows the status and
    the current step.
- [x] Delegation and background tasks are refused for untrusted senders.
- [x] **UI.** A Sub-agents panel above the message bar (`RunsPanel.jsx`) shows
  each run's status, role, live tool and steps, with Cancel. The Activity
  timeline has labels for the new tools.
- [x] **Delegation eval harness.**
  - `core/delegation_eval.py` and `scripts/delegation_eval.py`: 20 tasks over a
    seeded workspace (lookups, multi-step file work, context-only, fan-out,
    orchestrator split, budget), run through the real runtime and file tools.
  - `--mock` (oracle brain) passes 20/20, which proves the harness only.
  - The harness found a real gap: a standalone manager gave orchestrators no
    `delegate_task`. Fixed: the manager now supplies its own.
- **Tests:** `test_delegation.py` (21, including the hard token cap). `test_background_tasks.py` was updated
  for the runs table and the new statuses, plus the legacy-import test. All
  existing delegation regressions in `test_tools_wave4.py` pass unchanged.
- **Verified live** with a throwaway server and a scripted brain (no tokens,
  scratch data and user config):
  - three parallel children appeared in the panel
  - Cancel on one ended it within about a second while the other two kept
    running
  - the turn's Stop cancelled the rest
  - this caught and fixed a stale "running web_search" label: `tool_finished`
    now publishes
- **Acceptance:**
  - [x] 3 parallel children are visible and cancellable (verified in the UI).
  - [x] The delegation eval reaches ≥85% on a real model: **20/20 (100%)** on
    OpenAI `gpt-4.1-mini-2025-04-14`, 2026-11-25.
    - 36,275 tokens in 50 calls, inside the owner's data-sharing allowance
      (Build tier, 2.5M/day for that model group). The runner has a hard
      `--max-tokens` cap (`CappedProvider`, set to 1M); it counts every billed
      token and reserves room for calls already in flight.
    - Confirmed from the log that the orchestrator task really called
      `delegate_task`, and that the children grounded their answers in real
      tool calls (29 `read_file`, 2 `find_files`, 1 `list_dir`).
    - Command: `scripts/delegation_eval.py --openai-model
      gpt-4.1-mini-2025-04-14 --max-tokens 1000000 --min-score 0.85`, with
      scratch data and user config.

### Phase 4 — Event protocol v2 & chat composition — `[~]` 2026-11-25
- [x] **Event protocol v2** (`server/event_log.py`, new):
  - Every event gets a `seq` from one app-level 500-entry ring. Consecutive tokens
    fold into one entry that keeps per-token pieces, so a replay never doubles text.
  - Reconnect: the server sends `hello {boot, seq}`; the client replies
    `resume {from_seq, boot}` and gets exactly what it missed, or
    `resync_required` after a restart or a gap.
  - Approvals, Stop flags and turn locks are now app-level, so they survive a
    reconnect. Turn tasks are strongly referenced.
  - `EVENT_SCHEMA` and `validate()` describe every event type.
  - Client: seq dedup, resume, resync, exponential backoff (1.5 s → 15 s), a
    guarded `JSON.parse` (fixes BUG-14).
  - Tests: `test_event_protocol.py` (12; the mid-turn resume and Stop-from-a-new-
    connection tests run against a real uvicorn server).
- [x] **Parallel read-only tools:** an explicit allowlist (`PARALLEL_SAFE_TOOLS`)
  runs concurrently, up to 4 at once, with the transcript order unchanged. Any
  side-effecting tool keeps the batch sequential. `test_parallel_tools.py` (4).
- [x] **Inline visuals** (`webui/src/components/Visuals.jsx`, `tools/visuals.py`):
  - ```` ```mermaid ```` renders client-side with mermaid 12.3.0 (lazy-loaded,
    `securityLevel:'strict'`).
  - ```` ```chart ```` takes a JSON spec and renders an in-house SVG bar, line or
    pie chart.
  - `render_visual` stores HTML and shows it in an iframe with
    `sandbox="allow-scripts"`, srcdoc, CSP `connect-src 'none'`, never
    same-origin. Requests with `Origin: null` get 403.
  - A placeholder shows while a fence is still streaming, with a fallback to the
    source on error. `/api/render_error` reaches the model once, in the next
    turn's `<context>`.
  - Persona: the mermaid stopgap is gone (fixes BUG-06). `test_visuals.py` (19).
- [x] **Message actions:** regenerate, edit-and-resend, branch, delete (truncate,
  branch and delete endpoints; turn ids on `turn_result` and in the history).
  Switching model now continues the same session, with a divider.
  `test_message_actions.py` (8).
- [x] **Step inspector** (click a step for the full input and output, duration,
  Copy) and a **plan card** (the latest `update_todos` snapshot in the reply's
  activity).
- [x] **Notices** in the timeline: `tools_trimmed`, `context_compacted`,
  `turn_budget_exceeded`.
- [x] **"Stopping…" and "Queued" states** (`turn_queued` event; `stopped` carries
  `running`).
- [x] **A2UI spike** (owner approved `@a2ui/react` + `@a2ui/web_core` 0.16.1,
  Apache-2.0):
  - `show_ui` validates v0.9 payloads server-side: structure, catalogue,
    references, size, and Button actions. Invalid payloads return a
    `render_error` to the model.
  - `ui_guide` is a lazy tool, not system-prompt text.
  - The client renders with the official `MessageProcessor` + `A2uiSurface`, in
    a lazy chunk. Actions come back as `[ui action]` messages.
  - **Bundle cost:** the A2UI chunk is 529 KB raw / 141 KB gzip (lazy); mermaid
    core is 673 KB / 164 KB (lazy); the core bundle grew about 15 KB (1,149 KB).
  - **Verdict:** the protocol works end to end, but the renderer's weight
    (zod + markdown-it + web_core) is large for the need. Revisit an in-house
    renderer for the basic catalogue on the Phase 6 `ui/` primitives.
- **Verified live** (scripted-brain demo server, scratch data):
  - mermaid and the chart rendered inline
  - the sandboxed visual's script ran, its network was blocked, and the
    frame/app isolation threw a SecurityError
  - the A2UI card rendered, and pressing Pro round-tripped
    `[ui action] choose_plan {"plan":"pro"}`
  - this caught and fixed a bug: an inline `components` map remounted every
    block on each render, resetting visuals and A2UI cards (now module-level)
- **Not yet verified live:** clicking through the message actions, the
  inspector, notices and the Stopping/Queued UI (backend covered by tests); the
  iframe auto-height fix (rebuilt, not re-checked).
- [ ] Not done: a separate `visual` event (visuals ride the existing inline-media
  path); mapping A2UI onto in-house `ui/` primitives (Phase 6).
- [x] **Regenerate fix** (owner report, 2026-11-25). Regenerate jumped to the home
  screen, the prompt vanished, and the steps only appeared after completion.
  - Cause: truncating published `history_changed`, and the tab reloaded the chat
    over the starting turn. That wiped the prompt and set the status to idle.
    Regenerating the first exchange also briefly emptied the thread, which
    rendered the home screen.
  - Fix: rewind and send in ONE update (`send(..., {keepUpTo})`), and a tab
    ignores its own `history_changed`.
  - Verified in the browser mid-turn: the prompt stays visible, no home screen,
    tokens stream live, Stop is up; the end state has one prompt and one reply.

### Phase 4b — Agent quality: behaviour, skills & toolsets, live bug hunt — `[~]`
Added 2026-11-25 at the owner's request. Driven by REAL turns on OpenAI
`gpt-4.1-mini-2025-04-14` (the owner's data-sharing allowance). The harness is
`live_probe.py`: the real app wiring, scratch data, a hard token cap.

- [x] **Live findings fixed** (baseline → after):
  - "Spawn sub-agents" never called `delegate_task`; the model faked it with
    `memory_save`. Root cause: small models essentially never call `tool_search`,
    so deferred tools are invisible. Fixed: the delegation tools and the everyday
    action tools are now core: visuals/UI, weather, news, reminders, tasks,
    media, notifications, conversation search. The persona now has a
    SUB-AGENTS rule. Now: `delegate_task` with parallel tasks, every run.
  - "Remind me tomorrow…" saved a memory and claimed "I've set a reminder" (a
    false success). Fixed: `add_reminder` is core, plus a HONESTY rule (never
    claim an action no tool performed). Now: `add_reminder`.
  - Weather scraped the web; news likewise. Now `get_weather` and `get_news`.
  - An interactive visual flailed with `run_shell` (118K tokens). Now
    `render_visual` in 23K tokens.
  - A bar chart: Mermaid failed twice, then the model refused. Fixed: the
    persona says numbers are ```` ```chart ````, not Mermaid, and the
    `render_diagram` error points to ```` ```chart ````. Now: a ```` ```chart ````
    block.
  - `render_diagram` dead-ended when no image renderer was reachable (the
    owner's machine: mermaid.ink DNS fails, no Playwright browser). Fixed: it now
    returns a ```` ```mermaid ```` fence the chat renders itself (invalid syntax
    still errors). Mermaid fences are the default for chat diagrams.
  - "Side by side" came out as paired bullet lists. Fixed: comparisons ALWAYS go
    in a table. Now: a real table.
  - "Explain X with diagrams" gave one picture dumped at the top. Fixed: teach in
    `## ` sections with visuals inside each (long answers may use headings).
    Now: 3 mermaid diagrams, a table and 5 sections.
  - Deep research was 4 searches and a paragraph. Fixed: the rewritten
    `deep-research` skill plans 3–5 angles, fans out with `delegate_task`, fills
    gaps, and writes a report with Summary, sections, tables and Sources. Now:
    `/deep-research` gives a 7-section report with tables.
  - Persona: BE RESOURCEFUL. Try alternatives (another source, rephrase,
    another format) before saying "can't".
- [x] **`/skill` commands:** typing `/deep-research <topic>` loads that skill's
  procedure into the turn (server-side, enabled skills only). The composer's
  "/" menu lists the skills.
- [x] **Toolsets tab clarity:**
  - Tools outside the active profile are dimmed with a "not in this profile"
    badge. The profile text says it never changes the per-tool switches.
  - The old "Mode" dropdown is now "How tools are sent to the model", with three
    described choices.
- [x] Rewritten bundled skills: `deep-research` (v2), `creating-visuals` (v2: a
  form-picker table plus fallbacks).
- **Tests:** `test_agent_behaviour.py` (4) and new render-fallback tests. Full
  suite: 1,360 passed, 3 skipped.
- **Live token use 2026-11-25:** about 776K tokens across three probe rounds
  (baseline 124K, round 2 537K, round 3 115K), within the 2.5M/day allowance.
- [x] **Fresh start (owner request, 2026-11-25):** all Namma data wiped (chats,
  memory, learned skills in `~/.namma_agent/skills`, checkpoints, logs, settings).
  Kept: the API keys (vault) and the provider/model list. The default model is
  now **`gpt-5.6-terra`**: compared with `gpt-5.4-mini` on the same prompts, it
  gave richer answers for similar tokens. The duplicate learned skills went with
  the wipe, so there is nothing left to merge.
- [x] **Skills revamp** (Anthropic Agent Skills conventions: the `description`
  carries every trigger plus a "Not for …" near-miss; explain why rather than
  stacking rules; a lean body with tables, gotchas and a verification step):
  - New bundled skills: `task-planning`, `data-analysis`, `documents`, `writing`,
    `troubleshooting`, `email-and-calendar` (needs `gws`), `skill-creator`.
  - `deep-research` v2.1: a per-task `budget` (8 steps, 40K tokens) so one angle
    can't consume the whole run. `one-three-one-rule` v1.1: options in a table.
  - Removed the stale `skills/Office-CLI` folder (help dumps, no SKILL.md).
  - Audit: every tool named in a bundled skill exists in the registry.
- [x] **Fixes to the remaining live issues:**
  - Sub-agent reports must use markdown: `## ` headings, tables for comparisons,
    and a `## Sources` list.
  - The persona says choices should be a `show_ui` card, not a numbered list.
  - `convert_document` is now a core tool.
- [x] **Live hunt on `gpt-5.6-terra`, round 1** (23 prompts; the 550K cap
  stopped it after 14). Real tools ran; destructive calls went through a probe
  approval function that allows only actions inside a scratch workspace.
  - Worked first time: memory save, then recall in a new chat; a choice offered
    as a `show_ui` card; data analysis (pandas, two tables, two ```chart blocks,
    figures checked exact against the CSV); a Markdown → .docx summary; email
    draft; goal with progress; reminder plus task.
  - **Follow-up turns lost context (fixed).** After creating `trip-plan`, "undo
    the packing list", "save that as a skill" and "delete the folder" each
    replied that the creation "wasn't verified in this chat". Cause: history
    carried only the final text, never what the tools did, and the HONESTY rule
    made the model distrust its own earlier claims. Fix: each assistant turn in
    the model's history now ends with an `[actions: …]` record built from its
    saved steps (`tool(path=…) → ok: summary`, at most 12 lines, bookkeeping
    tools skipped, no file contents). The persona says to trust the record and
    never to write one itself.
  - **"Put this into an Excel file" was refused (fixed).** The model said "a
    spreadsheet tool isn't loaded". `convert_document` now writes **xlsx** (no
    new dependency: a stdlib SpreadsheetML writer, one sheet per Markdown table
    named after its heading, numbers typed, bold frozen header) and **csv**. The
    persona says every format is within reach (`convert_document`, `write_file`,
    a Python script) and never to say a tool "isn't loaded".
  - **Duplicate download link with a `sandbox:` prefix (fixed):** a persona rule,
    plus the chat maps `sandbox:/api/…` links onto the real path.
  - **Token cost of `update_todos` (improved):** its description asked for a
    separate call after every step, and each round trip re-sends ~15K tokens of
    context. Progress updates now ride along with the next step's tool call.
    Plan task: 100K → 82K tokens.
  - **Core set:** the file tools the persona tells the model to use
    (`make_dir`, `move_path`, `copy_path`, `delete_path`, `organize_dir`), the
    checkpoint tools (`list_checkpoints`, `rollback`) and `create_skill` are now
    always loaded. Before this the model searched for them or skipped them.
  - `task-planning` over-triggered on "help me pick…": its description now
    excludes choosing between options.
- [x] **Round 2** (13 prompts, 346K tokens), verifying the fixes:
  - The follow-up chain now works end to end: undo → `delete_path` on the right
    file; save as skill → `create_skill`, which wrote a well-formed skill with
    triggers and a "Not for" clause; delete folder → `delete_path`. Each delete
    asked for approval.
  - Excel → a real .xlsx in 16K tokens, with no duplicate link. The file opens in
    openpyxl: typed numbers, bold header.
  - Slow-laptop check: a process table plus a diagnosis (memory pressure).
  - Focus session; email (asked for the address and approval; did not send).
  - The comparison is a table.
  - TCP teaching: a sequence diagram, a worked table, then a quiz.
  - OAuth: sectioned, with Mermaid diagrams.
  - "What did we plan about Goa?" recalled the trip, including the undo and
    the delete.
- **Live token use 2026-11-25 (this round):** 871K (round 1 524K, round 2 346K).
  About 1.95M today across all runs, within the 2.5M/day allowance.
- [ ] Not re-verified on gpt-5.6-terra (token budget): `/deep-research` with the
  new per-task budgets, and a web-sourced chart.
- [ ] Not reachable from the probe harness, still to hunt live in the app: the
  Learning Room (pose_quiz cards), projects and document RAG, watchers,
  routines, comms bridges, settings flows, the TUI.
- [ ] Regroup toolset profiles around tasks. The core set was revised from the
  live findings; profile regrouping is not done.
- **Moved elsewhere:**
  - The skills marketplace (install community skills) joins the Phase 5
    catalogue.
  - The Settings visual revamp with proper states is Phase 6.

### Phase 5 — MCP & setup experience — `[x]`
Done 2026-11-25. The rest of Phase 4b (the in-app live hunt) was deferred: the
owner had about 400K tokens left, and that hunt needs more.

- [x] **MCP** (`mcp/config.py`, `http_client.py`, `detect.py`, `catalog.py`, `manager.py`):
  - **Config rules + validation:** per-field errors (name, duplicate, command,
    url, env/headers, timeouts) block a save. Warnings don't block: a literal
    secret, a missing `${VAR}`, a string command, an unknown field.
    - Secrets are written as `${NAME}` and resolved from the vault only at
      connect time; a server's `env` adds to the inherited environment.
  - **Import** from Claude Desktop / Cursor (`mcpServers`), VS Code (`servers`),
    and the official registry `server.json` (npm → npx, pypi → uvx,
    oci → docker, remotes → http).
  - **Install-from-URL:** https only, 256 KB cap, GitHub blob/repo → raw.
  - **Detection:**
    - node/npx, uvx, Docker (CLI *and* a running engine), python;
    - free disk, with a low-space warning under 2 GB;
    - servers already configured in Claude Desktop / Cursor / VS Code / Windsurf
      (shown masked, one-click import);
    - local `mcp/*` Docker images;
    - whether each configured launcher is on PATH.
  - **Curated catalogue (11 presets):** filesystem, git, GitHub hosted (HTTP),
    GitHub local (Docker), fetch, Context7, Playwright, time, SQLite, sequential
    thinking, Docker MCP Toolkit. Each has a param form and vault secrets.
  - **GitHub toolset presets:** pick toolsets plus read-only.
    - Hosted: `X-MCP-Toolsets` / `X-MCP-Readonly`.
    - Docker: `GITHUB_TOOLSETS` / `GITHUB_READ_ONLY` env.
  - **Streamable-HTTP transport:** a stdlib client handling JSON or SSE replies
    and `Mcp-Session-Id`. Failures say bad token vs bad URL vs offline.
  - **Async connect with per-server status:** each server connects in its own
    thread (startup never blocks). Status is connecting / connected / failed
    (with the reason) / disabled, pushed to the UI as `mcp_status` events.
- [x] **Setup mode** (beside chat and agent: the mode pill or `/setup`).
  - Its own prompt and 16 tools: `setup_status`, `setup_catalog`,
    `request_secret`, `save_provider`, `save_model`, `verify_provider`,
    `mcp_detect`, `mcp_add_server`, `mcp_remove_server`, `mcp_list_servers`,
    `integration_status`, `gws_auth_login`, `mail_add_account`,
    `mail_test_account`, plus web lookups.
  - **Covers:** models and providers; MCP servers; Google Workspace via `gws`
    (installed? client set up? signed in? Gmail/Calendar/Drive APIs on?);
    other email over IMAP/SMTP with app passwords (new `tools/mail.py`:
    `mail_list`, `mail_read`, `mail_send`; presets for Gmail, Outlook, Yahoo,
    iCloud, Zoho, Fastmail, custom); Telegram, Discord, Slack, Signal, WhatsApp
    and Home Assistant status.
  - **Secrets never touch the transcript or the model:** `request_secret`
    places a secure card in the chat (a ```secret fence). The value posts to
    `/api/setup/secret` → the vault (credential names only); the agent learns
    just the name.
  - **Paste guard, in every mode:** an API key or token pasted into chat is
    removed before the log line, the model, the DB and the `turn_started` echo.
    The tab's own bubble is scrubbed too, with a notice.
  - **Verification + diagnosis:** `verify_provider` makes one 16-token call and
    classifies bad_key / bad_model / bad_base_url / unreachable / quota.
    `mcp_add_server` is approval-gated (it launches third-party code).
  - Provider catalogue +6 (OpenRouter, Groq, DeepSeek, Mistral, xAI, Together),
    each with a key URL.
- [x] **First-run onboarding:** no model the app can call → a full-screen
  "connect a model" flow (provider → key into the vault → live model list →
  Connect & test). The model becomes the default only after the test passes.
  The shipped default brain no longer counts as "ready".
- [x] **Skills marketplace** (`core/skill_market.py`, `skills_index.json`):
  - A curated index of 16 skills: Hermes Agent (MIT) and Anthropic Agent Skills
    examples, licences checked. Plus install from any GitHub skill folder or
    SKILL.md URL.
  - The whole folder is fetched (references, templates), with limits: 60 files,
    2 MB, 512 KB per file, depth 4, no path escapes.
  - The preview shows licence, files, scripts, inline shell, tools this install
    lacks, missing commands, and the injection screen.
  - Installs land **disabled**, with a `.source.json` sidecar.
  - Inline `!`cmd`` never runs for an installed skill, even when
    `skills.allow_inline_shell` is on.
- [x] **Web UI** (`components/SetupUI.jsx`):
  - the onboarding screen and the setup pill;
  - the secure card (with a "Get one" link);
  - Settings → Servers: add-server wizard, import / URL, detection, status
    badges with the failure reason, two-step remove, live refresh;
  - the Config editor validates server-side;
  - Skills → marketplace with preview.
- [x] **Isolation bugs found while verifying (fixed):**
  - The shipped `database.path: data/namma_agent.db` pinned the DB, the vault
    and memory to the repo `data/`, ignoring `NAMMA_DATA_DIR`. This also
    affected Docker/VPS installs. It now follows the data dir.
  - An explicit `NAMMA_ENV_FILE` still loaded the repo `.env`, so scratch runs
    and the test suite picked up real keys.
  - The default vault used the OS Credential Manager in tests:
    `NAMMA_VAULT_BACKEND=file`, and the suite isolates the vault and `.env`.
  - The `build_provider` type default didn't apply over an empty `base_url`.
  - The leak wrote three test chats, one memory item and two made-up keys into
    the real data. Only those artifacts were removed; the owner's chat, config
    and OpenAI key are untouched.
- **Verified live** in the browser on a scratch instance (owner's key read-only
  from Credential Manager), on gpt-5.6-terra:
  - onboarding: bad key → "rejected (401)"; then OpenAI → 103 live models →
    test passed → model switcher set;
  - setup mode: GitHub read-only → secure card → test token saved → approval
    card → server added → GitHub 401 diagnosed in chat and shown as "failed" in
    Settings with the reason;
  - paste guard: key removed from the bubble, the model, the DB and the logs.
  - Live run fixes: the model described the token instead of calling
    `request_secret`; it asked "may I?" in text before an approval-gated add;
    it pointed at an old field after a 401.
  - About 40K live tokens.
- **Tests:** `test_mcp_setup.py` (17), `test_setup_mode.py` (27),
  `test_skill_market.py` (10). Full suite: 1,420 passed, 3 skipped.
- [ ] Not done:
  - a real-token end-to-end for a working GitHub/Google/mail setup (needs the
    owner's credentials);
  - CalDAV / ICS calendars for non-Google accounts;
  - the old "MCP tabs merge" into the Phase 6 Settings revamp.

### Phase 6 — UI/UX system — `[~]`
Plan: [§4 UI/UX plan](#4-uiux-plan). Round 1 landed 2026-11-25; every
acceptance criterion below is verified. What is not done is listed at the end.

- [x] **Tokens** (`webui/tailwind.config.js`, `src/index.css`):
  - One semantic colour set (`bg`, `surface`/`-raised`/`-sunken`, `fg`/`-muted`/
    `-subtle`, `border`, `accent`/`-fg`/`-wash`, `danger`, `warning`, `success`,
    `focus`), derived from each of the 4 named themes and flipped under `.dark`,
    so new code needs no `dark:` twin. Chart (`--chart-1..8`), memory-graph
    (`--graph-1..10`) and canvas tokens too.
  - Type scale: `2xs` 11 · `xs` 12 · `sm` 13 · `base` 14 · `prose` 15 (chat
    reading size) · `md` 16 · `lg` 20 · `xl` 24. **All 532 `text-[Npx]` were
    replaced**, and **every hex literal left the components** (theme swatches
    render inside their own `theme-<id>` scope; canvases read the tokens).
  - Radius, a z-index ladder (`base` → `top`), one `overlay` shadow, 100/150 ms
    durations.
  - Contrast: `--ink-faint` (→ `--fg-subtle`) darkened in all 4 light themes
    from ~2.4:1 to ≥4.5:1 on the soft surface; the night tones already passed.
  - Body text uses the system UI stack (Segoe UI Variable on Windows). Inter
    was declared but never loaded.
  - The theme follows `prefers-color-scheme`, live, until you pick a mode.
- [x] **Accessibility basics:** one global `:focus-visible` ring, a
  `prefers-reduced-motion` block, and non-selectable chrome (`nav`, buttons,
  `[data-chrome]`). Every icon-only button has an `aria-label` (49, from 1).
  The MCP on/off switch is a `role="switch"`.
- [x] **Primitives** (`webui/src/components/ui/`): Button, IconButton (label
  required), Dialog (role, `aria-modal`, focus trap, Escape, focus restore,
  a safe initial focus that skips `data-destructive`, stacking), ConfirmDialog,
  Toast + Toaster, Kbd, EmptyState, ErrorState, Skeleton, CommandPalette.
  - **BUG-12 fixed:** the in-app confirm focuses Cancel, so Enter cancels.
  - Every modal now uses Dialog: Settings, the confirm, the palette, the sudo
    prompt, the uninstall confirm, New project, New topic, Modify path.
- [x] **Settings is deep-linkable:** `/settings/<section>` for all 21 sections
  (`src/settingsSections.js`).
  - It overlays whatever page you were on (the modal-route pattern keeps that
    page underneath), and closing goes back there. A cold link shows the chat
    underneath.
  - Section search in the nav (Enter opens the first match), a skeleton while
    loading, a toast on save.
- [x] **Command palette** (Ctrl/Cmd+K): new chat, stop, go to a page, toggle
  the theme, every Settings section, the 20 most recent chats. Arrow keys,
  Enter, Escape. **Escape stops a running turn** when no dialog is open.
- [x] **Chat performance:**
  - `Message` and `Markdown` are memoised, and ChatView's context values are
    stable. They used to be new objects on every render, which defeated any memo.
  - Streamed tokens are coalesced per session and flushed every ~50 ms
    (`src/tokenBatcher.js`). Any other event flushes first, so order holds.
  - **Core bundle 1,183 KB → 315 KB** (99 KB gzip). Settings, every non-chat
    route, the quiz card and the onboarding screen are lazy. The markdown
    pipeline is its own chunk, preloaded in parallel, with a plain-text
    fallback. KaTeX (+mhchem) and highlight.js load only when a message has
    math or a code fence.
- [x] **Tests:** Vitest + React Testing Library (`npm test`, 18):
  - `tokens.test.js`: no arbitrary sizes or hex; tokens defined in light and
    dark; reduced motion and the focus ring; titled buttons have an `aria-label`.
  - `dialog.test.jsx`: Escape, focus trap, focus restore, BUG-12.
  - `palette.test.jsx`: matching, arrow keys + Enter, Escape, deep-link slugs.
  - `chat.test.jsx`: 200 streamed updates re-render an earlier message 0
    times; the batcher; send on Enter; approve once.
  - Without the memo the transcript test fails at 201 renders; the batcher
    test fails on the bug below.
- **Verified live** (scratch instance, scripted streaming brain, isolated data;
  the real `data/` and `~/.namma_agent` were byte-identical afterwards):
  - a cold `/settings/providers` link; search → `/settings/servers`; Escape →
    `/`; opened from Projects, Projects stays underneath and closing returns
    there;
  - Ctrl+K → "settings mcp" → Enter → `/settings/config` over Projects;
  - a ~2,000-token reply streams progressively (138 → 3,429 chars over
    ~2.5 s) with **zero long tasks**; the highlight, KaTeX and mhchem chunks
    load on demand and render (code, inline math, `\ce{}`, a table);
  - Escape mid-stream stopped the turn;
  - the delete-chat confirm: Cancel focused, Enter cancelled, the chat stayed;
  - dark mode at 720 / 1100 / 1440 px (chat, Settings, palette); the New
    project dialog (focus inside, Escape closes).
  - **Caught and fixed live:** the batcher called bare `setTimeout` as a
    method (`timers.set(...)`), which browsers reject ("Illegal invocation"),
    so tokens only appeared at turn end. jsdom didn't catch it; a regression
    test now does.
- **New dev dependencies** (test-only, not shipped): `vitest` 3,
  `@testing-library/react` 16, `@testing-library/dom` 10, `jsdom` 25. Reason:
  the plan's smoke tests need a DOM test runner, and Vitest reuses the Vite
  config.
- [ ] **Not done:**
  - Migrating the legacy `paper`/`ink`/`night` classes to the semantic tokens
    (843 `dark:` classes and 240 raw Tailwind palette colours remain; new code
    and the primitives use tokens).
  - `lucide-react` for the 98 inline SVGs; bundling JetBrains Mono locally.
  - Splitting `Settings.jsx` into one file per section with a single save
    model; first-class Memory/Automations/Capabilities/Runs pages; merging the
    MCP tabs.
  - Transcript virtualisation; keyboard-selectable slash commands; a custom
    context menu; starter prompts; error bubbles with actions.
  - The playbook review rubric and anti-slop audit (not run).
  - Mapping A2UI onto the `ui/` primitives (from Phase 4).

### Phase 7 — Desktop & packaging — `[✗]` superseded by Phase 9 (W3, Electron)
Kept for reference: the acceptance criteria below carry over to Phase 9 W3.
- [ ] **Shell (pywebview kept; see the decision log):**
  - window-state persistence
  - theme-aware background colour
  - boot splash, plus an error page with logs, retry and safe mode
  - close-to-tray option
  - global hotkey (`RegisterHotKey`)
  - native menu (pywebview 6)
  - custom context menu and selective `user-select`
  - deep links forwarded over local HTTP
  - pystray off the main thread
- [ ] Notifications: `windows-toasts` with an installer-created Start-menu shortcut and
  AUMID.
- [ ] Installer: Add/Remove entry, clean uninstall (with a keep-my-data prompt),
  updater with progress and rollback.
- [ ] Lazy startup: MCP, comms and runners start after the window is shown. Bundle the
  fonts locally.
- **Acceptance:**
  - Cold start to an interactive window in under 4 s.
  - A second launch focuses the existing window (done in Phase 1).
  - Uninstall leaves no registry or shortcut residue.

### Phase 8 — Multi-device access — `[!]` needs owner decision
- [!] Write a design ADR before any code, covering:
  - access keys registered per profile in the DB through a shell script
  - native, web, mobile (PWA) and Telegram as clients of one instance
  - local-first by default, with a shared DB only when hosted
  - WhatsApp-style linked-device session sync

  Implementation is gated on owner sign-off.

### Phase 9 — Native remake: Electron app + Hermes-style redesign — `[~]`
Owner request, 2026-11-25:
- a real native desktop app (notifications, a proper install and uninstall);
- every screen redesigned on Hermes Agent's layout;
- Hermes-style provider setup with Hermes' provider list;
- the model picker out of the header; modes picked from a list;
- no Save buttons where things can save themselves;
- Roman-empire characters.

The plan is in `plan/2026-11-25_23-20-00_plan.md`. Owner decisions:
- Electron (not Tauri);
- Roman roles, personas and theme;
- API keys plus official OAuth only.

Each workstream edits only its own subsection below.

#### W1 — Shared renderer redesign (web + desktop) — `[~]` (slices 1-4 landed; the W2/W4-dependent bits are open)
Slice 1 landed 2026-11-25. Everything marked `[x]` is verified live.
- [x] **Modes are picked from a list.**
  - `ui/SelectMenu.jsx` (listbox: arrow keys, Enter, Escape, click-outside, focus return) replaces the 3-way `ModePill`.
  - Each mode shows its Roman role and a one-line description (`src/roles.js`): Agent · Imperator, Chat · Scriba, Setup · Architectus.
  - A new chat opens in `conversation.default_mode`: `/api/config` now reports `default_mode` (`service.py` `_default_mode`, `test_ui_shell_config.py`).
  - The palette has "Mode: …" commands.
- [x] **The model picker left the header.**
  - `ModelSwitcher` (a `<select>` in the ChatView header) is gone.
  - `ui/ModelPicker.jsx` is a searchable overlay that treats hyphens, dots, underscores and spaces as equivalent. It opens from the composer's model chip, the status bar, or the palette ("Choose a model…").
  - Project and Learning chats keep their summarise-and-switch flow.
- [x] **Settings save themselves** (`src/useAutosave.js`, `ui/SaveStatus.jsx`).
  - Config fields save ~400 ms after the last edit; secrets save on blur, so a half-typed token is never stored. A failed write rolls the view back to the server's values and shows "Couldn't save. Retry".
  - Removed: the footer Save, "Save providers", "Save models", "Save name", and every "Apply". Providers and Models save their rows ~600 ms after an edit, and new rows pick up their server id (no duplicates).
  - Still explicit: Create/Save persona (it creates a document), MCP "Apply & reconnect" (it relaunches servers), Test connection.
  - Copy that told users to press Save was rewritten.
- [x] **Hermes shell, skeleton** (`components/shell/`):
  - `TitleBar`: sidebar toggle, Settings, search/command box, side-panel toggle. It drags the window on desktop and reserves `titlebar-area-*` for Electron's window controls.
  - `StatusBar`: connection, role · mode, a model shortcut, Working…, Commands.
  - `RightPane`: Runs and Plan tabs, remembered. When it's open, those panels stop docking above the composer.
  - The composer is always stacked (text on top, a toolbar row below), so narrow windows no longer crush the text field.
  - `src/desktop.js` feature-detects the W3 `window.nammaDesktop`.
- **Tests:** `phase9.test.jsx` (11):
  - autosave batching, flush on blur, rollback + retry, failure detection;
  - mode roles; listbox keyboard and Escape (the Escape is marked handled, so it never also stops a turn);
  - loose model search, keyboard pick, the empty state.
  Web UI: 29 passed. Python: 1,424 passed, 3 skipped.
- **Verified live** (scratch server, scripted brain that reports the tool count; the real `data/` and `~/.namma_agent` were byte-identical afterwards):
  - Chat mode sent the model **0 tools** and Agent mode sent **45**, so the list really drives the turn;
  - "llama32" found "Llama 3.2"; picking it continued the chat with a divider and updated both chips;
  - History turns 12 → 17 showed "Saved" and survived a reload;
  - a forced 500 rolled the field back and showed Retry, and Retry saved;
  - renaming a model in Models persisted with no duplicate row;
  - 720 / 1100 / 1440 px in light and dark; no console errors.
  - **Caught and fixed live:** at 720 px the new toolbar chips crushed the text field to one letter. The composer is now always stacked.
- [x] **Slice 2 (2026-11-26, owner requests):**
  - **Hermes titlebar band** (`components/shell/TitleBar.jsx`). The full-width titlebar row with a search box is gone.
    - Each top-edge panel draws its own 34px header in the band: sidebar (logo + name), main view (chat title / breadcrumbs / Download, portalled in by ChatView; other pages show their name), side panel (Runs / Plan tabs).
    - Fixed tool clusters, as in Hermes' `titlebar-controls.tsx`: left = sidebar toggle at a 14px inset; right = Settings + side-panel toggle, pinned left of Electron's window controls (`--titlebar-tools-right` from `titlebar-area-*`).
    - Nothing in the centre. Bottom hairline plus a 16px fade. Drag regions on desktop.
    - Below 1024px the side panel floats over the chat as a drawer instead of squeezing it (found live: at 720px it left the chat ~140px).
  - **Chat header speaker toggle removed** (with the old header).
  - **Composer:**
    - Placeholders shortened ("Message {name}…", "What should we set up?").
    - An empty field is always exactly one line with `overflow-y: hidden`, so a wrapping placeholder can't add a scrollbar; it ellipsises.
    - The hands-free headset button was removed.
  - **OS-native voice** (`core/os_voice.py`; `GET /api/voice`, `POST /api/voice/tts`, `POST /api/voice/stt`; `src/voice.js`):
    - Read-aloud uses the system's voices: Windows SAPI via PowerShell `System.Speech`, macOS `say`, Linux espeak-ng.
    - Dictation records 16 kHz mono WAV in the page and the server transcribes it with Windows SAPI dictation. The cloud `comms.stt` endpoint and the browser's recognizer are fallbacks.
    - Text and paths reach PowerShell only via env vars and temp files.
    - Caps: 6,000 chars TTS, 12 MB STT (enforced while streaming). Missing engines give clear "install X" errors.
    - Settings → Behavior → **Voice** replaces the stale "Enable Piper voice" toggle: engine choices (auto / system / browser; dictation also cloud), system-voice picker, speed, Test voice. It autosaves.
  - **Tests:**
    - Python: `test_os_voice.py` (13) covers PowerShell injection safety, rate clamp, macOS `say`, the engine fallback order, input caps, a missing recognizer, and all three endpoints.
    - Web UI: `voice.test.js` (5) covers the WAV header, downsampling, engine choice and fallback, and markdown stripping.
    - Python 1,437 passed / 3 skipped; web UI 34 passed; ruff clean.
  - **Verified live:**
    - On this machine: two system voices (David, Zira); TTS 0.6 s; a speak → dictate round trip through the real server in 0.76 s returned "Please open the project settings in check the weather".
    - The Read aloud button fetched the system-voice WAV and played it.
    - The band was checked at 720 / 1100 / 1440 px, light and dark; no console errors; scratch data only.
    - **Not verified live:** microphone capture in the browser pane (it needs a permission prompt). The server half of dictation is verified, and the WAV encoder is unit-tested.
- [✗] **Slice 3 (2026-11-26): the owner's painting as the chat background.** Superseded the same day by slice 4 at the owner's request ("remove the background given"). `chat-background.webp` is deleted.
- [x] **Slice 4 (2026-11-26, owner request): painted paper background + the rest of W1.**
  - **Chat background: painted, crumpled paper** (`components/ChatBackdrop.jsx`, `index.css` `.chat-bg*`).
    - Layers are generated by `webui/scripts/make_chat_art.py` from the owner's PNGs (Desktop: 40.png brush wash, 14.jpg ink splatter, 19.png drip hand, 10.png masks, 7.png hands) into `public/brand/bg/` (7 files, 468 KB).
    - Every layer is an alpha mask or a neutral texture, coloured from tokens:
      - primary paint = the theme accent;
      - mode paint = Agent gold / Chat terracotta / Setup teal, with lighter dark-mode variants;
      - line art = the theme ink;
      - crumpled paper = a Worley F2-F1 crease field, multiplied on light themes and soft-light on dark ones;
      - a veil in the theme background colour down the reading column.
    - Paint is procedural dry-brush (bristle streaks, a dry tail, pigment pooling, a wet bloom) and fades towards the centre.
    - A slow drift; a bloom when the mode changes; while a turn runs, the drip hand's ink pulses in the mode colour. The masks and hands hide below 760px (container query). Reduced motion is honoured.
  - **Settings split** (3,132 → 174-line shell): 22 modules in `components/settings/` (one per section plus `shared.jsx` and `icons.jsx`). Behavior, Browser, Messaging and Appearance became components fed one `form` object.
  - **Settings → Model**: Providers + Models merged. Sections: Default model, Add a model (the wizard), Connections, Your models. **Settings → MCP**: Servers, plus the raw JSON folded underneath. Old links (`/settings/providers|models|servers|config`) still land.
  - **Onboarding wizard** (`components/setup/ModelWizard.jsx`, which replaces the old `ProviderOnboarding` body):
    - steps: Provider (search + Popular/Aggregators/Cloud/Local groups) → Sign in (key with "Get one", "Sign in with OpenRouter", an endpoint field when needed) → Model (live list, loose search, custom id) → Connect & test → Done;
    - the same component is used in Settings → Model;
    - it is built on `src/providerContract.js`, which speaks the plan's W2 contract and falls back to today's endpoints (no OAuth; default model = first in `models:`).
  - **Right pane: Files + Preview** (`chatFiles.js`, `shell/FilePreview.jsx`):
    - Files lists attachments plus every `/api/media/...` file the chat references (the chat export's rule);
    - Preview shows images, sandboxed HTML (`allow-scripts`, never same-origin), PDFs, audio/video and text (first 200 KB);
    - uploads are listed but not previewed (they aren't served).
  - **Profile rail** (`shell/ProfileRail.jsx`): persona avatars above Settings in the sidebar (monograms in chart tokens until W4 portraits; `portrait` URLs are already supported). Click switches persona; "+" opens Settings → Persona. It stays in sync with the Persona tab.
  - **Tabler icons** (`@tabler/icons-react` 3.53): the shell, sidebar, composer, chat, settings, panels, image viewer and views. A codemod matched icons by their path data. About 25 decorative or content SVGs remain (charts, learning cards).
  - **Imperium theme** (fifth named theme):
    - parchment/marble light and wine-black dark, a Tyrian-purple accent, bronze laurel;
    - Cinzel (`@fontsource/cinzel`, OFL-1.1, Latin 600) for headings only;
    - an original code-drawn laurel wreath (`components/Laurel.jsx`) around the logo in the empty chat;
    - every text pair is >= 4.5:1 (tested).
  - **Tokens:** `dark:` classes went 814 → 95 by an exact-equivalence codemod (no visual change by construction). New semantic tokens: `surface-hover`, `surface-press`, `fg-soft`, plus status colours mapped to `success`/`warning`/`danger`. The 95 left are one-off status tints.
  - Dev: `vite.config.js` proxies to `NAMMA_API_PORT` (default 8000), so a scratch backend can sit behind `npm run dev`.
  - **Tests:** `w1.test.jsx` (12): Files/Preview incl. the sandbox, the rail switch, the wizard happy path + failed test + search, `active_model` fallback, merged tabs + aliases + an icon per section, the Settings shell size, Imperium contrast, the laurel, a `dark:` ceiling. `brand.test.jsx` rewritten (5). Web UI **51 passed**; Python **1,437 passed / 3 skipped** (no backend change).
  - **Verified live** (scratch backend + Vite; the real `data/` and `~/.namma_agent` had the same file list, sizes and mtimes afterwards):
    - the background in light and dark, and the mode paint switching to terracotta in Chat;
    - Imperium with the Cinzel heading and the laurel;
    - Settings → Model at `/settings/models`: the wizard against the real local Ollama (live list, then Connect & test showing the real "does not support chat" error);
    - `/settings/servers` → MCP; the side panel's four tabs; the dark-mode Projects, Memory and Settings views.
  - **Not verified live:** a successful wizard connect (no chat model on this machine; covered by a mocked test); Files/Preview with real generated media (mocked test); OpenRouter sign-in (needs W2).
- [ ] **Left for W1 (blocked or deliberately left):**
  - `[!]` OAuth sign-in and an explicit `active_model` need W2's endpoints. The UI already calls them and falls back.
  - `[!]` Persona portraits need W4.
  - 95 `dark:` status tints have no semantic token yet.
  - About 25 content SVGs (learning cards, charts) are still hand-drawn.
  - The laurel isn't in the brand mark: that's the owner's logo art.
  - `npm audit` reports 20 pre-existing advisories (not introduced here).

#### W2 — Provider & setup parity (backend) — `[ ]`
Its own session. Single catalogue, Hermes' provider list, OpenRouter PKCE, explicit `active_model`.

#### W3 — Electron desktop app — `[ ]`
Its own session. `desktop/`: NSIS installer and uninstaller, tray, toasts, autostart, deep links, auto-update, and backend hooks under `NAMMA_DESKTOP=1`.

#### W4 — Roman characters — `[ ]`
After the W1 shell:
- roles Imperator / Scriba / Architectus / Legatus;
- personas Caesar, Cicero, Augustus, Seneca, Aurelius;
- original portraits.

### Phase 10 — Memory graph and its primitives — `[x]` 2026-11-26

The owner: the Memory graph was "very absurd" — not built properly, Schema and Ranked
"not working properly", "not maintaining proper relations between entities". This phase
rebuilds the graph as a derived, typed structure over Engram's facts and redesigns the
Memory page. Branch `claude/phase10-memory-graph-05e8d1` (from `phase9-w1`).

#### Audit (2026-11-26) — what the graph produced, and why it was wrong

Method: `scripts/seed_memory_graph.py` replays 16 realistic turns through the REAL write
pipeline (`EngramWriter.process`) with a scripted model returning the kind of output a
cloud model returns (inconsistent subjects, synonym predicates, phrase/literal objects, a
city move, a restatement). Seeded into a scratch DB and viewed on a scratch server
(`NAMMA_DATA_DIR` etc. pointed at a temp folder). The owner's real DB was only read
read-only (`immutable=1`) for aggregates: 2 entities, both type `thing`, one relation whose
object is a clause, still live although its fact had left recall.

On the seed (20 facts) the old graph had **21 entities and 19 live edges**:
- **Every entity was type `thing`.** `add_relation` never passed a type and the extractor
  never asked for one. So **Schema** showed one bubble, and the frontend drops same-type
  edges, so it had **zero edges**. **Ranked** was one column of 21 nodes sorted by raw degree,
  labels overlapping.
- **The user was four nodes**: `user`, `the user`, `I`, `Santhosh`. Normalisation was
  lower-case plus whitespace only. `user -has_name-> Santhosh` was an edge, not an identity.
- **Duplicates**: `Namma Agent` and `Namma Agent project`. `Santhosh -loves-> Python` and
  `-likes-> python` were two edges (one relation per fact row, no dedup).
- **Relations pointing at text**: `user -age-> "21"` and
  `user -wants_github_tool_access-> "read-only repositories and issues only"` were nodes.
- **Untyped predicates**: free-form snake_case (`is_building`, `built_with`, `collaborates_with`)
  with no synonyms, no inverse handling, and no symmetric relations.
- **Supersession only half-reflected**: the resolver's UPDATE expired the old edge, but the
  orphan `Bangalore` node stayed in the graph. A contradiction the resolver missed (it
  often ADDs) was never caught at graph level. `archive()` never expired edges (the
  real-data case above). Approved pending facts never reached the graph.
- **Ranking computed from nothing meaningful**: degree only (no importance, frequency or
  recency). The graph view's node size was degree too.
- Facts without a triple (raw explicit remembers) never linked to any entity.

#### Data model and primitives — `namma_agent/core/engram/graph.py` (new)
- [x] **Entity**: canonical key `norm` (stable id = uuid5), display `name` (most-used surface
  form; longer wins ties, so full name over acronym; the user's own name for the self
  entity), `type` from a vocabulary (person, organization, place, project, technology,
  animal, event, concept, product). Unknown types pass through, so the schema reflects the
  data. Also `aliases` (surface forms with counts), `is_self`, and attributes.
- [x] **Alias table** (`memory_entity_aliases`): every lookup key maps to an entity. `auto` rows
  are rebuilt; `name` rows come from has_name facts; `manual` rows (user merge or rename)
  survive rebuilds. User-chosen display names are pinned in `memory_meta`.
- [x] **Relation**: canonical snake_case `rel`, directed `src → dst`, `confidence` (noisy-OR over
  supporting facts), bi-temporal `valid_from` / `created_at` / `expired_at`, and `superseded_by`
  (the replacing relation). One row per live (src, rel, dst); each asserting fact is a row in
  `memory_relation_sources`.
- [x] **Attribute** (`memory_attributes`): literals (numbers, dates, emails, URLs), lower-case
  clauses and `age`/`birthday`/… hang off the entity, with the same lifecycle as relations.
- [x] **Resolution**: case, whitespace, article and possessive folding. "Full Name (ACR)"
  registers both keys. Generic suffixes ("… project", "… programming language") are dropped
  for matching and display. "A Kumar" keeps its initial. `user` / `the user` / `I` / `me` / `my`
  resolve to the self entity. Bare pronouns never become nodes. A has_name fact makes the
  name an alias of the self entity and **merges** a node created earlier under that name.
- [x] **Predicates**: 114 synonym/inverse spellings map onto 22 canonical relations (`loves` → `likes`,
  `is_building` → `works_on`, `built_with` → `uses`, …). Inverse spellings are flipped
  (`employs` → `works_at`, `sister_of` → `has_sister`). Symmetric relations (`works_with`,
  `friend_of`, `married_to`, …) dedupe in either direction.
- [x] **Typing**: model types win. Otherwise types are inferred from the predicate's
  range/domain (has_pet → animal, lives_in → place, works_on: person → project) or a
  technology lexicon; `concept` is the fallback.
- [x] **Contradictions**: a functional predicate (`lives_in`, `studies_at`, `born_in`, `from`,
  `married_to`, `works_as`) keeps one live object per subject; `likes` ⇄ `dislikes` replace
  each other. The loser gets `expired_at` + `superseded_by`. A fact whose only graph content
  was the superseded relation is invalidated too (history kept).
- [x] **Lifecycle**: invalidate and archive call `item_gone`. A relation expires only when no
  other live fact asserts it. Hard delete removes sources, then orphan entities.
  `approve_item` links the approved fact.
- [x] **Schema** (`MemoryGraph.schema`) is derived from the live graph: types with count,
  attribute keys and examples; relation kinds with count, symmetric/functional flags and
  the (source type → target type) pairs they really connect.
- [x] **Ranking** (`MemoryGraph.ranked`):
  `score = 0.45·centrality + 0.30·salience + 0.25·recency`, where:
  - centrality = weighted PageRank on the undirected live graph (weight = supporting
    facts × confidence), normalised to the max;
  - salience = 0.7·max importance of supporting facts + 0.3·min(1, log2(1+mentions)/4),
    where mentions = summed fact frequency;
  - recency = 0.5^(days since newest supporting fact was seen / half-life), with the
    half-life from `memory.consolidate.half_life_days` (30).

  Every component is returned.
- [x] **Write pipeline on the user-selected model**: the extraction and consolidator promote
  prompts ask for canonical names, `"user"` for the user, a preferred predicate vocabulary,
  and `subject_type` / `object_type`. The calls still go through the provider getter (the
  Settings model, never a hardcoded one). Types are stored on `memory_items`
  (new columns), and `EngramWriter._apply` links through `store.link_item`.
  `merge_triple_duplicates` now folds through entity resolution.
- [x] **Migration**: `MemoryGraph.rebuild()` re-derives the graph from the facts in time
  order, so the history slider keeps working. It replays every fact (live, superseded or
  archived), plus relations that never had a fact (the Cognee import). It runs once when
  `graph_version < 2` (on open) and on demand from `POST /api/memory/graph/rebuild` (the
  page's **Rebuild** button). It is idempotent.
- [x] **API** (`server/api.py` → `service.py`):
  - `GET /api/memory/graph` — typed nodes with aliases, attributes, degree and score; edges
    with id, rel, directed, confidence, support, source fact, valid_from, expired and
    superseded_by;
  - `GET /api/memory/graph/nodes` and `/edges`;
  - `/entity/{id}` (neighbourhood + source facts + rank);
  - `/schema`, `/ranked`, `/search?q=`;
  - `POST /api/memory/graph/merge`, `POST /entity/{id}` (rename/retype) and `/rebuild`.
  - `EngramStore.graph()` / `add_relation()` / `upsert_entity()` / `entity_items()` stay as
    wrappers. Recall's mention keys exclude the self entity (so "I"/"my" don't pull the hub).

**Result on the same seed after migration: 14 entities, 15 live relations, all typed.**
- The user is one node named "Santhosh" with `age` and the GitHub preference as attributes.
- `Namma Agent project` is an alias of Namma Agent; KARE is an alias of the full college name.
- `loves` + `likes` became one `likes` edge with support 2 and confidence 0.91.
- Bangalore is superseded: out of the live view, kept in history.
- Schema: 8 types and 13 relation kinds with real type pairs.
- Ranked: Santhosh 0.98, Arjun 0.52, Namma Agent 0.51, Python 0.49, …

#### Memory page redesign (`webui/`)
- [x] `components/memory/graphModel.js` (pure, tested):
  - type → theme chart token (`--chart-1…8`, `concept` = `--fg-subtle`);
  - deterministic force layout (Fruchterman–Reingold, precomputed, landscape gravity — the
    same memory always draws the same way, nothing jitters);
  - parallel-edge fan-out, neighbourhood and alias-aware search.
- [x] `components/MemoryGraph.jsx` rewritten (canvas, no graph library):
  - nodes coloured by type and sized by rank; the self entity has an accent ring;
  - directed arrowheads (none on symmetric relations), relation labels as pills with
    collision avoidance, screen-constant text at any zoom, superseded edges dashed in history;
  - click to focus (the neighbourhood stays lit), drag nodes, pan, wheel/buttons zoom, Fit,
    a labels toggle, and Esc/+/−/0 keys;
  - a type legend that hides/shows types; it re-frames when the details panel opens;
  - colours are re-read on theme/dark class changes.
- [x] `components/memory/EntityPanel.jsx`: type, aliases, attributes, live relations (direction,
  support, confidence), superseded relations with when, source facts (superseded struck
  through, "mentions it" for raw facts), rename/retype, and "Same as another entity…" merge.
- [x] `components/memory/SchemaView.jsx`: an SVG type diagram at 1:1 pixel scale (aggregated
  type→type relations, self-type loops), entity-type cards and a relation-kind table with
  type-pair chips.
- [x] `components/memory/RankedView.jsx`: score plus centrality/salience/recency bars, links ·
  facts, last seen, and the formula in a caption. Click to focus.
- [x] `views/MemoryView.jsx`:
  - an Explore card with Graph/Schema/Ranked tabs (the last tab is remembered), entity
    search with alias hits, History slider, Rebuild and the details panel;
  - the existing core-memory editor, Ask, Facts browser, Remember/Improve, Environment and
    Forget, restyled;
  - semantic tokens only, `components/ui` primitives, Tabler icons, translucent surfaces;
    `dark:` pairs: 6 → 0 in these two files.
- [x] Verified on the scratch server (seeded DB migrated on open):
  - Graph, focus + panel, Schema, Ranked;
  - Imperium light/dark, default dark, classic light, mono dark (Schema) and slate light
    (Ranked);
  - screenshots were taken in-session; the before/after notes are in the session-notes folder.

#### Tests
- [x] `namma_agent/tests/test_memory_graph.py` (38): canonicalisation, resolution (self, has_name
  merge, acronym, suffix, case, initials, pronouns), typing, attributes, dedup + noisy-OR,
  symmetric, inverse, functional and likes/dislikes supersession with fact retirement,
  archive/hard-delete/approve lifecycle, manual merge surviving rebuild, writer extraction
  with a mocked model on the provider getter, schema, PageRank/ranking formula, legacy-data
  migration plus time-travel history, the full seed, and the API surface via TestClient.
- [x] `test_engram_phase2.py`: the hard-delete test now expects the self entity "You"
  (the GC behaviour it guards is unchanged).
- [x] `webui/src/test/memory.test.jsx` (15): graph model, MemoryGraph controls/legend/focus,
  Schema, Ranked, and MemoryView tabs + search → focus → entity panel facts.
- [x] Full suites: **Python 1,475 passed / 3 skipped** (1,437 before); **web UI 66 passed**
  (51 before); `vite build` OK.

#### Not done / not verified
- [ ] Not run against a live model (no key given for this task). The extraction prompt's new
  fields are covered with a scripted model only.
- [ ] Entity resolution is rule-based. Synonyms with no shared key ("VS Code" vs "Visual Studio
  Code") stay separate until merged by hand in the panel (the merge is remembered).
- [ ] The functional-predicate list is fixed in code; `works_at` is deliberately left out
  (people can hold two jobs).

---

## 4. UI/UX plan

Built with the UI Playbook. The Hermes desktop kit is a reference for principles and
interaction patterns only; its visual identity is not copied.

**Context:**
- A daily-use, high-frequency personal agent on the desktop, used by power users.
  Destructive tools raise the stakes.
- Personality: *calm, capable, transparent, not flashy, not toy-like*.
- Visual language: quiet utility / native desktop. Flat, not boxed; one primitive per
  concern; tokens, not literals; intent before automation.
- **Effect budget: zero decorative effects on app screens.** Motion only for feedback
  and orientation, at 100–150 ms.

**Tokens:**
- **Colour:** one semantic set (`--bg`, `--surface`, `--surface-raised`, `--fg`,
  `--fg-muted`, `--fg-subtle`, `--border`, `--accent`, `--accent-fg`, `--danger`,
  `--warning`, `--success`, `--focus`). It is redefined under `.dark` and for each of
  the 4 named themes, replacing the `paper`/`night` split (about 749 `dark:`
  duplicates). Follow `prefers-color-scheme` by default.
- **Type:** 11 / 12 / 13 / 14 / 16 / 20 / 24 as named sizes, replacing the 428
  arbitrary `text-[Npx]` values. Body text uses the system UI stack (Segoe UI Variable
  on Windows); JetBrains Mono is bundled locally for code.
- **Radius:** 4 / 6 / 10 / full. **Spacing:** 4px base.
- **Elevation:** one overlay shadow plus a hairline, and a z-index ladder: base,
  sticky, dropdown, overlay, modal, toast.
- **Contrast:** body text ≥4.5:1, including "subtle" text.

**Primitives** (`webui/src/components/ui/`):
- Button, IconButton (required `aria-label`, ≥32px), Input, Select, Toggle, Field.
- Dialog (role, focus trap, Escape, focus restore, safe default focus) and Menu
  (arrow keys).
- Tooltip, Toast (app-wide feedback), Section, Skeleton, EmptyState, ErrorState, Kbd.
- `lucide-react` icons replace the 95 inline SVGs. Radix for Dialog, Menu and Tooltip
  only if it justifies its bundle cost.

**Information architecture:**
- Chat stays home.
- Settings becomes route-addressable `/settings/:section`: a master/detail overlay with
  search and one save model, split one file per section and migrated section by
  section with the old modal as a fallback.
- First-class pages: Memory, Automations (watchers and routines), Capabilities (tools,
  skills, MCP), Runs (subagents).
- Ctrl+K command palette and a shortcut map; Escape stops a running turn; slash
  commands are keyboard-selectable.

**Chat performance:**
- Memoise `Message` and `Markdown`, batch token updates every ~50 ms, virtualise long
  transcripts.
- Code-split routes, Settings, KaTeX and mermaid, so the core bundle is under 400 KB.

**States:**
- Error bubbles use `--danger` and carry actions (retry, open settings).
- Starter prompts in the empty chat; skeletons instead of "Loading…" text.

**Desktop feel:** non-selectable chrome, a custom context menu, a theme-matched window
background, reduced-motion support.

**Review loop:**
- Render at 720 / 1100 / 1440 px in light and dark.
- Run the playbook review checklist and anti-slop audit; the rubric must score ≥4.
- Vitest + React Testing Library smoke tests: send, approve, palette, dialog Escape.

**Acceptance (Phase 6):**
- No arbitrary font sizes or hex literals in components.
- Every icon button has an `aria-label` and a visible focus ring; every dialog traps
  focus and closes on Escape.
- `prefers-reduced-motion` is honoured.
- Settings is deep-linkable.
- Streaming a 2,000-token reply doesn't re-parse earlier messages.

---

## 5. Known issues & bugs

| ID | Severity | Issue | Where | Status |
|---|---|---|---|---|
| BUG-01 | Critical | Auto mode replaced *every* approval callback with "allow", so routines, watchers (acting on web/email content) and `/v1` ran destructive tools | `service.py` `run_turn` | `[x]` fixed 2026-11-25: `trust.decline_all` is never overridden (`test_approval_policy.py`) |
| BUG-02 | Critical | Remote-channel turns passed `approval=None`, which skips the destructive-tool gate | `service.py` `_channel_turn` | `[x]` fixed: owner allowed, trusted declined unless `comms.trusted_can_run_destructive`, untrusted declined |
| BUG-03 | High | Sub-agent left the session contextvar on its hidden session, so the parent's todos, shell cwd, notes, checkpoints and artifacts went there. Also: unbounded child steps, Stop didn't reach the child, unknown toolsets silently fell back to research tools | `core/builtins.py` | `[x]` fixed (`test_tools_wave4.py`) |
| BUG-04 | High | Over 128 tools (native + GitHub MCP) and every OpenAI request fails ("array too long … 128") | `core/agent.py`, `mcp/manager.py` | `[x]` stopgap: hard cap plus safe names. Real fix (tool search) is Phase 2 |
| BUG-05 | High | Runaway tokens: unlimited steps, uncapped tool results kept in context, `read_file` up to 200K chars, `find_files` walking `.venv`/`node_modules` | `config.yaml`, `core/agent.py`, `tools/file_ops.py` | `[x]` defaults fixed. Measurement and budget are Phase 2 |
| BUG-06 | Medium | Mermaid never rendered client-side; raw code shown | `webui/src/components/Markdown.jsx` | `[x]` fixed 2026-11-25: client-side mermaid 12 (Phase 4), verified live |
| BUG-07 | Medium | `.env` newline injection; "applied live" untrue for agent knobs; six setters rebound `self.config` (stale runners) | `config.py`, `service.py`, `server/api.py` | `[x]` fixed (`test_settings_hardening.py`) |
| BUG-08 | Medium | Second launch built a full duplicate service (Telegram poller, MCP processes, runners) plus a second window and tray | `app.py` | `[x]` fixed (`test_single_instance.py`) |
| BUG-09 | Medium | `/api/upload`: no size cap (whole body read into RAM), same-name overwrite | `server/api.py` | `[x]` fixed |
| BUG-10 | High (privacy) | `data/checkpoints/` personal snapshots tracked in git | repo | `[x]` untracked and gitignored. They still exist in history; rewriting it is the owner's call |
| BUG-11 | Medium | In Docker, the config overlay and `.env` live in the image layer, so UI edits are lost on recreate; `--env-file` values beat `.env` | `Dockerfile`, `config.py` | `[~]` 2026-11-25: the user config (`user_config.yaml`) and `.env` now live in `$NAMMA_DATA_DIR`, so edits persist (`test_self_knowledge_config.py`). Still open: a real `--env-file` variable beats a UI-saved value at the next boot (documented precedence) |
| BUG-12 | Low | Confirm dialog autofocuses the destructive button (Enter deletes) | `webui/src/App.jsx` | `[x]` fixed 2026-11-25: `ui/ConfirmDialog` focuses Cancel (`dialog.test.jsx`), verified live |
| BUG-13 | Low | Window background hard-coded light (flash for dark-mode users) | `app.py` | `[ ]` Phase 7 |
| BUG-14 | Low | WebSocket `JSON.parse` without try/catch; fixed 1.5 s reconnect, no backoff | `webui/src/api.js` | `[x]` fixed 2026-11-25: guarded parse, exponential backoff, resume |
| BUG-15 | Low | `self_knowledge.md` stale ("FRIDAY", wrong tools, wrong default model) | `namma_agent/self_knowledge.md` | `[x]` fixed 2026-11-25: rewritten, and `about_namma` now generates the live sections |
| BUG-16 | Low | A pending approval blocks a worker thread for up to 300 s on the WebSocket path | `server/api.py` | `[ ]` Phase 4 |
| BUG-19 | Critical | **Stop didn't stop.** Owner report: "it shows stopped in the UI but the model works and completes the whole task; an immediate new prompt runs two things at once in the same chat." Causes: Stop was only checked between agent steps (an in-flight model call and every tool in the step ran to completion); tokens kept streaming; running shell commands weren't killed; a pending approval held the turn for up to 300 s; the WebSocket server ran same-chat turns concurrently, and the older turn's cleanup deleted the newer turn's cancel flag | `core/agent.py`, `core/shell_session.py`, `tools/shell.py`, `server/api.py` | `[x]` fixed 2026-11-25. Model calls abort within ~0.2 s; tokens are dropped after Stop; remaining tools in the batch are skipped; shell commands are killed; approval waits release; same-chat turns run one at a time (a new prompt waits for the stopped turn to wind down). See `test_stop_turn.py` (6); the WebSocket test fails on the old code. **Known limit:** a blocked HTTP read can't be killed, so the abandoned model call may finish in the background (output discarded; provider tokens still billed). The UI goes idle on click with no "stopping…" state yet (Phase 4). |
| BUG-17 | Medium | Observed live 2026-11-25: the WhatsApp QR channel (whatsmeow) is rejected as "Client outdated (405)" | `comms/` WhatsApp QR bridge | `[ ]` Needs a whatsmeow client update; triage in Phase 5 |
| BUG-18 | Low | Observed live 2026-11-25: Telegram sends at startup return HTTP 403 (bot blocked or wrong chat id in the local config) | `comms/telegram.py` / local config | `[ ]` Check the owner's bot/chat config; surface a clear error in the Messaging tab |

---

## 6. Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-11-25 | **Electron desktop app replaces pywebview (reverses "keep pywebview")** | Owner asked for a native app that handles notifications, install and uninstall properly. Hermes Desktop is Electron + React; Node is installed, Rust isn't. The pywebview launcher stays as a fallback for one release. |
| 2026-11-25 | **Adopt Hermes Desktop's layout and interaction model; keep Namma's own name and art** | The owner wants the Hermes UI. Hermes is MIT (credited in `THIRD_PARTY_NOTICES.md`). Its name and ☤ mark are not used, and its renderer can't be reused directly (different gateway, `@nous-research/ui`). This supersedes "identity not copied" in §4. |
| 2026-11-25 | **No ChatGPT/Codex or Claude-subscription OAuth** | Both reuse another product's OAuth client (Hermes routes Claude "as Claude Code"), which conflicts with the providers' terms and can break without notice. API keys everywhere, plus official third-party OAuth (OpenRouter PKCE). |
| 2026-11-25 | **Phase 6: semantic tokens sit on top of the legacy palette instead of replacing it** | The `bg`/`surface`/`fg`… tokens derive from each theme's `paper`/`ink`/`night` values, so all 4 themes and the 843 existing `dark:` classes keep working while sections migrate one at a time. A big-bang rename of ~1,000 classes would be unreviewable. |
| 2026-11-25 | **Phase 6: no Radix or lucide-react yet** | The in-house Dialog (focus trap, Escape, restore, safe focus) is ~100 tested lines; Radix isn't worth its bundle for that. lucide waits for the SVG pass. |
| 2026-11-25 | **Phase 6: Vitest + RTL + jsdom as dev dependencies** | The plan's smoke tests need a DOM runner; Vitest reuses the Vite config. Test-only, never shipped. |
| 2026-11-25 | `PROGRESS.md` replaces `Namma_Agent_Port.md` and `STAND_OUT.md` | One tracker; owner decision |
| 2026-11-25 | **Keep pywebview; decline a Tauri rewrite for now** | Same WebView2 renderer on Windows, so no memory win. A rewrite is ~3–6 weeks plus a Rust toolchain, sidecar lifecycle and update-signing pipeline; the pywebview gaps (tray, toasts, single-instance, hotkey, window state) are ~1–2 weeks in Python. Revisit if pywebview blocks a must-have. |
| 2026-11-25 | **Tool search, not fixed toolsets, is how tools scale**; profiles are user-facing presets | OpenAI hard-fails over 128 tools and accuracy drops past 30–50; Claude Code and Hermes defer tools behind search |
| 2026-11-25 | Hard 128-tool cap as a stopgap, dropping MCP tools first | Unblocks GitHub MCP on OpenAI today without a design change |
| 2026-11-25 | **Remote channels default-decline destructive tools** except `owner`; `trusted` needs `comms.trusted_can_run_destructive: true` | They have no approval round-trip; `approval=None` silently meant "allow everything" |
| 2026-11-25 | Auto mode applies only to interactive approval, never to an explicit decline-all | Unattended runs (routines, watchers, `/v1`) have nobody to ask |
| 2026-11-25 | Sub-agent step cap is 25 when the parent is unlimited | An unbounded hidden child can block the parent turn indefinitely |
| 2026-11-25 | Default `tool_result_max_chars: 24000` with spill-to-file; `tool_loop_limit: 40` | Context costs grow quadratically with uncapped results; matches Claude Code and Codex practice |
| 2026-11-25 | Inline visuals: fenced blocks for simple diagrams/charts plus a `render_visual` tool for interactive HTML, in sandboxed iframes | Mirrors Claude's inline-visual tool pattern and LibreChat/Open WebUI renderers; tool events give exact placement |
| 2026-11-25 | Multi-device sync is design-first | Breaks local-first; needs an owner decision |
| 2026-11-25 | **Adopt A2UI as the format for agent-generated interactive UI; validate with a Phase 4 spike first** | A2UI (Google, open source) is declarative JSON rendered by the *client's own* components: no agent-supplied code, so it is safer than HTML iframes and matches our design system. It has an official React renderer and streams incremental updates. Its interop with AG-UI (transport) and MCP Apps is documented. It fits setup mode (secret slot posts straight to the vault), clarify questions and approval cards. **Not** for diagrams (fenced mermaid/chart stay) or third-party server UIs (MCP Apps in sandboxed iframes). Risks: spec churn (0.9.1 vs 1.0), invalid JSON from small models, renderer bundle size. |
| 2026-11-25 | Same-chat turns are serialized on the server; Stop aborts in-flight model calls, tool batches and shell commands | Owner-reported BUG-19; concurrent same-session turns corrupted the cancel state and interleaved answers |
| 2026-11-25 | **Tool search is agent-side meta-tools (`tool_search`/`tool_describe`/`tool_call`)**, not provider-native deferral | Works the same on every provider and keeps one approval/audit path; Anthropic's native `defer_loading` is a later optimisation |
| 2026-11-25 | Lab and smart-home tools are availability-gated (`requires`), not left unregistered | They stay visible in the Toolsets tab with clear errors, and appear live when config enables them, at no prompt cost |
| 2026-11-25 | The date and memory prefetch ride the newest user message, not the system prompt | Keeps the system prompt + tools byte-identical per chat, so they're served from the prompt cache |
| 2026-11-25 | **One user config in the data dir (`data/user_config.yaml`) replaces `config.local.yaml`**; the base `config.yaml` is never rewritten | Owner decision. `config.yaml` is git-tracked and shipped by the installers/updater, so personal settings there would show in `git diff` and clash with updates. The data dir already holds the user's state (DB, vault) and survives updates and image rebuilds; no `ruamel.yaml` dependency |
| 2026-11-25 | **Delegation fan-out is capped per call (3 at once), with depth bounding the tree (orchestrator once, then leaves)**, rather than one global pool | A shared pool deadlocks when orchestrators hold slots while waiting on their children; per-call caps plus depth 2 bound the total at 1 + 3 + 9 |
| 2026-11-25 | Sub-agent runs are persisted in SQLite (`subagent_runs`); the JSON background store is imported once and retired | One store for delegate and background runs, queryable by chat for the UI, and interrupted runs are found at boot |
| 2026-11-25 | Process-wide `Broadcaster` for events that outlive a turn | A background run finishes after its turn's WebSocket sink is gone; every connected UI subscribes instead |
| 2026-11-25 | Settings secrets go to the vault; `.env` keeps non-secrets | The vault already existed; a stale `.env` copy is removed so it can't shadow the vault |
| 2026-07-29 | (carried) Phase-7 Hermes-gap work: SSRF guard, checkpoints, approval-gated memory writes, Docker/SSH shells, user tools + hooks, `/v1` | See history |

---

## 7. Migrated history (condensed)

Full detail, with per-item files and test counts, is in git history under
`Namma_Agent_Port.md` and `STAND_OUT.md` (removed 2026-11-25).

### Hermes-parity effort (`Namma_Agent_Port.md`) — complete
- **Phase 0, token/TTFT accuracy:** usage breakdown (input/output/cache read/write);
  Anthropic prefix caching; headline excludes cache reads; TTFT stamped at the provider
  boundary.
- **Phase 1, comms:** Slack, WhatsApp and Signal outbound; a platform-agnostic
  `InboundBridge`; Signal polling inbound; CLI gateway; Slack/WhatsApp webhooks; GUI
  gateway start/stop.
- **Phase 2, skills:** SKILL.md store, learning loop, Skills tab. Hermes-ported skills
  were deleted 2026-06-22 at the owner's request.
- **Phase 3, toolsets:** Toolsets tab, category toggles, tool port (image-gen and MoA
  declined).
- **Phase 4, chat transparency:** tool-call and thinking timeline, approval cards.
- **Phase 5:** procedural interaction sounds.
- **Phase 6:** Settings redesign + notifications.
- **Phase 7:** native installer and desktop app (pywebview), self-contained Windows
  runtime.
- **Phase 8, "better than Hermes":**
  - Wave 1: rolling context compaction, self-verification nudge, proactive routines.
  - Wave 2: background-work observability (`/api/status`), cumulative usage view,
    consolidation polish.
- **Phase 9, TUI + CLI (wave 1, 2026-07-29):** `namma_agent/tui/` (prompt_toolkit + rich),
  the `namma <command>` surface, skins, colour/unicode degradation, gateway split.
  Full suite: 1,130 passed.

### Stand-out effort (`STAND_OUT.md`)
- **Phase 1, trust as a product (2026-07-18/19):**
  - per-channel trust levels
  - injection screening of web tool output
  - Windows Job-Object and POSIX rlimit shell sandbox
  - secrets vault (Credential Manager, DPAPI, keyring) + redaction
  - Settings → Security tab
  - `docs/SECURITY.md`
- **Phase 2, watchers (2026-07-19):** file, email, web and calendar triggers with
  zero-LLM polling and an "only if it matters" gate.
- **Phase 3, measured self-improvement (2026-07-19):** weekly self-review that mines
  failures, corrections, retries and repeated workflows, with ≤5 proposals and owner
  accept/reject.
- **Phase 4, distribution (partial):** README overhaul, mkdocs site,
  `docs/BENCHMARKS.md` (recall@5 = 92%, mock mode).
- **Phase 5, Windows polish (2026-07-19/20):** tray, start-on-login, WSL awareness,
  Action-Center toasts with Reply/Open, sanitised shell PATH, self-contained installer.
- **Phase 6, deployability (2026-07-19):** headless hardening (bind, token auth,
  `NAMMA_DATA_DIR`), Docker image + compose, systemd unit, server-lite profile,
  VPS/Oracle guides.
- **Phase 7, last Hermes gaps (2026-07-29):** SSRF guard, checkpoints + rollback,
  approval-gated memory writes, Docker/SSH shell backends, user tools + lifecycle hooks,
  OpenAI-compatible `/v1`. Full suite: 1,171 passed, 3 skipped.

---

## 8. Open items carried over

From `Namma_Agent_Port.md`:
- [ ] Hermes gap-analysis pass for UI/backend features not yet captured (image-gen
  stays declined).
- [ ] TUI wave 2: inline approval/sudo/clarify panels, `/diff` from checkpoint
  snapshots, `/model` picker.
- [ ] A `clarify` tool (ask the user a structured question mid-turn).
- [ ] Verify the licences of bundled media (sounds, icons); MIT covers code only.

From `STAND_OUT.md`:
- [~] README: the 30-second GIF slot is still a placeholder (needs demo recordings).
- [ ] Enable GitHub Pages (branch `gh-pages`) in repo settings for the mkdocs site.
- [ ] Demo recordings: watcher → Telegram ping, injection quarantine, weekly learning
  report.
- [ ] GitHub release with the native installers, repo topics, launch posts.
- [ ] Track stars and issues as the distribution metric.
- [~] winget: PR microsoft/winget-pkgs#404868 passed validation and is awaiting
  moderator approval.
- [x] 1 GB server profile idle RSS, measured 2026-11-25 on the owner's E2.1.Micro
  (x86-64, 2 vCPU, 956 MB RAM, version 2.3.2, up 3 days):
  - The agent process peaked at 124 MB resident (`VmHWM`). It is now 27 MB
    resident plus 106 MB in swap.
  - The GitHub MCP container uses 29 MB.
  - The host is at 282 MB used of 956 MB, with a load average of 0.01.
  - Read-only inspection over SSH; nothing on the box was changed.
- [x] CI Docker-image smoke test: verified 2026-11-25. `.github/workflows/ci.yml` has
  a `docker` job (build, health check under a 900 MB cap, auth-token run).
- [!] Local Docker build blocked by the Windows AF_UNIX bug (reboot pending), so there
  is no live in-container run of the Docker shell backend yet.
- [ ] Feed the memory-approval accept/reject ratio into the weekly self-review
  snapshot (once real data exists).
- [ ] Context-file discovery (`AGENTS.md` / `CLAUDE.md` / `.namma.md` from the working
  directory).
- [ ] Credential pools (multi-key rotation per provider).

---

## 9. Declined

- [✗] **God Mode / jailbreak skills.** Permanently declined; the anti-position is the brand.
- [✗] **Channel-count race** (iMessage, WeChat, 29 channels). Each channel is attack
  surface; the current five plus CLI cover the owner.
- [✗] **Hosted image-gen / TTS gateway.** A subscription-infrastructure play.
- [✗] **Mixture-of-agents.** A cost multiplier with no differentiation.
- [✗] **Tauri / Electron rewrite** (for now). See the decision log.
- [x] **Skills/plugin marketplace** (previously declined). Shipped in Phase 5
  (2026-11-25) as a curated catalogue plus install-from-URL: previewed, installs
  disabled, not an open ecosystem.

---

## 10. Change log

- **2026-11-26 (Phase 10 — memory graph and its primitives):**
  - Audit on a seeded scratch instance: 21 entities all typed `thing`, the user split into 4 nodes, literals and clauses as nodes, duplicate synonym edges; Schema had one type and zero edges; Ranked was raw degree.
  - New `core/engram/graph.py`: typed entities with aliases/attributes, canonical directed relations with sources, confidence and supersession, derived schema, PageRank/salience/recency ranking, rebuild-from-facts migration; `/api/memory/graph/*` endpoints.
  - Memory page redesigned: deterministic typed graph with labelled directed edges, focus + entity panel with source facts, working Schema and Ranked tabs, merge/rename.
  - Python 1,475 passed / 3 skipped; web UI 66 passed.
- **2026-11-26 (Phase 9 W1, slice 4):**
  - The chat background is painted, crumpled paper built from the owner's Desktop art. It follows the theme, light/dark and the mode. The slice-3 painting is removed.
  - Settings split into 22 modules; Providers + Models → **Model**, Config + Servers → **MCP**; the old links still work.
  - Onboarding wizard on the W2 contract (with fallbacks), reused in Settings → Model. Right pane Files + Preview. Sidebar profile rail.
  - Tabler icons across the shell; Imperium theme (Cinzel headings, laurel); `dark:` 814 → 95.
  - Web UI 51 passed; Python 1,437 passed / 3 skipped.
- **2026-11-26 (Phase 9 W1, slice 3):**
  - The chat background is the owner's ink-wash painting (cover fit), with a theme-coloured veil down the reading column and dimming in dark themes. It replaces the hands mask and corner paint blocks.
  - Web UI 38 passed; Python suite not affected (no backend change).
- **2026-11-26 (Phase 9 W1, slice 2):**
  - Hermes-style titlebar band: per-panel 34px headers plus fixed tool clusters; no search row.
  - Chat header speaker toggle removed. Composer placeholders fit on one line with no scrollbar; headset button removed.
  - OS-native read-aloud (SAPI / `say` / espeak-ng) and Windows SAPI dictation, with a Voice settings section.
  - Side panel becomes a drawer below 1024px.
  - Python 1,437 passed / 3 skipped; web UI 34 passed.
- **2026-11-25 (Phase 9 W1, slice 1):**
  - Modes are picked from a list (with Roman roles), and the model picker is an overlay instead of a header `<select>`.
  - Settings save themselves (no Save buttons; rollback + Retry on failure).
  - Hermes shell skeleton: titlebar, status bar, right pane; the composer is always stacked.
  - `/api/config` reports `default_mode`.
  - Python 1,424 passed / 3 skipped; web UI 29 passed.
- **2026-11-25 (Phase 6, round 1 — UI/UX system):**
  - Semantic tokens and a named type scale. Every `text-[Npx]` and hex literal
    is gone from components; subtle text meets 4.5:1; the theme follows the OS.
  - `ui/` primitives (Dialog, ConfirmDialog, Button, IconButton, Toast,
    CommandPalette, …). Every modal uses Dialog; BUG-12 fixed; 49 `aria-label`s.
  - Settings deep links (`/settings/<section>`) with search; Ctrl+K palette;
    Escape stops a turn.
  - Memoised transcript, 50 ms token batching, core bundle 1,183 → 315 KB.
  - Vitest + RTL: 18 tests. Python suite unchanged: 1,420 passed, 3 skipped.
- **2026-11-25 (Phase 5 — MCP & setup experience):**
  - MCP: validation, import, URL install, detection, an 11-preset catalogue
    with GitHub toolsets and read-only, a Streamable-HTTP transport, and
    background connects with live status.
  - Setup mode: providers, models, MCP, Google `gws`, IMAP/SMTP mail and
    messaging, with secure secret cards, a paste guard, and real verification
    with diagnosis.
  - First-run provider onboarding; the skills marketplace (preview, installs
    disabled).
  - Fixed three data-dir/vault isolation bugs and cleaned up what they leaked.
  - **Full suite: 1,420 passed, 3 skipped. ruff clean.** Web UI rebuilt.

- **2026-11-25 (Phase 4b, fresh start + live hunt on gpt-5.6-terra):**
  - Owner-approved wipe of all data; keys and models kept. Default model is now
    `gpt-5.6-terra`.
  - Skills revamp: 7 new bundled skills, `deep-research` v2.1 with per-task
    budgets, the stale Office-CLI folder removed, all tool references audited.
  - Live fixes:
    - follow-up turns see an `[actions: …]` record of the tools earlier turns ran;
    - `convert_document` writes xlsx and csv;
    - no refusing for a "tool not loaded";
    - `sandbox:` links fixed;
    - `update_todos` round trips cut;
    - file, checkpoint and skill tools are core;
    - sub-agent reports structured;
    - choices go to `show_ui`.
  - **Isolation bug (found after the wipe, fixed):**
    - Reminders were pinned to `<repo>/data/reminders.json` and ignored
      `NAMMA_DATA_DIR`, so the probe's reminders landed in the owner's real app,
      where they would have fired. They now live in `data_dir()`.
    - The test suite wrote tool outputs and diagrams into the real `data/`, and
      created a WhatsApp session file in `~/.namma_agent`. `conftest.py` now
      gives the suite its own data dir at import time.
      `NAMMA_WHATSAPP_SESSION` overrides the session file location.
    - The leaked files were removed. A full suite run now leaves `data/` (keys
      and settings only) and `~/.namma_agent` (empty) untouched.
  - Tests: `test_followup_and_sheets.py` (6). **Full suite: 1,366 passed, 3
    skipped. ruff clean.** Web UI rebuilt. About 871K live tokens.

- **2026-11-25 (Phase 4 fix + Phase 4b):** live bug hunt on gpt-4.1-mini.
  - Fixed: regenerate (verified in the browser); delegation and everyday action
    tools always loaded; honesty, resourcefulness, sub-agent and table rules;
    the chart vs Mermaid routing; the client-side Mermaid fallback for
    `render_diagram`; sectioned visual explanations.
  - Added `/skill` commands and the Toolsets tab clarity fixes.
  - Rewrote the `deep-research` and `creating-visuals` skills.
  - Added Phase 4b and the skills marketplace (Phase 5).
  - **Full suite: 1,360 passed, 3 skipped. ruff clean.** About 776K live tokens.

- **2026-11-25 (Phase 4, in progress):** event protocol v2 (seq, ring, resume),
  parallel read-only tools, inline mermaid/chart/sandboxed visuals, message
  actions, in-session model switch, step inspector and plan card, notices,
  Stopping/Queued states, and the A2UI spike with the official renderer. New
  npm dependencies (owner-approved): mermaid 12.3.0, @a2ui/react 0.16.1,
  @a2ui/web_core 0.16.1, zod 3.25.76. **Full suite: 1,355 passed, 3 skipped.
  ruff clean.**

- **2026-11-25 (Phase 2):** token efficiency, self-awareness, part of config truth.
  - Added the per-request usage log with background-call attribution and the
    per-turn token budget.
  - Added tool search (core tools plus `tool_search`/`tool_describe`/`tool_call`)
    and toolset profiles. Lab and Home Assistant tools are hidden until they're
    set up.
  - Made the prompt cache-stable (date and prefetch moved into a `<context>`
    block; OpenAI `prompt_cache_key`).
  - Added two-phase in-turn compaction.
  - Self-knowledge is now generated live, with an "ABOUT YOU" block in the prompt.
    The app can edit its own install dir, and `..` paths are allowed (checked
    after resolution).
  - Settings secrets go to the vault. The overlay and `.env` live in
    `$NAMMA_DATA_DIR` when it's set (BUG-11 persistence).
  - Model profiles honour `provider.fallback`. Removed Cognee leftovers and dead
    code.
  - New tests: `test_usage_log.py`, `test_tool_search.py`, `test_context_budget.py`,
    `test_self_knowledge_config.py`. Updated tests that asserted the removed
    behaviour (Cognee fallbacks, minute-stamped date, `..` rejection,
    `is_destructive`).
  - **Full suite: 1,285 passed, 3 skipped. ruff clean.**
  - Checked live against the running server: the Toolsets tab shows the profiles,
    the tool-search mode and the "hidden — needs …" badges; the Status tab shows
    the new per-call section. Not exercised live: a real model turn (so no
    measured cache-read ratio or token counts yet).
  - Blocked: retiring `config.local.yaml` needs an owner decision (see Phase 2).
- **2026-11-25 (Phase 3):** delegation runtime.
  - `core/delegation.py` (`DelegationManager`): goal/context/tasks[] fan-out,
    leaf/orchestrator roles, concurrency cap 3, depth cap 2, cancellation tree,
    the `{status, summary, exit_reason, truncated}` contract, persisted runs
    (`subagent_runs`), `subagent` events through a process-wide broadcaster, and
    a bounded background pool that reports back into the chat.
  - New `cancel_background_task` tool, `/api/runs` endpoints and the Sub-agents
    panel in the chat. `AgentResult.exit_reason` added.
  - Eval harness: `scripts/delegation_eval.py` (`--mock` 20/20).
  - VPS: measured the idle RSS of the 1 GB server profile on the owner's
    E2.1.Micro (read-only).
  - **Full suite: 1,311 passed, 3 skipped. ruff clean** (incl. `scripts/`).
  - Verified in the browser against a scripted-brain server: 3 parallel
    children, per-run Cancel, and Stop cancelling the rest.
  - Live eval, run later the same day with the owner's OpenAI key and model
    choice (gpt-4.1-mini, data-sharing allowance): 20/20 (100%), 36,275 tokens.
    The runner gained a hard `--max-tokens` cap and an `--openai-model` flag.
    Full suite: 1,312 passed, 3 skipped.
- **2026-11-25 (Phase 2, config truth):** owner chose one user config in the data dir.
  - Settings edits go to `data/user_config.yaml` (or `$NAMMA_DATA_DIR/`). The
    legacy `config.local.yaml` is migrated once and renamed `*.migrated`.
  - Docker and `install.sh` seed the user config from the server-lite profile.
    Docs and comments updated.
  - Test isolation: `tests/conftest.py` points every test at a temporary user config.
  - **Full suite: 1,290 passed, 3 skipped. ruff clean.** The owner's real
    `config.local.yaml` was untouched by the suite; it migrates on the next launch.

- **2026-11-25:** Product audit (graphify plus three code audits and four research
  tracks).
  - Created `PROGRESS.md`; retired `Namma_Agent_Port.md` and `STAND_OUT.md`.
  - Removed academic, hackathon, presentation and Cognee material.
  - Untracked `data/checkpoints/`.
  - Landed Phase 1 critical fixes BUG-01…BUG-05 and BUG-07…BUG-09, with BUG-06
    stopgapped. Added 4 test files plus 5 delegation tests and fixed 3 pre-existing
    unused-import lint errors.
  - Fixed the owner-reported Stop bug (BUG-19). A turn's Stop check is restored
    on exit, so it can't leak into later shell commands on the same thread.
  - Recorded the A2UI adoption decision and spike.
  - **Full suite: 1,231 passed, 3 skipped. ruff clean.**
  - Live smoke: the server boots and the UI loads with no console errors.
    `/api/desktop/focus`, the upload cap and env-injection rejection were checked
    against the running server. A second `--server` launch exits in 3 s without
    building a service.
  - Not exercised live: a real model turn and Stop in the desktop window (covered
    by unit and WebSocket tests).
