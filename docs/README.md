# Namma Agent Documentation

> **The trustworthy personal agent that measurably knows you — first-class on
> Windows.** New here? Start with [Why Namma](WHY_NAMMA.md), then the
> top-level [README](https://github.com/SanthoshReddy352/Namma-Agent#readme)
> for setup.

## Trust & security

- **[SECURITY.md](SECURITY.md)** — the threat model and the six trust
  boundaries (sender trust, injection screening, approval gate, shell
  sandbox, secrets vault, memory integrity) — plus what Namma does *not* claim.

## Memory

- **[MEMORY_SYSTEM_DESIGN.md](MEMORY_SYSTEM_DESIGN.md)** — Engram, the native
  in-process memory: research survey, schema, write pipeline, recall fusion,
  consolidation.
- **[BENCHMARKS.md](BENCHMARKS.md)** — the reproducible memory eval:
  methodology, current recall@k, how to run it with no API key.

## Setup

- **[INSTALL.md](INSTALL.md)** — install, run, and update the Desktop App on
  Windows/macOS/Linux (one-click installers + how updates work).
- **[COMMS.md](COMMS.md)** — connect messaging channels (Telegram, Signal,
  Slack, WhatsApp, Discord): credentials, trust levels, and the gateway.

## Self-hosting (always-on)

- **[DEPLOY.md](DEPLOY.md)** — the umbrella: pick your path, the plain-words
  security checklist, updating, backups, the 1 GB reference box.
- **[DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)** — the flagship walkthrough: your
  own agent on Oracle's Always-Free tier, $0/month, from zero, ~30 minutes.
- **[DEPLOY_VPS.md](DEPLOY_VPS.md)** — the same result on any VPS
  (Hetzner/DO/Lightsail), plus optional domain + TLS via Caddy.
- **[GATEWAYS.md](GATEWAYS.md)** — which messaging channel to run on a
  server: public-URL needs, trust levels, 1 GB-box fit, Telegram exact taps.

## Guides

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how the whole system works, with UML
  diagrams and the rationale behind every major technical decision.
- **[SKILLS.md](SKILLS.md)** — how skills (procedural memory) work and how they're created.
- **[EXTENDING.md](EXTENDING.md)** — create your own tools and skills (developer guide).
- **[PLUGINS.md](PLUGINS.md)** — attach external MCP servers (including
  optional external memory providers).
- **[SELF_MODIFICATION.md](SELF_MODIFICATION.md)** — how the assistant writes its own
  tools/skills and reconfigures itself at runtime, and the safety model.

## Project

- **[RELEASING.md](RELEASING.md)** — how to publish a new version (versions, git
  tags, GitHub releases) so installed apps can auto-update.
