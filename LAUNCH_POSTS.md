# Launch posts (Phase 4 — "Ship it")

> Drafts for the three announcement channels, anchored on the security angle.
> Post AFTER the GitHub release exists and the docs site is live, so every link
> resolves. Fill in the `<GIF/demo>` slots once the Phase 4 recordings exist —
> HN tolerates no-media, Reddit and X perform much better with a clip.
> Every claim below is verifiable in the repo (SECURITY.md, BENCHMARKS.md,
> the Security tab, the test suite) — keep it that way when editing.

---

## 1 · Show HN

**Title (≤80 chars):**

> Show HN: Namma Agent – a personal AI agent that treats security as the product

**Body:**

I've been building a self-hosted personal agent (shell, files, email/calendar,
browser, messaging bridges — any cloud brain: Anthropic/OpenAI/Google or any
OpenAI-compatible endpoint). The interesting part isn't the feature list —
every agent has one now. It's that the category has a trust problem
(prompt-injection exfiltration, hijacked always-on agents, Microsoft's "treat
agents as untrusted code execution with persistent credentials"), and almost
nobody ships the boring machinery for it. So I made that the product:

- **Per-channel sender trust.** A stranger in a Slack workspace is not you.
  Untrusted senders get destructive tools stripped from the model's view AND
  force-declined at the execution gate; their text is wrapped as
  data-not-instructions; their would-be memory writes are quarantined —
  someone can chat with your agent but can't teach it "facts" or touch your
  machine.
- **Injection screening on everything the agent reads** — uploads, web pages,
  search snippets, RSS. Flagged content is delivered wrapped and marked, never
  silently dropped (screening is a tripwire layered with prompt guards, not a
  classifier I'm pretending is perfect).
- **Approval-gated destructive tools with decline auditing** — the audit trail
  shows what was *asked*, not just what ran. Autonomous runs (watchers,
  routines, sub-agents) decline destructive tools unconditionally.
- **Sandboxed shell** — Windows Job Objects (memory cap, fork-bomb guard,
  kill-on-close) / POSIX rlimits under the approval gate.
- **Secrets vault + output redaction** — OS-native storage (Credential
  Manager/keyring/DPAPI), and known secret values are masked in every tool
  result and log line.
- **All of it visible in one Security tab** — trust map, sandbox state,
  quarantine log, audit trail. The threat model is published, including an
  explicit "what this does NOT claim" section: docs/SECURITY.md.

Two other things I think are genuinely uncommon:

- **A published memory benchmark.** Long-term memory is native + in-process
  (SQLite; no vector-DB service), and it ships with a reproducible eval —
  `python scripts/memory_eval.py --mock`, no API key needed — currently
  recall@5 = 92% on the offline retrieval suite. Small self-authored dataset,
  generously scored, not cross-project comparable — the methodology and
  limitations are in docs/BENCHMARKS.md. A weekly self-review re-runs it and
  trends the number, so "it learns you" is a line on a chart, not a vibe.
- **Event watchers with an "only if it matters" gate.** Cheap zero-LLM polls
  on files/email/web/calendar; one model pass filters noise against your
  stated intent; delivery over Telegram. The change summary is explicitly
  treated as untrusted data (a watched web page is an injection vector).

It runs always-on on Oracle's free tier (1 GB box, ~30-minute guide written
for someone who has never opened a cloud console), or any VPS/Docker. Windows
is a first-class target, not a port. MIT licensed. ~810 offline tests.

Honest scope: the brain is a cloud API call by design (or a local
OpenAI-compatible server if you point it at one); screening is heuristic;
the sandbox bounds blast radius, it isn't a jail. If you want a huge skills
ecosystem, Hermes and OpenClaw are ahead and I'm not chasing them.

Repo: https://github.com/SanthoshReddy352/Namma-Agent
Security model: …/docs/SECURITY.md · Benchmark: …/docs/BENCHMARKS.md ·
$0 deploy: …/docs/DEPLOY_ORACLE.md

I'd especially value criticism of the trust model — what would you try first
to break it?

---

## 2 · r/LocalLLaMA

**Title:**

> I built a self-hosted personal agent where the security model is the point —
> per-sender trust, injection quarantine, sandboxed shell, and a memory
> benchmark you can run offline (MIT)

**Body:**

Like half this sub I've been building a personal agent. Mine's angle: the
always-on agent category has a real trust problem, so instead of racing
Hermes/OpenClaw on skills and channels (unwinnable for a solo dev), I built
the thing nobody ships — a layered trust model that's **on by default and
visible in the UI** — and put numbers on the memory claims.

**Local-first notes for this sub:**

- The brain is any OpenAI-compatible endpoint — **Ollama / LM Studio work
  with one config key**, no cloud account needed. Provider chain falls back
  across endpoints when one is down.
- Memory is native + in-process (SQLite FTS5 + entity graph + optional
  embeddings from any `/embeddings` endpoint, incl. local). No Docker, no
  vector-DB service, works fully offline.
- The memory benchmark runs **without any API key**:
  `python scripts/memory_eval.py --mock` → recall@5 = 92% (12-case suite,
  methodology + honest limitations in docs/BENCHMARKS.md — it's a regression
  needle, not a leaderboard).

**The security stack** (all on by default, all observable in a Security tab):
per-channel sender trust (untrusted senders: destructive tools stripped +
declined, memory writes quarantined), injection screening on everything the
agent reads (web/search/RSS/uploads — flagged content wrapped, never silently
dropped), approval gate with *decline* auditing, Job-Object/rlimits shell
sandbox, OS-native secrets vault with output redaction. Threat model incl.
what it does NOT claim: docs/SECURITY.md.

**Also:** event watchers (file/email/web/calendar → LLM "worth telling you?"
gate → Telegram), a weekly self-review that mines transcripts and *proposes*
skills/automations (never auto-applies), Windows as a first-class target
(Job Objects, Credential Manager, tray, winget), and a ~30-min $0 Oracle
free-tier deploy guide (1 GB box — brain is an API call, so it fits).

MIT, ~810 offline tests, no telemetry, no hosted anything.

Repo: https://github.com/SanthoshReddy352/Namma-Agent

Would love this sub's take on two things: (1) the injection-screening
tripwire approach vs classifier-based screening, (2) what a local-model
benchmark for the *extraction* half of memory should look like.

`<demo clip: watcher catches an email → Telegram ping>`

---

## 3 · X / Twitter thread

**1/**
Every personal-agent demo is "look what it can do."
Almost none answer "what happens when a stranger messages it, a web page
prompt-injects it, or it runs a bad command at 3am."

I spent the last months building the answer. Namma Agent, MIT-licensed: 🧵

**2/**
Per-sender trust, on by default.
A stranger in your Slack ≠ you. Untrusted senders: destructive tools
stripped AND force-declined, text treated as data-not-instructions, memory
writes quarantined. They can chat. They can't teach your agent "facts."

**3/**
Everything the agent READS is screened for prompt injection — web pages,
search snippets, RSS, uploads. Flagged content isn't silently dropped; it's
delivered wrapped + marked, and logged to a quarantine you can inspect.
Screening is a tripwire, layered with guards — not a magic classifier.

**4/**
"It remembers you" is a claim. A benchmark is a fact.
Namma's memory ships with a reproducible eval — no API key needed:
`python scripts/memory_eval.py --mock` → recall@5 = 92%.
A weekly self-review re-runs it. Trend line, not vibes.
(Methodology + honest limits: docs/BENCHMARKS.md)

**5/**
Always-on that's actually reachable: watchers poll your files/email/web/
calendar for ~zero cost, one model pass decides "worth telling you?", and it
pings your phone over Telegram — with destructive tools hard-declined in
every autonomous run.

**6/**
It runs 24/7 on Oracle's free tier — 1 GB box, $0/month, ~30-min guide
written for someone who's never opened a cloud console. Zero open ports on
the recommended path (the gateway dials out).
First-class on Windows, too. Job Objects, Credential Manager, winget.

**7/**
It's honest about what it's not: no skills marketplace, five channels not 29,
the sandbox bounds blast radius rather than jailing, screening is heuristic.
The threat model — including "what we do NOT claim" — is published.

Repo: github.com/SanthoshReddy352/Namma-Agent
Break my trust model, I want the reports.

`<attach: 30s GIF — injection quarantine in action>`

---

## Posting notes

- **Order:** X thread + r/LocalLLaMA same day; Show HN a day or two later
  (HN traffic benefits from the repo already showing some life). Post HN on a
  weekday morning US time.
- **Be present:** all three formats live or die on author responses in the
  first 2–3 hours — block the time.
- **Don't oversell:** every number in these drafts is currently true
  (recall@5 = 92%, ~810 tests). Re-verify both before posting; update if
  they've moved.
- The "break my trust model" invitation is deliberate — it fits the
  anti-position brand, and reports become the Phase 4 "issues" metric.
