# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [2.2.3] — Namma Agent Installer

### Changed
- **Installer Updated for Better User Experience**  
- **Used Pywebview2 + React for the Installer UI**  

## [2.2.2] — Namma Agent Build/Release

### Changed
- **Fixed GitHub CI & Release Workflows for Namma Agent**  
- **Fixed Bundling Issues**  

## [2.2.1] — Namma Agent GitHub Workflow

### Changed
- **Fixed GitHub CI & Release Workflows for Namma Agent**  

## [2.2.0] — Renamed to Namma Agent

### Changed
- **Project renamed to Namma Agent** — *Intelligence for Everyone. Your Trusted
  AI Companion. Your Agent, Your Advantage.* A full rename, not just docs:
  - **Package:** the `friday/` package is now `namma_agent/`; run it with
    `python -m namma_agent`. All imports (`from namma_agent…`), the
    `NammaAgentService` class, the `useNammaAgent` web hook, and the `about_namma`
    / `exit_namma` tools were renamed accordingly.
  - **Environment variables:** `FRIDAY_*` → `NAMMA_*` (`NAMMA_API_KEY`,
    `NAMMA_TELEGRAM_TOKEN`, `NAMMA_CONFIG`, `NAMMA_LOG_LEVEL`, …). `ASSISTANT_NAME`
    is unchanged. **Existing `.env` files must migrate their keys.**
  - **Data paths:** `data/friday.db` → `data/namma_agent.db`, `logs/friday.log` →
    `logs/namma_agent.log`, `~/.friday/` → `~/.namma_agent/` (skills, tools,
    personas, browser profile). **Existing databases/profiles must be moved or are
    recreated fresh.**
  - **Default assistant name:** the configurable display name now defaults to
    *Namma Agent* (was *FRIDAY*); set `assistant.name` / `ASSISTANT_NAME` to call
    the assistant anything you like — the mechanism is unchanged.
  - **Docs:** the README and `docs/` set were rewritten under the new name, and
    [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) was redesigned to document the
    current codebase — Projects (FTS5/BM25 RAG + injection screening), the Learning
    Room (scoped teacher agent, conversational assessment, confidence gate),
    deterministic memory auto-capture, shareable packs, and document conversion —
    with ten new architectural-decision entries.

## [2.1.0] — Project knowledge bases + Learning Room v2

### Added
- **Project documents (multi-document RAG)** — upload up to 25 files (10 MB
  each) per project. Each file is text-extracted, screened for prompt injection
  (`core/docscan.py`), chunked structure-aware with overlap, and indexed into
  SQLite FTS5 (`core/docindex.py`). The agent grounds project chats via
  `search_project_documents` (BM25 ranking, per-document diversity, neighbour
  stitching, file/section citations) with a data-not-instructions guard around
  every excerpt. Flagged files are quarantined out of retrieval until the user
  explicitly trusts them (Documents panel in the project view).
- **Cross-session project continuity** — a project chat's system prompt now
  carries summaries of the project's earlier conversations (auto-summarized
  when a new project chat opens) plus a `search_project_history` tool, so a
  session days later picks up where the last one left off.
- **Learning Room: path chat** — each topic's overview thread is now a
  dedicated "Path chat" (button on the dashboard): ask about the path, reshape
  it, and set **standing teaching preferences** (`set_teaching_preference`,
  e.g. "research every answer") that apply in every module from then on.
- **Learning Room: React Flow path view** — a Claude-style List/Flow toggle on
  the topic dashboard; the Flow view renders the path as generous module cards
  on a pannable, zoomable infinite canvas (status colors, minimap, click to
  open a module).
- **Syllabus → path** — upload a school/college syllabus (PDF/DOCX/…) in the
  "New topic" modal; Namma Agent screens it (injection or non-syllabus content is
  flagged, nothing is built), verifies it is a syllabus, infers the learner's
  level automatically, and builds the module path from it.
- **Learning Telegram nudges** — module-completion progress pings
  (`learning.notify_progress`) and "it's been a while" reminders for idle
  topics (`learning.nudge_after_days`, riding the opt-in
  `scheduler.run_in_background` switch).

### Fixed
- **Path chat opened as a blank "new chat"** — the overview session is now
  seeded with a path-chat welcome (new `POST /api/learning/{id}/session`), and
  its breadcrumb shows `Learning Room / Topic / Path chat` with the back arrow
  landing on the topic dashboard.
