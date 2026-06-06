# FRIDAY v2 Migration — Status Tracker

> **This is the live progress ledger for the cloud-only rebuild.** It is the single
> authority on what is done, in progress, and pending. Every task of every phase is
> listed here. The canonical plan ("god document") is
> [`FRIDAY_V2_GOD_DOC.md`](./FRIDAY_V2_GOD_DOC.md).

**Last updated:** 2026-06-06

## Legend

- `[ ]` TODO — not started
- `[~]` IN-PROGRESS — actively being worked
- `[x]` DONE — completed and verified

## Progress summary

| Phase | Title | Status |
|------|-------|--------|
| 0 | Safety net & docs | `[x]` DONE |
| 1 | Provider layer | `[~]` IN-PROGRESS |
| 2 | Agent core | `[ ]` TODO |
| 3 | Model-narrated progress | `[ ]` TODO |
| 4 | Backend server | `[ ]` TODO |
| 5 | Modern GUI | `[ ]` TODO |
| 6 | Voice (Piper TTS + STT) | `[ ]` TODO |
| 7 | Module porting waves | `[ ]` TODO |
| 8 | Purge legacy | `[ ]` TODO |
| 9 | Finalize | `[ ]` TODO |

---

## Phase 0 — Safety net & docs
- [x] Create god doc (`FRIDAY_V2_GOD_DOC.md`)
- [x] Create this status tracker (`STATUS_V2.md`)
- [x] Add "ACTIVE MIGRATION (v2)" pointer to `CLAUDE.md`
- [x] `git init`, `.gitignore` sanity (added piper tarball), initial commit
- [x] Baseline tag `v1-pre-rebuild`
- [x] Record baseline metrics (see below)

**Baseline metrics (v1, 2026-06-06):**
| Metric | Value |
|--------|-------|
| Python files | 478 |
| Python lines | 101,937 |
| `core/` files | 146 |
| Modules | 27 |
| Test files | 168 |
| `intent_recognizer.py` | 3,564 lines |
| `router.py` | 1,113 lines |
| `app.py` | 1,187 lines |
| Python runtime | 3.13.12 |
| Git tracked files | 687 |
| Rollback point | tag `v1-pre-rebuild` |

## Phase 1 — Provider layer
- [ ] `friday/core/providers/base.py` (Provider ABC + `LLMResponse`)
- [ ] `openai_provider.py` (native OpenAI, tools + streaming)
- [ ] `anthropic_provider.py` (native `tool_use` + prompt caching + streaming)
- [ ] `google_provider.py` (Gemini function-calling)
- [ ] `openai_compat.py` (opencode / lmstudio / ollama / custom base_url)
- [ ] `registry.py` (config-driven selection + fallback chain)
- [ ] `config.yaml` provider section + `.env.example` keys
- [ ] `friday/tests/test_providers.py`

## Phase 2 — Agent core
- [ ] `friday/core/tools.py` ToolRegistry (native defs from capability descriptors)
- [ ] `friday/core/memory.py` single SQLite (sessions/turns/facts FTS5/audit)
- [ ] `friday/core/persona.py` (port persona_manager YAML→prompt)
- [ ] `friday/core/agent.py` the one loop (generate→tools→loop→final, streaming)
- [ ] `remember_fact` / `recall_facts` tools
- [ ] `friday/tests/test_agent_loop.py`
- [ ] `friday/tests/test_memory.py`

## Phase 3 — Model-narrated progress
- [ ] `friday/core/events.py` (port event bus)
- [ ] `friday/core/narration.py`: spoken preamble alongside tool calls
- [ ] Context-aware long-task progress lines (timer pattern, real context)
- [ ] Tool-step narration on `tool_finished`
- [ ] `friday/tests/test_narration.py`

## Phase 4 — Backend server
- [ ] `friday/server/api.py` FastAPI app + REST (config/persona/tools)
- [ ] WebSocket event protocol (token/tool/progress/approval/turn_completed)
- [ ] Approval round-trip over socket
- [ ] `friday/tests/test_server.py`

## Phase 5 — Modern GUI
- [ ] `friday/webui/` Vite + React + Tailwind scaffold
- [ ] Streaming chat transcript
- [ ] Tool/progress timeline component
- [ ] Voice orb / push-to-talk control
- [ ] Settings (provider+model picker, persona, key status)
- [ ] Dark modern theme
- [ ] `friday/app.py` pywebview native window + serve `webui/dist`

## Phase 6 — Voice
- [ ] `friday/voice/tts.py` Piper (port, output + narration)
- [ ] `friday/voice/stt.py` local push-to-talk (port, slimmed)
- [ ] Barge-in via interrupt bus

## Phase 7 — Module porting waves
*(each module: convert params to JSON Schema, drop intent regex, add focused test)*
- [ ] Wave 1: file_ops, code_exec/shell, system_control, app_launcher
- [ ] Wave 2: web, browser_automation, security_tools, network
- [ ] Wave 3: smart_home, document_intel, vision/image, scheduler, weather, news
- [ ] Wave 4: memory, delegate_task, persona switch

## Phase 8 — Purge legacy
- [ ] Delete intent_recognizer, planning/, routing layers, MoA, task_graph_executor, workflow_orchestrator
- [ ] Delete stores/, memory/, memory_service, session_rag, reasoning/, delegate/delegation
- [ ] Delete old llm_providers, gui/ (PyQt), cli/, main.py, local GGUF + kokoro*
- [ ] Prune/rewrite tests/

## Phase 9 — Finalize
- [ ] Rewrite README, SETUP_GUIDE*, requirements.txt, setup.sh/ps1, config.yaml, .env.example
- [ ] Rewrite CLAUDE.md (remove intent-recognizer rules; remove migration pointer)
- [ ] Rewrite docs/testing_guide.md for v2
- [ ] Full green test suite + end-to-end launch verification

---

## Change log
- 2026-06-06 — Migration kicked off. God doc + status tracker created.
- 2026-06-06 — Phase 0 complete: git initialized, baseline tag `v1-pre-rebuild`, CLAUDE.md migration pointer added, baseline metrics recorded. Starting Phase 1 (provider layer).
