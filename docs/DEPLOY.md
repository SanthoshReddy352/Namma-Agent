# Self-hosting Namma Agent (always-on)

Namma's watchers, routines, and messaging gateway only deliver when the agent
runs somewhere that never sleeps. A laptop closes; a server doesn't. This page
is the map — pick a path, follow its guide, and at the end you message your
agent from your phone and it answers.

**No cloud experience is assumed** in any of these guides. Every step is a
numbered click-path or a copy-paste command with its expected output, and each
first use of a term (instance, SSH, firewall, token) gets a one-line
definition.

## What self-hosting gives you

- The **messaging gateway** listens 24/7 — Telegram/Signal/Discord messages
  reach your agent any time, from anywhere.
- **Watchers and routines** fire on schedule or on events even while your PC
  is off.
- Your data stays on a machine you control (the whole state is one `data/`
  folder).

## Pick your path

| Path | Cost | Difficulty | Guide |
|---|---|---|---|
| **Oracle Cloud free tier** ★ recommended | $0/month, forever | ~30 min, from zero | [DEPLOY_ORACLE.md](DEPLOY_ORACLE.md) |
| Any VPS (Hetzner, DigitalOcean, Lightsail…) | ~$4–6/month | ~15 min | [DEPLOY_VPS.md](DEPLOY_VPS.md) |
| Docker (any box that runs it) | — | ~10 min | below |
| Always-on home PC | electricity | ~5 min | run `python -m namma_agent --server`; add [start-on-login](INSTALL.md) |

All server paths use the same one-line installer
([`deploy/install.sh`](../deploy/install.sh)): system user, venv, a 2 GB swap
file on small boxes, a systemd service that survives reboots, and a generated
access token.

### Docker quick path

```bash
git clone https://github.com/SanthoshReddy352/Namma-Agent.git && cd Namma-Agent
cp namma_agent/.env.example .env      # put your provider key in it
docker compose up -d                  # builds the UI + serves on 127.0.0.1:8000
docker compose logs -f                # watch it come up
```

State lives in the `namma_data` volume; the port publishes to **loopback
only** by default — reach the UI through an SSH tunnel
(`ssh -L 8000:localhost:8000 you@server`, then open http://localhost:8000
at home) or put a reverse proxy with TLS in front.

## The security checklist, in plain words

Read once before exposing anything. The full model is in
[SECURITY.md](SECURITY.md).

1. **Prefer the zero-exposure path.** The Telegram/Signal/Discord gateways
   *dial out* — the server needs **no open ports at all**, and there is
   nothing on the internet to attack. This is the recommended default.
2. **If you expose the web UI, set the access token.** The installer already
   generated one (`NAMMA_AUTH_TOKEN` in the server's `.env`); with it set,
   every API call and the websocket require the token and the UI shows an
   unlock screen. Without a token, the server refuses nothing — so it binds
   loopback-only by default and warns loudly if you change that.
3. **Front the open internet with TLS.** A reverse proxy (Caddy is two lines —
   see [DEPLOY_VPS.md](DEPLOY_VPS.md)) gives you `https://` and hides the raw
   port.
4. **Keep webhook channels untrusted.** If you open Slack/WhatsApp webhooks to
   the world, their [trust level](COMMS.md#trust-levels--who-is-allowed-to-do-what)
   stays `untrusted` — strangers can chat but can't run destructive tools or
   write memory.
5. **Firewall = the cloud's + the box's.** Some providers (Oracle!) have TWO
   layers; the Oracle guide walks both.

## Updating

```bash
sudo bash /opt/namma-agent/deploy/install.sh   # idempotent — re-running IS the update
```

It pulls the latest code, updates deps, rebuilds the UI if needed, and
restarts the service. Your `.env`, `config.local.yaml`, and `data/` are never
touched.

## Backup = copy the data folder

Everything the agent knows lives in `/opt/namma-agent/data/` (or the
`namma_data` Docker volume): the SQLite database, uploads, watchers, routines,
self-review snapshots.

```bash
sudo tar czf namma-backup-$(date +%F).tgz -C /opt/namma-agent data .env namma_agent/config.local.yaml
```

**One caveat:** secrets stored in the OS **vault** (Settings → Security) are
machine-keyed — a vault file restored onto a *different* machine can't be
unsealed. On servers, keep secrets in `.env` (which the backup includes), or
re-enter vault secrets after a move.

## The 1 GB reference box

Everything above is sized to run healthy on Oracle's Always-Free
`VM.Standard.E2.1.Micro` (1 GB RAM): the headless agent + gateway idles well
under ~400 MB RSS, the installer's **2 GB swap file** absorbs spikes, the
systemd unit's `MemoryMax=700M` (or the compose `mem_limit`) makes sure a
runaway agent gets restarted instead of taking the box down, and the
[server-lite profile](../deploy/config.server-lite.yaml) trims per-turn
context. The brain is an API call — the box never runs a model.