- **Quiz checks drifted into plain text** — the teaching contract now mandates
  `pose_quiz` for every comprehension check (plain-text checks aren't tracked
  and don't count) and at least one visual per concept, not just the first.
- **Module completion was unreliable / chats mixed** — completion now goes
  through an explicit confidence gate ("do you feel confident about this
  module?"): yes → the teacher MUST call `mark_module_complete`; no → it probes
  the shaky ideas and re-teaches. Completion drops a "Module complete →
  Continue to <next module>" card into the chat (opens the next module's own
  thread), and a finished module's chat becomes review-only — it refuses to
  teach new content and redirects to the next module, so lessons never bleed
  between module threads.
- **Path state-awareness** — quizzes and completions are attributed to the
  module whose *thread* they happen in (not the global "current" pointer), and
  jumping ahead to a not-yet-reached module asks for confirmation first.

- **Broken inline images ("Not Found")** — `render_diagram` retries transient
  mermaid-cli failures and rescues `-1`-suffixed output files; the contract and
  tool errors forbid the model from fabricating `/api/media/…` links; dead
  links degrade to an "image — unavailable" chip instead of a broken icon.
- **Turns ending on a dangling "Check:"** — announcing a check now obligates a
  `pose_quiz` call in the same turn.
- **Genuine syllabi flagged on upload** — scanner false positives fixed
  ("you are now …" needs persona-changing language; hidden-unicode threshold
  raised above normal PDF-extraction noise) and the syllabus analysis retries
  once with an explicitly generous is-it-a-syllabus rule.

- **Quiz cards vanished on chat reopen** — posed quizzes are now persisted as
  `quiz` turns (kept out of the model's message history) and restored in place
  — after the assistant message that posed them, already answered with the
  learner's pick — when the chat is reopened.
- **Dashboard quiz history is now clickable** — each check expands to the full
  question: every option (correct one ticked, a wrong pick marked) plus the
  explanation; the full quiz payload is stored with each result.

- **"Could not parse the syllabus analysis"** — the analysis JSON now parses
  even when the model wraps it in prose or code fences (balanced-object
  extraction, string-aware); verified end-to-end against the real failing PDF.
  Upload failures are no longer mislabelled "Document flagged" — only actual
  security flags say that; transient errors say "try again". Syllabus warnings
  are capped to a short readable note.
- **Polish & optimization** — auto-sent "[build path]" prompts are hidden when
  reopening the path chat; persisted quiz turns are excluded from conversation
  search (no JSON noise in recall); topic resolution is skipped for non-learning
  chats on session open; React Flow is code-split and loads only when the Flow
  view is opened (main bundle 806→627 kB).

### Changed
- **Quizzes no longer dead-end** — answering a quiz hands the result back to
  the teacher, which must keep the lesson moving: next in-module step, or
  module completion (with celebration) when everything is covered.
- **Teaching contract** — research-backed pedagogy: recall warm-ups (spaced
  retrieval practice), one running example continued across modules (module
  recaps persist via `mark_module_complete(recap=…)`), Socratic hints before
  answers, early-exit when the learner's goal is met, and a hard curriculum
  boundary: content reserved for later modules is never taught or teased early.

## [2.0.0] — Cloud-only rebuild

Namma Agent (then named FRIDAY) was rebuilt from the ground up as a **cloud-only**
assistant. The entire
application now lives in the `namma_agent/` package; the legacy local-model /
intent-recognizer / PyQt stack was removed.

### Added
- **Provider-agnostic brain** — native Anthropic, OpenAI, and Google providers
  plus a generic OpenAI-compatible client (Ollama, LM Studio, opencode, custom
  base URL), with a config-driven fallback chain.
- **One agent loop** — generate → call tools → loop → final answer, with token
  streaming, native tool calling, and a bounded/cancellable turn.
- **Tool registry** — ~55 auto-discovered tools across files, shell/system, web,
  browser, network, security, weather/news, smart home, vision, documents,
  scheduler, memory, tasks/goals, focus, skills, comms, workspace, and MCP.
- **Cross-session memory** — single SQLite store (sessions/turns/facts with FTS5),
  curated `USER.md` / `MEMORY.md` notes, and session summaries.
- **Skill system** — `SKILL.md` procedural memory with a learning loop
  (`create_skill` / `update_skill`).
- **Voice** — local Piper TTS (spoken answers + narration) and push-to-talk STT,
  both degrading gracefully without audio hardware.
- **Web UI** — React + Tailwind chat with a live tool/progress timeline, mode
  switch (chat/agent), stop button, attachments, and a settings panel.
- **Messaging bridges** — Telegram (inbound + outbound) and Discord; MCP client.
- **Configurable assistant name** — `assistant.name` in `namma_agent/config.yaml`
  (or the `ASSISTANT_NAME` env var) renames the assistant everywhere from one place.

### Removed
- The entire legacy v1 tree: intent recognizer, planning/routing layers, the
  domain stores, the local GGUF/llama stack, kokoro, the PyQt GUI, the terminal
  CLI, and the old Next.js docs site.
- The legacy root scaffolding (`config.yaml`, `requirements.txt`, `setup.sh/ps1`,
  `SETUP_GUIDE*.md`, `STATUS.md`) and the `docs/` planning archive. Setup and run
  instructions now live in the [README](README.md).
