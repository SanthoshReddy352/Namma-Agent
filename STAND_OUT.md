# Namma Agent — Stand-Out Plan

> **Source of truth** for the "make Namma Agent stand out" effort — the successor to
> [Namma_Agent_Port.md](Namma_Agent_Port.md) (Hermes parity: ✅ done). All work is
> processed against this file; update statuses as phases land.
>
> **Thesis (2026-07-17 research):** feature parity is saturated and a feature/ecosystem
> race against Hermes (Nous, $1.5B, hosted Tool Gateway) or OpenClaw (viral, 100+
> skills, 29 channels) is unwinnable for a solo project. The open positions are:
> **trust/security** (the category's public wound — ClawJacked, injection/exfil CVEs,
> Microsoft's "treat as untrusted code execution with persistent credentials"),
> **event-driven proactivity** (the "always-on gap"), **measurable self-improvement**
> (memory is table stakes; *measured* memory is rare), and **distribution** (an unseen
> agent doesn't stand out). Namma already has 60% of the security machinery built —
> it's plumbing, not product, yet.

## Positioning

> **“The trustworthy personal agent that measurably knows you — first-class on Windows.”**

## Status legend
- `[ ]` Not started · `[~]` In progress · `[x]` Done (verified) · `[!]` Blocked · `[✗]` Declined (with reason)

## Guiding rules
- Keep Namma's invariants: cloud-only brain, `assistant.name` configurable, package stays `namma_agent`.
- Every phase ships with tests (offline/mocked) + a visible UI surface — invisible plumbing doesn't differentiate.
- Prefer stdlib / zero-new-heavy-deps (the Engram lesson).
- Windows is a first-class target for every item, not a port afterthought.

---

## Phase 1 — Trust as a product (security tab + hardening)
*Why first: biggest open position in the market, most of the machinery already exists
(docscan screening, quarantine, approval gate, audit table, sub-agent tool stripping),
and later phases (watchers, self-review) create MORE autonomous surface — the trust
model must exist before we widen autonomy.*

### 1a — Per-channel trust levels — ✅ landed 2026-07-18
- [x] Add `trust` to every inbound bridge (`comms/inbound.py`): `owner` / `trusted` / `untrusted`.
      Telegram/Signal (pinned ids) default `owner`; Slack/WhatsApp webhooks default `untrusted`;
      unknown channels always `untrusted`. (`core/trust.py`; level rides the turn as a
      contextvar set by the bridge — no signature churn.)
- [x] Thread trust into the agent turn: `untrusted` turns get destructive tools stripped
      from the model's view AND force-declined at the execution gate + memory writes gated
      (auto-ingest, `memory_save`, and `ingest_text` all quarantine — stored with
      `screen_status='untrusted'`, never FTS-indexed, zero model calls spent).
- [x] Untrusted message content wrapped in a guarded delimiter in the prompt
      (raw text still persisted in the transcript).
- [x] Config: `comms.trust.<channel>` in `config.yaml` + Settings → Messaging per-channel
      picker (`GET/POST /api/comms/trust` via status; applies to running bridges live).
- [x] Tests: `test_trust.py` (16) + `/api/comms/trust` endpoint test; full suite green;
      UI verified live (picker round-trip → config.local.yaml → status).

### 1b — Screen tool-fetched web content (close the injection gap) — ✅ landed 2026-07-18
- [x] Route web/browser tool outputs through `core/docscan.py` (`screen_web_text`) —
      `web_extract` (per page), `web_crawl` (per page, so one poisoned page doesn't
      taint the rest), `web_search` (titles/snippets are SEO-controllable), and
      `get_news` (RSS headlines). (`core/browser_controller.py` audited: it drives
      media/navigation and returns no page text to the model — nothing to screen.)
- [x] Flagged content is NOT dropped — wrapped in the guarded delimiter + a leading
      `⚠ possible prompt injection` marker (first line, so the Activity strip's
      summary shows it too) + `data.flagged/reasons` for programmatic surfaces.
- [x] Tests: `test_web_screening.py` (9) — seeded injection page/snippet/headline →
      flagged + wrapped, original content preserved; clean paths byte-identical.

### 1c — Sandboxed shell execution — ✅ landed 2026-07-18
- [x] Windows: every `run_shell` child runs in a **Job Object** (kill-on-close —
      closing the handle now also reaps descendants a timeout kill used to orphan —
      memory cap, active-process fork-bomb guard, optional cumulative CPU cap, no
      breakaway) — `core/sandbox.py`, ctypes, stdlib-only, attached in
      `shell_session._spawn`.
- [x] POSIX: `resource.setrlimit` (RLIMIT_AS/CPU/FSIZE via `preexec_fn`) + existing
      `start_new_session=True`; `_kill` now kills the whole process group (killpg).
- [x] Optional `security.shell.confine_to` root: absolute path args (and a cwd)
      outside it make `run_shell` refuse until the model gets the user's explicit
      OK and re-runs with `outside_root_approved=true` — approval in chat, tripwire
      not jail. URLs excluded from path matching.
- [x] Degrades gracefully (warn once, run as today; `status()` reports
      mechanism/caps/active for the 1e Security tab via `background_status()`).
      Config: `security.sandbox` in config.yaml (enabled by default, 4 GB cap).
- [x] Tests: `test_sandbox.py` (20) — fake kernel32 limit/flag/failure paths, fake
      resource-module rlimits (run on any platform), warn-once, confine tripwire +
      tool gate, and a REAL Windows Job Object kill-on-close integration test.
      Full suite 722 green; live probe: real PowerShell spawn → `active: true`.

### 1d — Secrets vault + redaction — ✅ landed 2026-07-18
- [x] `core/secrets.py`: Windows **Credential Manager** via ctypes (zero deps);
      POSIX `keyring` when installed; fallback file with **DPAPI**-sealed values
      on Windows / 0600 + machine-keyed obfuscation on POSIX. Names-only index
      (`data/secrets.index.json`) powers the inventory. Opt-in `.env` migration
      (`POST /api/secrets/migrate`, optional scrub that blanks values but keeps
      keys) + a boot **bridge** loading vault values into `os.environ` where
      unset — providers/channels unchanged.
- [x] **Redaction pass**: known secret VALUES (vault + secret-looking env vars,
      longest-first, 8-char floor) masked as `***NAME***` in every tool result's
      content/error (`ToolRegistry.execute` — covers the model, Activity strip,
      and persisted steps) and in the log via a `RedactingFilter` on the app logger.
- [x] API: `GET/POST/DELETE /api/secrets*` (names only, never values) — the 1e
      Security tab's data source.
- [x] Tests: `test_secrets.py` (15) — file-vault round-trip + on-disk
      not-plaintext, REAL Credential Manager round-trip (Windows), bridge
      precedence, migration ± scrub, redaction in tool output/error/log.
      Full suite 737 green; live verify: server picked `credential-manager`,
      API set→inventory→delete round-trip clean.

### 1e — Settings → Security tab (make it all visible)
- [ ] One tab that shows: per-channel trust levels, quarantine log (flagged docs/web/
      memory writes + trust/untrust actions), approval audit trail (from the existing
      `audit` table), sandbox status, secrets inventory (names only), and a plain-language
      "trust model" explainer.
- [ ] API: `GET /api/security/overview`, reuse existing audit/quarantine data.
- [ ] Tests: endpoint shape; UI renders all sections (build clean + live verify).

### 1f — Publishable security posture doc
- [ ] `docs/SECURITY.md`: threat model, trust boundaries, what's sandboxed, what's
      screened, what's approval-gated, responsible-disclosure note. This doubles as
      Phase 4 marketing material — it's the page OpenClaw doesn't have.

---

## Phase 2 — Event-driven proactivity (watchers)
*Why second: highest user-visible payoff per hour; the market's "always-on gap".
Builds directly on the routines runner + comms delivery; safe because Phase 1
already established that autonomous runs decline destructive tools.*

- [ ] **Watcher framework** (`core/watchers.py`, store `data/watchers.json`, runner
      pattern copied from `core/routines.py`): a watcher = *trigger* + *condition* + *action*.
- [ ] Trigger types (v1):
  - [ ] `file` — path/glob appears or changes (stdlib polling; no watchdog dep).
  - [ ] `email` — new message matching from/subject filter (reuse Gmail tooling).
  - [ ] `web` — page/selector content changed since last poll (hash diff; screened per 1b).
  - [ ] `calendar` — upcoming event / conflict within N minutes.
- [ ] **"Only if it matters" LLM gate**: trigger fires → cheap agent pass decides
      *notify / act / ignore* against the watcher's stated intent — no notification spam
      (the #1 complaint about always-on tools).
- [ ] Action = a routine-style scoped agent run (destructive tools always declined) →
      delivery via comms-first / native-notification fallback (reuse routine delivery).
- [ ] Chat tools: `create_watcher` (approval-gated), `list/toggle/delete_watcher`, `run_watcher_now`.
- [ ] Settings → Capabilities → Watchers tab (list, last-fired, enable/disable, delete) + `/api/watchers*`.
- [ ] Status tab row (watcher runner + per-watcher state) in `background_status()`.
- [ ] Tests: schedule math, each trigger type (mocked), LLM gate ignore/notify paths,
      destructive-tool refusal, persistence across restart.

---

## Phase 3 — Measured self-improvement (close the learning loop)
*Why third: turns Hermes's "grows with you" vibes into a number. Depends on nothing
new — mines data the app already has (sessions, skills, memory eval, usage stats).*

- [ ] **Weekly self-review** (a built-in routine, off by default until verified):
  - [ ] Mine the week's sessions for: failed turns (tool errors, user corrections,
        retries), repeated multi-step workflows, unanswered follow-ups.
  - [ ] Draft outputs: proposed new/updated **skills** (via the existing skills learning
        loop), proposed **routines/watchers**, memory consolidation notes.
  - [ ] Drafts are PROPOSALS — surfaced for one-click accept/reject, never auto-applied.
- [ ] **"What I learned this week" report**: delivered over comms + rendered in a new
      **Learning Report** surface (Settings → System or sidebar): facts learned, skills
      drafted, failures analyzed, recall-eval trend, tokens saved by caching/compaction.
- [ ] **Metrics spine**: persist weekly snapshots (`data/self_review/*.json`) —
      memory eval score (run `scripts/memory_eval.py --mock` headlessly), fact count,
      skill count, failure rate — so the report can show *trend lines*, not one-offs.
- [ ] Tests: session mining heuristics, proposal accept/reject round-trip, report
      generation offline, snapshot persistence.

---

## Phase 4 — Distribution & credibility
*Why fourth: needs Phases 1–3 as the story. Standing out is half engineering, half
being seen — this phase is cheap and currently at zero.*

- [ ] **README overhaul**: positioning line, 30-second GIF, honest comparison table
      (Namma vs Hermes vs OpenClaw: trust model, measured memory, watchers, Windows),
      quick-start (installer + one-liner).
- [ ] **Docs site**: MkDocs Material → GitHub Pages, from the existing `docs/`
      (ARCHITECTURE, MEMORY_SYSTEM_DESIGN, SECURITY, PLUGINS) + a "why Namma" page.
- [ ] **Publish the memory benchmark**: `docs/BENCHMARKS.md` — eval methodology,
      recall@k numbers, how to reproduce (`--mock`, no API key). Rare in this space; free credibility.
- [ ] **Demo assets**: 2–3 short screen recordings (watcher catching an email →
      Telegram ping; injection quarantine in action; weekly learning report).
- [ ] **Ship it**: GitHub release with the native installers (CI already builds them),
      topics/tags, a Show-HN / r/LocalLLaMA / X post anchored on the security angle.
- [ ] Track: stars/issues as the phase's success metric (visibility, not vanity).

---

## Phase 5 — Windows first-class polish
*Why last but real: OpenClaw is macOS-leaning, Hermes Linux/macOS-first. "Genuinely
great on Windows" is an underserved niche we already live in. Small items, big feel.*

- [ ] System tray icon (show/hide window, gateway status dot, quit) — pywebview/pystray.
- [ ] Start-on-login toggle (HKCU Run key; Settings → Behavior).
- [ ] `winget` package manifest (installer already exists + Add/Remove registration).
- [ ] WSL awareness in environment memory (Engram G8): detect distros, translate
      `/mnt/c` ↔ `C:\` in path assist.
- [ ] Toast actions (Reply / Open) on Windows notifications where supported.
- [ ] Fix the open note from the port tracker: shell defaulting to the stray Hermes venv PATH.

---

## Phase 6 — Server & cloud deployability (VPS / Oracle Cloud / any box)
*Why: an always-on agent (Phase 2 watchers, routines, messaging gateway) only
delivers when it runs somewhere that never sleeps. A laptop-bound agent misses the
"always-on" promise; a $0 Oracle free-tier box or any VPS keeps the gateway
listening 24/7. Deployability is also distribution (Phase 4): "runs on the free
tier" is a quick-start story competitors bury behind hosted subscriptions. Phase 1
must land first — exposing the agent on a server without the trust model, sandbox,
and secrets vault would be irresponsible.*

> **Reference target: Oracle `VM.Standard.E2.1.Micro`** (Always Free: x86-64 AMD,
> 1 OCPU share, **1 GB RAM**, 2 instances/tenancy). Chosen over the bigger A1 ARM
> shape on purpose: E2.1.Micro is **actually obtainable** (A1 capacity is
> perpetually "out of capacity" in most regions) and never expires — the "always
> available" box. Everything in 6a/6b must FIT AND STAY HEALTHY in 1 GB: the
> headless agent + always-on messaging gateway is the workload, the web UI is
> occasional, the brain is an API call (no local model). Budget: agent RSS well
> under ~400 MB, swap file mandatory in the guide, zero heavy deps (the Engram
> rule pays off here).

### 6a — Headless server hardening (make remote exposure safe)
- [ ] Bind address + port in config (`server.host`/`server.port`; default stays
      `127.0.0.1` — never silently public).
- [ ] **Access token auth** for the web UI/API when bound beyond localhost
      (`server.auth_token` / `NAMMA_AUTH_TOKEN`): required on every REST + WebSocket
      request; constant-time compare; UI login screen stores it.
- [ ] Headless-friendly paths: no pywebview assumption in `--server` mode (already
      true — verify + test), data dir override (`NAMMA_DATA_DIR`) for volume mounts.
- [ ] Tests: auth required/rejected/accepted, localhost default unchanged, data-dir override.

### 6b — Deployment packaging (sized for the 1 GB micro)
- [ ] **1 GB memory profile, measured**: run the headless server + gateway on (or
      simulated as) E2.1.Micro; record RSS; trim if needed (lazy imports for the
      UI-only paths, `conversation.tool_result_max_chars` preset, smaller history
      window preset). Ship a `config.server-lite.yaml` profile the guide references.
- [ ] **One-line installer for Ubuntu/Debian VPS** (`deploy/install.sh`, curl-able):
      creates a `namma` user, venv install, **creates a 2 GB swap file** (the 1 GB
      box's survival step), writes the systemd unit, starts the service, prints the
      access token + next steps. Idempotent — safe to re-run.
- [ ] **systemd unit** template (`deploy/namma-agent.service`): restart-on-failure,
      `EnvironmentFile=.env`, `MemoryMax=` guard so the OOM killer never takes the
      whole box, runs `python -m namma_agent --server`.
- [ ] **Dockerfile** (python:slim, non-root user, volume for `data/` + config,
      healthcheck on `/api/health`) + `docker-compose.yml` (one service, env-file,
      `mem_limit` matching the micro). x86-64 first (E2.1.Micro), ARM64 also built
      (A1 users); CI smoke-tests the image.
- [ ] Tests: compose config validates; install.sh lints (shellcheck) + dry-run mode;
      `/api/health` smoke test.

### 6c — Deployment guides (a first-time cloud user succeeds by reading alone)
*Audience contract for EVERY guide in this phase: the reader has never opened a
cloud console, doesn't know what SSH is, and uses Windows at home. Every step is a
numbered click-path or a copy-paste command with its expected output shown; every
"why" is one plain sentence; every step has a "if you see X instead → do Y"
recovery line. No unexplained jargon — the first use of a term (instance, SSH,
firewall, token) gets a one-line definition. Success is testable: at the end the
user messages their agent from their phone and it answers.*
- [ ] `docs/DEPLOY.md` — the umbrella guide: what self-hosting gives you (the
      always-on gateway), pick your path (Oracle free tier ★ recommended / any VPS /
      always-on home PC / Docker), the security checklist in plain words (auth
      token, firewall, trust levels for exposed webhooks), how to update, and
      backup = "copy the `data/` folder" (+ vault caveat from 1d).
- [ ] **`docs/DEPLOY_ORACLE.md` — the flagship walkthrough (E2.1.Micro, from zero)**:
  - [ ] Create the Oracle Cloud Free account (card-verification note: no charges on
        Always Free; region choice matters — pick your home region, it can't change).
  - [ ] Create the VM: every console click to launch `VM.Standard.E2.1.Micro` with
        Ubuntu; download the SSH key; screenshot-level detail (or described fields
        where screenshots would rot).
  - [ ] Connect from Windows: `ssh` in PowerShell (it's built in — no PuTTY needed),
        fixing the key-permissions error they WILL hit, what a prompt is.
  - [ ] Install: paste the 6b one-liner; what it prints; the 2 GB swap file it makes
        and why the 1 GB box needs it.
  - [ ] Oracle's TWO firewalls explained simply (Security List in the console +
        `iptables` on the box) — only if exposing the web UI; the Telegram-only path
        needs NO open ports at all (the gateway dials out — this is the recommended,
        zero-exposure default).
  - [ ] Keep-alive facts: Always Free E2.1.Micro is not idle-reclaimed (that's A1);
        what the monthly network cap looks like for a chat workload (nowhere close).
  - [ ] Verify + celebrate: `systemctl status`, message the bot from your phone,
        reboot test (`sudo reboot` → it comes back by itself).
  - [ ] Troubleshooting table: out of capacity (rare on E2.1.Micro; try another AD),
        SSH timeout (wrong IP / security list), bot silent (token typo, gateway
        stopped), OOM (swap missing).
- [ ] **Generic VPS walkthrough** (`docs/DEPLOY_VPS.md`, Hetzner/DO/Lightsail-
      agnostic, assumes the Oracle guide's literacy level): non-root user, ufw,
      the same one-liner, optional domain + Caddy TLS (two-line config).
- [ ] `docs/GATEWAYS.md` — per-channel messaging setup, same audience contract:
      Telegram first (BotFather → token → chat id, with exact taps — it's the
      recommended channel: dial-out, no public URL, `owner` trust by default),
      then Discord (bot + intents), Slack (Socket Mode vs Events URL), WhatsApp
      (QR link vs Cloud API webhook), Signal (signal-cli REST) — each labeled:
      needs a public URL? recommended trust level (from 1a)? works on the 1 GB box?
- [ ] Cross-link: Settings → Messaging surfaces "Deployment & gateway guides" links;
      README quick-start points at DEPLOY.md; DEPLOY_ORACLE.md is the story Phase 4
      leads with ("your own agent, $0/month, 30 minutes").

---

## Declined / deliberately not chasing
- [✗] **Skills marketplace / plugin ecosystem** — network-effects play; incumbents win by default. Namma's answer is the self-review loop *drafting* personal skills (Phase 3).
- [✗] **Channel-count race** (iMessage, WeChat, 29 channels) — current five + CLI cover the owner-user; each new channel is surface area against Phase 1.
- [✗] **Image-gen / TTS hosted gateway** — subscription-infra play (Hermes Tool Gateway). Revisit only if a user need appears.
- [✗] **MoA (mixture-of-agents)** — research-grade cost multiplier, no differentiation for a personal agent.
- [✗] **GODMODE-style jailbreak skills** — permanently declined; the anti-position is the brand.

## Order rationale (one line each)
1. **Trust** — market's open wound; 60% built; must precede wider autonomy.
2. **Watchers** — the always-on gap; highest visible payoff; safe atop Phase 1.
3. **Measured self-improvement** — makes "grows with you" a number; feeds the story.
4. **Distribution** — tells the story Phases 1–3 wrote; near-zero cost.
5. **Windows polish** — the niche nobody serves; small items, compounding feel.
6. **Deployability** — makes "always-on" real on a $0 VPS; needs Phase 1's trust
   model landed before any remote exposure; guides double as Phase 4 material.
