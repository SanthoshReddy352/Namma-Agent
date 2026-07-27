# Why Namma?

There are plenty of personal AI agents. Hermes has a $1.5B company behind it
and a hosted tool gateway. OpenClaw went viral with 100+ community skills and
29 messaging channels. Namma will not out-feature them, and doesn't try.
Instead it holds four positions the feature race leaves open.

## 1. Trust is the product, not a settings page

The personal-agent category has a public trust problem: prompt-injection
exfiltration CVEs, hijacked always-on agents, and Microsoft's blunt guidance
to treat agents as *untrusted code execution with persistent credentials*. An
agent that reads your email, runs shell commands, and remembers everything is
exactly the thing those warnings are about.

Namma's answer is a layered trust model that is **on by default** and
**visible in the UI** (Settings → System → Security):

- **Per-channel sender trust** — a stranger in a Slack workspace is not you.
  Untrusted senders get destructive tools stripped, their text treated as
  data-not-instructions, and their would-be memory writes quarantined.
- **Injection screening** on everything the agent reads: uploads, web pages,
  search snippets, RSS. Flagged content is wrapped and marked, never silently
  dropped.
- **Approval-gated destructive tools**, with declines audit-logged — the
  trail shows what was *asked*, not just what ran. Autonomous runs (routines,
  watchers, sub-agents) decline destructive tools unconditionally.
- **A sandboxed shell** — Windows Job Objects (memory cap, fork-bomb guard,
  kill-on-close) or POSIX rlimits.
- **A secrets vault** (Windows Credential Manager / keyring / DPAPI-sealed
  file) with secret values redacted from every tool result and log line.

The whole model — including an explicit *"what Namma does NOT claim"*
section — is published in [SECURITY.md](SECURITY.md). Every claim in that
document is observable live in the Security tab.

## 2. Memory you can measure

Every agent says it remembers you. Namma publishes a number: a reproducible
recall benchmark (`python scripts/memory_eval.py --mock`, offline, no API
key) currently at **recall@5 = 92%**, re-run weekly with the score trended
over time. Methodology, results, and limitations — including the honest ones —
are in [BENCHMARKS.md](BENCHMARKS.md).

The memory itself ([Engram](MEMORY_SYSTEM_DESIGN.md)) is native and
in-process: bounded core memory in every prompt, bi-temporal facts + an
entity graph in SQLite, millisecond fused recall, salience-gated always-on
learning, and a sleep-time consolidation cycle. No Docker, no vector-DB
service, no memory container to babysit.

## 3. Always-on means event-driven

Most agents act when you speak to them, or on a clock. Namma's **watchers**
act when the *world* changes: a file lands in a folder, an email matches a
query, a page's content shifts, a meeting approaches. Polls are cheap and
zero-LLM; a single "only if it matters" model pass filters noise against your
stated intent; delivery reaches you on your phone over your messaging channel.
And because the trust model came first, watcher runs can't execute destructive
tools — proactivity without handing the keys to a background process.

## 4. First-class on Windows

OpenClaw leans macOS; Hermes leans Linux/macOS. Namma is built *on* Windows
as a primary target: Job-Object sandboxing, Credential Manager secrets,
DPAPI-sealed fallbacks, PowerShell-aware tooling, one-click installers — with
Linux and macOS fully supported alongside.

## What Namma deliberately doesn't chase

- **A skills marketplace** — network-effects games favor incumbents. Namma's
  answer is the weekly self-review that *drafts personal skills from your own
  usage evidence* (you approve each one).
- **A channel-count race** — five channels + CLI cover an owner-user; every
  additional channel is attack surface.
- **Jailbreak-style "god mode" skills** — permanently declined. The
  anti-position is the brand.

## The one-sentence version

> **The trustworthy personal agent that measurably knows you — first-class
> on Windows.**

If you want the biggest ecosystem, pick Hermes. If you want the most
channels, pick OpenClaw. If you want an always-on agent you can *audit* and a
memory claim you can *verify*, run Namma.
