# About {name} (self-knowledge)

This is {name}'s reference about itself — how it's built and configured. The
**live** sections (version, paths, configured models, MCP servers, toolsets) are
generated from the running configuration by `about_namma`; the sections below
describe how each subsystem works.

## What {name} is
A cloud-LLM personal assistant in the `namma_agent/` Python package: one
provider-agnostic agent loop, a tool registry, a skill system (procedural memory),
Engram (native long-term memory), browser-native voice (Web Speech API — read-aloud
and mic dictation, no server audio), a React web UI, a desktop window
(pywebview), and messaging bridges. The display name comes from `assistant.name`
in the config.

## Configuration
- The documented base config is `namma_agent/config.yaml` (defaults, never
  rewritten). Everything changed in Settings, the setup wizard or
  `namma config set` goes to ONE user config, `user_config.yaml` in the data
  folder (path in the live **Paths** section), merged on top of the base. An old
  `config.local.yaml` is migrated into it once and renamed `*.migrated`.
- API keys live in the secrets vault (Settings → Security) or `.env`; `.env`
  values are loaded at startup. Never print a key's value.
- Provider, model, persona and agent-loop changes made in Settings apply live on
  the next turn — no restart needed.

## Modes
- **Agent mode** — tools and skills (files, shell, web, apps, memory, …).
- **Chat mode** — pure conversation: no tools, no skills, no actions.

## Models and providers
`providers:` lists named connections (type, base_url, api_key_env); `models:`
lists switchable model profiles that reference a provider. Each chat can pick a
model. Supported types: `anthropic`, `openai`, `google`, and OpenAI-compatible
endpoints (`opencode`, `lmstudio`, `ollama`, custom `base_url`). `provider:` is
the legacy default with an optional `fallback:` chain, which also applies to
model profiles.

## Tools and tool search
Tools are grouped into toolsets (Settings → Toolsets). When more tools are enabled
than `tools.search.threshold`, only the core tools are sent with each request; the
others are found with `tool_search` and run with `tool_call` (same approval
rules). `tools.profile` picks a preset (general, productivity, code, research,
minimal). Destructive tools always ask for approval unless Auto mode is on.

## Delegation (sub-agents)
`delegate_task` hands self-contained work to sub-agents: a `goal` plus the
`context` they need (they can't see the chat), or `tasks[]` to fan out — up to
3 run in parallel. `role: orchestrator` lets a child split its work once more;
those children are leaves. Each child returns status, summary, exit_reason and
truncated. `toolsets`, `skills` and `budget` (max_steps, max_tokens) shape a
child; destructive tools are never available to it. `background_task` runs one
sub-agent without blocking and posts its report into the chat when done;
`check_background_task` / `cancel_background_task` manage it. Runs show above
the message bar, where they can be cancelled (cancelling a run cancels its
children; Stop on the turn cancels everything it started).

## Skills (procedural memory)
SKILL.md playbooks under `namma_agent/skills/` (bundled) and
`~/.namma_agent/skills/` (learned). `use_skill` loads one; `create_skill` /
`update_skill` author them. Repeated tool workflows are drafted as disabled skills
for review.

## Memory (Engram)
Core memory (always in the prompt), bi-temporal facts and an entity graph in
SQLite, fused recall (`memory_search`), `memory_save`, `memory_forget`, a
salience-gated background writer, and sleep-time consolidation. Chat transcripts
are searchable with `search_conversations` / `recall_sessions`. Manage it in
Settings → Memory.

## MCP servers
Configured under `mcp.servers` in the config file (each: `name`, `command`,
optional `env`, `enabled`). Their tools register as `mcp_<server>_<tool>`.
Toggle servers in Settings → Toolsets → MCP.

## Browser and media
A visible, Playwright-driven browser with a persistent profile;
`open_browser_url`, `play_youtube`, `play_youtube_music`, `media_control`.

## Messaging
Telegram, Discord, Slack, WhatsApp and Signal bridges (`comms:` config, tokens in
the vault or `.env`). Each channel has a trust level; remote channels can't run
destructive tools unless the sender is the owner.

## Background work
Routines (scheduled agent runs), watchers (file/email/web/calendar triggers),
the weekly self-review, reminders and memory consolidation. Settings → Status
shows what is running and the token usage of every model call.

## Logging
`logging.level` (or `NAMMA_LOG_LEVEL`) = debug|info|warning|error. Logs go to the
terminal and `logs/namma_agent.log` (rotating).
