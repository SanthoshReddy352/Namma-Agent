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

### 1e — Settings → Security tab (make it all visible) — ✅ landed 2026-07-18
- [x] Settings → System → **Security** tab: plain-language trust-model explainer,
      per-channel trust chips (links to Messaging to change), sandbox status card
      (mechanism + caps + active), secrets inventory (backend + names only, with the
      1d migrate button), quarantine log (untrusted-sender memory writes,
      injection-flagged documents, suspicious web fetches), and the approval audit
      trail — collapsible (default collapsed, count in header), destructive calls
      badged approved/declined. Declined destructive attempts are now audit-logged
      (`agent.py` decline path), so the trail shows what was ASKED, not just what ran.
- [x] API: `GET /api/security/overview` — one payload aggregating `trust_map`,
      `sandbox.status()`, secrets inventory, `store.quarantined_items()` (new),
      `db.flagged_documents()` (new), `db.recent_audit()` (new, destructive-annotated);
      web flags mined from the audit's ⚠ markers (no new store).
- [x] Tests: endpoint shape test (seeded decline + quarantine + flagged doc + web
      flag) + decline-audit assertion in `test_trust.py`. Full suite 738 green;
      live verify: real instance rendered every section with live data (50 real
      audit rows, credential-manager backend), collapse/expand round-trip clean.

### 1f — Publishable security posture doc — ✅ landed 2026-07-19
- [x] `docs/SECURITY.md`: threat model (4 prioritized threats + explicit
      out-of-scope), the six trust boundaries (per-channel sender trust, injection
      screening, approval gate + decline auditing, shell sandbox, secrets vault +
      redaction, memory integrity), an honest "what Namma does NOT claim" section,
      and a responsible-disclosure note. Cross-referenced to the live Security tab
      (1e) — every claim in the doc is observable in the UI. Doubles as Phase 4
      marketing material.

**Phase 1 complete — trust is now a product surface, not plumbing.**

---

## Phase 2 — Event-driven proactivity (watchers)
*Why second: highest user-visible payoff per hour; the market's "always-on gap".
Builds directly on the routines runner + comms delivery; safe because Phase 1
already established that autonomous runs decline destructive tools.*

- [x] **Watcher framework** — ✅ landed 2026-07-19 (`core/watchers.py`, store
      `data/watchers.json`, runner pattern copied from `core/routines.py`): a
      watcher = *trigger* + *condition* + *action*, with per-type check cadence
      (file 2 min / email 5 / calendar 5 / web 30, overridable), lazy runner
      start (creating a watcher IS the opt-in), and per-watcher `last_result`
      so the UI shows WHY nothing happened.
- [x] Trigger types (v1) — all cheap polls, zero model calls, first check
      records a baseline without firing (except calendar, where "already within
      the window" is the point):
  - [x] `file` — path/glob new/changed/removed (stdlib glob+mtime snapshot; no watchdog dep).
  - [x] `email` — new message ids matching a Gmail query (via `gmail_list`);
        summaries injection-screened per 1b (subjects are attacker-writable).
  - [x] `web` — extracted-text hash diff via `web_extract` (so 1b screening
        already applied); noisy-page churn is the gate's job to filter.
  - [x] `calendar` — events starting within N minutes (via `calendar_agenda`),
        optional title match, no re-alert per event; screened per 1b.
- [x] **"Only if it matters" LLM gate**: trigger fires → one cheap no-tools model
      pass (`service._watcher_gate`) decides *notify / act / ignore* against the
      watcher's stated intent, with the change summary explicitly framed as
      untrusted DATA. Gate failure falls back to *notify* (never silently drop);
      `gate: false` per watcher skips the pass.
- [x] Action = a routine-style scoped agent run (reuses `_routine_turn` —
      destructive tools always declined) → delivery via comms-first /
      native-notification fallback (mirrors routine delivery, 🔔 prefix).
- [x] Chat tools: `create_watcher` (approval-gated), `list/toggle/delete_watcher`
      (delete gated too), `run_watcher_now`.
- [x] Settings → Capabilities → Watchers tab (trigger chip, intent, last
      checked/fired, last result, check-now/toggle/delete) + `/api/watchers*`
      (list/toggle/delete/run, mirroring routines).
- [x] Status tab row (watcher runner + per-watcher state) in `background_status()`.
- [x] Tests: `test_watchers.py` (22) — cadence math, every trigger type (mocked
      tools, incl. error-is-a-note-not-a-fire and injection-screened summaries),
      gate ignore/notify/act/act-degrades/failure-fallback/disabled paths,
      persistence across runner restart, tools round-trip + destructive flags,
      REST endpoint shapes. Full suite 760 green; live verify: real server +
      dev UI — Watchers tab rendered a seeded watcher, "Check now" recorded a
      real Downloads baseline into the store, delete round-trip clean.

**Phase 2 complete — the agent now reaches out when things happen, not just on a clock.**

---

## Phase 3 — Measured self-improvement (close the learning loop)
*Why third: turns Hermes's "grows with you" vibes into a number. Depends on nothing
new — mines data the app already has (sessions, skills, memory eval, usage stats).*

- [x] **Weekly self-review** — ✅ landed 2026-07-19 (`core/self_review.py` +
      `SelfReviewRunner`, OFF by default via `self_review.enabled: false`; the
      "Run review now" button always works; a fresh enable waits for the next
      weekly slot instead of firing instantly):
  - [x] Mine the week's sessions (offline heuristics, zero model calls): failed
        tool runs from the audit trail (incl. declined destructive), user
        corrections (phrase heuristics), retries (word-set similarity on
        consecutive asks), repeated multi-step workflows (recurring
        `tools_used` sequences ×3+), sessions ending on an unanswered user
        message. (`Database.turns_since` added for the window sweep.)
  - [x] Draft outputs: ONE model pass (the user-selected Settings model) drafts
        ≤5 proposals — skills (applied via the existing skills learning loop),
        routines, watchers, or plain notes — each validated against the real
        stores' rules before it's even shown.
  - [x] Drafts are PROPOSALS: pending in `data/self_review/proposals.json`,
        one-click accept/reject in the Learning tab, never auto-applied.
        Accepted routines/watchers arrive DISABLED; rejected titles are
        remembered so an idea can't nag weekly.
- [x] **"What I learned this week" report**: plain-text report persisted +
      rendered in Settings → System → **Learning** (stat cards with was-X
      trends, report body, proposal queue) and delivered over comms on
      scheduled runs (manual runs stay in the UI).
- [x] **Metrics spine**: weekly snapshots in `data/self_review/YYYY-MM-DD.json`
      (rerun same day = overwrite, not dup) — recall@k from the headless
      `--mock` memory eval, fact/entity/relation counts, skill count, tool
      failure rate, 7-day tokens + cached reads — so the report shows
      *trend lines*, not one-offs. Status tab row + `background_status()` block.
- [x] Tests: `test_self_review.py` (15) — mining heuristics on a seeded DB,
      window cutoff, offline eval, snapshot persistence + trend order,
      proposal validate/draft-parse/dedupe (rejected ideas stay dead),
      accept-applies (skill/routine/watcher — disabled) + double-resolve
      refusal, report trends, weekly anchoring math, runner off-by-default,
      endpoint shapes. Full suite 775 green; live verify: real "Run review
      now" mined 15 sessions/234 calls, measured recall@5 = 92%, and the real
      model drafted 2 skill proposals from the actual failure evidence
      (left pending — the user's call).

**Phase 3 complete — "grows with you" is now a number with a trend line.**

---

## Phase 4 — Distribution & credibility
*Why fourth: needs Phases 1–3 as the story. Standing out is half engineering, half
being seen — this phase is cheap and currently at zero.*

- [~] **README overhaul** — text landed 2026-07-19: positioning line ("the
      trustworthy personal agent that measurably knows you"), honest comparison
      table (Namma vs Hermes vs OpenClaw across trust/memory/proactivity/
      self-improvement/channels/Windows/hosting — with explicit "when to pick
      them" concessions), 41 stale Cognee references replaced with Engram
      (zero-setup memory is now part of the quick-start story), trust &
      watchers & self-review sections added. **Open: the 30-second GIF**
      (placeholder comment marks the slot — needs the Phase 4 demo recordings).
- [x] **Docs site** — landed 2026-07-19: `mkdocs.yml` (Material, dark/light,
      nav over the existing docs), `docs/WHY_NAMMA.md` positioning page,
      reorganized `docs/README.md` index, `.github/workflows/docs.yml`
      (gh-deploy on docs changes to main). Verified locally: built clean +
      rendered (Home/Why Namma/Benchmarks checked in the browser; `docs`
      entry added to .claude/launch.json). Remaining link warnings are
      pre-existing `../` links to source files (GitHub-only); harmless.
      **Post-push step: enable GitHub Pages (branch `gh-pages`) in repo settings.**
- [x] **Publish the memory benchmark** — landed 2026-07-19: `docs/BENCHMARKS.md`
      — what's measured (real write pipeline → real recall stack, substring
      recall@k), the two modes (offline `--mock` isolates retrieval; default
      measures the user's model end-to-end), current number (**recall@5 = 92%**,
      11/12, verified this session; the one miss diagnosed honestly — zero
      lexical overlap "allergies"/"allergic", the gap embeddings close),
      weekly trend via self-review snapshots, reproduce commands, and an
      honest-limitations section (small self-authored dataset, generous
      scoring, not cross-project comparable).
- [ ] **Demo assets**: 2–3 short screen recordings (watcher catching an email →
      Telegram ping; injection quarantine in action; weekly learning report).
- [ ] **Ship it**: GitHub release with the native installers (CI already builds them),
      topics/tags, a Show-HN / r/LocalLLaMA / X post anchored on the security angle.
- [ ] Track: stars/issues as the phase's success metric (visibility, not vanity).

---

## Phase 5 — Windows first-class polish
*Why last but real: OpenClaw is macOS-leaning, Hermes Linux/macOS-first. "Genuinely
great on Windows" is an underserved niche we already live in. Small items, big feel.*

- [x] System tray icon — landed 2026-07-19: `core/tray.py` (pystray + Pillow,
      both optional — no tray libs, no tray, app unaffected): show/hide window
      (double-click default), live gateway status line (recomputed on menu
      open, zero polling), open-in-browser, quit (destroys the window → clean
      shutdown). Wired in `app.py:_start_tray`; tray stops on window close.
      Tests: `test_tray.py` (4, fake-pystray menu wiring + real-pystray build).
- [x] Start-on-login toggle — landed 2026-07-19: `core/autostart.py` (HKCU Run
      key via winreg, prefers `pythonw.exe`; Linux XDG autostart .desktop;
      macOS honestly unsupported), `GET/POST /api/autostart`, Settings →
      Behavior toggle (applies instantly, no Save). Tests: `test_autostart.py`
      (5, incl. a REAL HKCU round-trip under a test-only value name).
- [x] `winget` package manifest — landed 2026-07-19: `installers/winget/`
      generator (`generate.py`) emits the 3-file schema-1.6 set with the real
      release-asset SHA-256; silent switch is the installer's existing `--cli`
      mode; Add/Remove DisplayName matched. README covers validate → local
      install test → winget-pkgs PR. Tests: `test_winget.py` (2).
      **Post-release step: run the generator + submit the PR once a release is out.**
- [x] WSL awareness (Engram G8) — landed 2026-07-19: `detect_wsl()` (UTF-16
      parsing, graceful None), distros + default in the HOST prompt block,
      path assist translates `/mnt/<drive>/…` → `<Drive>:\…` and passes
      `\\wsl$\…` through. Live-verified (found the real docker-desktop
      distro). Tests in `test_engram.py` (+5).
- [x] Toast actions — landed 2026-07-19: Windows notifications are now real
      Action-Center toasts (WinRT via PowerShell, powershell-AUMID route for
      unpackaged apps) with **Reply** and **Open** protocol-action buttons
      deep-linking the web UI (`?reply=1` hint; composer autofocuses); body
      click opens too; in-script fallback to the legacy balloon where WinRT is
      unavailable. Live-verified (real toast fired). Tests in
      `test_notifications.py` (+2).
- [x] Stray Hermes venv PATH — fixed 2026-07-19: spawned shells get a sanitized
      PATH (`shell_session._shell_env`) — other products' `venv\Scripts` /
      `venv/bin` entries dropped (the machine's real Hermes leftover confirmed
      the case), Namma's own interpreter dir prepended so `python`/`pip` mean
      the agent's venv. Port-tracker open note closed. Tests in
      `test_shell_session.py` (+2).

**Phase 5 complete — Namma feels native on Windows, not ported to it.**

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

### 6a — Headless server hardening — ✅ landed 2026-07-19
- [x] Bind address + port in config (`server.host`/`server.port` +
      `NAMMA_HOST`/`PORT` env overrides for containers; default stays
      `127.0.0.1`); non-loopback bind without a token logs a loud warning.
- [x] **Access token auth** (`server.auth_token` / `NAMMA_AUTH_TOKEN`, env wins):
      middleware on every `/api/*` request (Bearer / X-Namma-Token / ?token=,
      `hmac.compare_digest`) + the WebSocket (?token=, close 4401). Exempt:
      `/api/health` (healthchecks) and `/webhooks/*` (platform-verified). UI:
      401/4401 → **unlock screen** (AuthGate) → token in localStorage → every
      fetch + the WS carry it.
- [x] `NAMMA_DATA_DIR` override via `config.data_dir()` — swept through all
      state stores (db default, uploads/media, watchers/routines/self-review,
      jsonstores, secrets vault dir, projects, app tracker, learning nudges).
- [x] Tests: `test_server_hardening.py` (9) — bind defaults/env precedence,
      token resolution, 401/carriers/health-exempt/static-open, WS 4401 +
      accept, data-dir override + stores following it. **Live-verified**:
      real server with a token → UI showed the unlock screen (API-backed
      sidebar empty on 401), pasted token → reloaded authenticated, sessions
      + WS up, zero console errors.

### 6b — Deployment packaging — ✅ landed 2026-07-19 (RSS measurement pending)
- [~] **1 GB memory profile**: `deploy/config.server-lite.yaml` overlay shipped
      (smaller history window, tool-result cap, gentler consolidation, loopback
      bind) and referenced by the installer/Dockerfile. The CI docker job
      (below) now **records the container's idle RSS under the 900m cap** on
      every push — first numbers arrive with the next push; confirm on a real
      E2.1.Micro at first deploy.
- [x] **One-line installer** `deploy/install.sh` (curl-able, idempotent =
      updater): apt deps, **2 GB swap if <2 GB RAM**, `namma` system user,
      clone/pull, venv (core+comms deps only), UI build (skipped when dist
      ships), server-lite profile (first install only), token generation into
      `.env` (kept if present), systemd unit install + start, prints token +
      next steps. `--dry-run` / `--no-swap` flags.
- [x] **systemd unit** `deploy/namma-agent.service`: restart-on-failure,
      `EnvironmentFile=.env`, **`MemoryMax=700M`** + `TasksMax`, basic
      hardening (NoNewPrivileges/ProtectSystem), `--server` headless.
- [x] **Dockerfile** (node build stage → python:3.12-slim runtime, non-root,
      `VOLUME /app/data` + `NAMMA_DATA_DIR`, stdlib `/api/health` HEALTHCHECK,
      `NAMMA_HOST=0.0.0.0`) + **docker-compose.yml** (env-file, loopback-only
      port publish by default, `mem_limit: 900m`) + `.dockerignore`.
      Local build blocked by a machine-level Windows bug (AF_UNIX socket
      files undeletable → Docker Desktop can't boot; diagnosed 2026-07-20,
      reboot pending) — so the verification moved to CI: a new `docker` job
      in ci.yml builds the real image, boots it under the 900m cap, smokes
      `/api/health`, records idle RSS, and verifies the 6a auth gate
      (401 without token / 200 with) inside the running image.
- [x] Tests: `test_deploy.py` (6) — compose parses with the bounds, Dockerfile
      essentials, unit-file guard rails, install.sh safety rails (`set -euo
      pipefail`, dry-run, swap, token, no CRLF) + a real `bash -n` syntax pass.

### 6c — Deployment guides — ✅ landed 2026-07-19 (audience contract below honored)
*Audience contract for EVERY guide in this phase: the reader has never opened a
cloud console, doesn't know what SSH is, and uses Windows at home. Every step is a
numbered click-path or a copy-paste command with its expected output shown; every
"why" is one plain sentence; every step has a "if you see X instead → do Y"
recovery line. No unexplained jargon — the first use of a term (instance, SSH,
firewall, token) gets a one-line definition. Success is testable: at the end the
user messages their agent from their phone and it answers.*
- [x] `docs/DEPLOY.md` — landed: what self-hosting gives you, the pick-your-path
      table (Oracle ★ / VPS / Docker / home PC), plain-words security checklist
      (zero-exposure default, token, TLS, webhook trust, the two firewalls),
      update = re-run the installer, backup = tar `data/` + `.env` +
      config.local.yaml with the 1d vault machine-key caveat, and the 1 GB
      reference-box sizing story.
- [x] **`docs/DEPLOY_ORACLE.md` — the flagship walkthrough** — landed with every
      contracted beat: account creation (card-verification note, home-region
      warning), VM creation click-by-click (E2.1.Micro chosen over A1 with the
      why, described fields not screenshots), Windows SSH (built-in, the
      icacls key-permissions fix they WILL hit, "what a prompt is"), the
      one-liner install with its printed 9 steps + swap-file why, the TWO
      firewalls (with "you almost certainly need NEITHER" + SSH-tunnel
      alternative), keep-alive facts (not idle-reclaimed; 10 TB/month vs a
      chat workload), verify + celebrate (status → bot answers → reboot acid
      test), and the troubleshooting table (capacity/SSH/bot-silent/OOM).
- [x] **Generic VPS walkthrough** (`docs/DEPLOY_VPS.md`) — non-root user + ufw
      hygiene, the same one-liner, Telegram + verify by reference, optional
      domain + two-line Caddy TLS with the loopback-only division of labor.
- [x] `docs/GATEWAYS.md` — the at-a-glance table (public URL? default trust?
      1 GB fit? verdict) for all five channels + both WhatsApp/Slack modes,
      Telegram with the exact taps (BotFather → token, @userinfobot → chat id,
      .env lines, restart), "dials out" defined, when-you-need-webhooks
      pointer to the Caddy step. Credential deep-dives stay in COMMS.md (no
      duplication — deployment view only).
- [x] Cross-links — landed: Settings → Messaging Gateway card now links the
      three guides (GATEWAYS / DEPLOY / COMMS, new-tab); README quick-start
      gained the "always-on for $0" section pointing at DEPLOY.md +
      DEPLOY_ORACLE.md; COMMS.md tips point server users at GATEWAYS/DEPLOY;
      mkdocs nav gained a Self-hosting section; docs/README.md index updated.

**Phase 6 code+docs complete — remaining: measure real RSS on a 1 GB box (first
real deploy) and wire the Docker-image smoke test into CI.**

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
