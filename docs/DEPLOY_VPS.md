# Deploy on any VPS (Hetzner, DigitalOcean, Lightsail, …)

The generic version of the [Oracle walkthrough](DEPLOY_ORACLE.md) — same
assumed knowledge (never used a cloud, Windows at home), same result: your
agent answering on your phone from a box that never sleeps. Any provider
works; the cheapest tier (~$4–6/month, 1 GB RAM) is plenty — Namma's brain is
an API call, the box never runs a model.

## 1. Create the server

At your provider, create the smallest **Ubuntu 22.04+ (or Debian 12+)**
server. Add your SSH key if the provider asks (or let it email you a root
password). Note the server's **public IP** — `YOUR_IP` below.

## 2. Connect from Windows

PowerShell has SSH built in:

```powershell
ssh root@YOUR_IP        # or: ssh -i path\to\key ubuntu@YOUR_IP  (provider-dependent)
```

Type `yes` at the first-connection question. You're now at a prompt *on the
server*. (Key permission error? See
[the fix](DEPLOY_ORACLE.md#part-3--connect-from-windows-3-min).)

## 3. A non-root user + firewall (2 minutes of hygiene)

Providers often log you in as **root** (the all-powerful account). Make a
normal user and a firewall first:

```bash
adduser me                    # pick a password; Enter through the questions
usermod -aG sudo me
ufw allow OpenSSH             # keep the door you're using open…
ufw enable                    # …then turn the firewall on (type y)
```

Expected: `Firewall is active and enabled on system startup`. From now on you
can `ssh me@YOUR_IP`. **Don't open any other port** — the recommended
Telegram path dials out and needs none.

## 4. Install (the same one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/SanthoshReddy352/Namma-Agent/main/deploy/install.sh | sudo bash
```

It prints ten numbered steps (packages → swap file on small boxes → code →
venv → **memory embeddings** → UI build → lite config → **access token** →
systemd service) and ends with the token + next steps. Copy the token somewhere
safe.

### About step 5 — memory embeddings (required)

The installer adds [Ollama](https://ollama.com) and pulls `all-minilm`, the
embedding model behind the memory's semantic recall. Without it, memory search
is keyword-only and misses paraphrases — "what is my mother tongue?" never
reaches the stored fact that says *Telugu*.

This step is **required**: if Ollama can't be installed or the model can't be
pulled, the installer stops with instructions rather than leaving you with a
half-working memory.

|  | |
|---|---|
| Disk | ~350 MB (Ollama ~300 MB + the 46 MB model) |
| RAM | ~150 MB resident while serving |
| Speed | ~10 ms per query on 2 cores |
| Cost | none — it never leaves the box |

That fits the 1 GB Oracle reference box beside the agent. Ollama's installer
registers a systemd unit, so it comes back after a reboot with no extra work.

On a box that genuinely cannot run it (air-gapped, or too tight even for
150 MB), opt out explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/SanthoshReddy352/Namma-Agent/main/deploy/install.sh | sudo bash -s -- --no-embeddings
```

Nothing else breaks when you do: recall falls back to BM25 keyword search, the
embedder circuit-breaks after one failed call so a missing endpoint costs
nothing per turn, and Settings → Memory shows **Vector recall: off**. To enable
it later:

```bash
ollama pull all-minilm
```

On a roomier box, `nomic-embed-text` (274 MB, 768-dim, ~500 MB resident)
retrieves better — pull it and set `memory.embeddings.model` in
`namma_agent/config.local.yaml`.

Add your AI key and restart:

```bash
sudo nano /opt/namma-agent/.env       # ANTHROPIC_API_KEY=sk-ant-...  (Ctrl+O, Ctrl+X)
sudo systemctl restart namma-agent
```

## 5. Connect Telegram & verify

Exactly [Parts 6–7 of the Oracle guide](DEPLOY_ORACLE.md#part-6--connect-telegram-5-min-phone-only):
BotFather token + chat id into `.env`, restart, message your bot;
`sudo systemctl status namma-agent`, then the `sudo reboot` acid test.

## 6. Optional: web UI over the internet, properly

Skip this if Telegram covers you (it usually does). Otherwise, don't open
port 8000 raw — give it a domain and TLS with **Caddy** (a web server that
fetches HTTPS certificates automatically):

1. Point a DNS **A record** of your (sub)domain at `YOUR_IP`
   (e.g. `agent.example.com`).
2. Install and configure Caddy:

   ```bash
   sudo apt install -y caddy
   printf 'agent.example.com {\n    reverse_proxy 127.0.0.1:8000\n}\n' | sudo tee /etc/caddy/Caddyfile
   sudo systemctl restart caddy
   ufw allow 80,443/tcp
   ```

3. Open `https://agent.example.com` — the **unlock screen** asks for your
   access token (from the installer / `NAMMA_AUTH_TOKEN` in the server's
   `.env`), remembers it, and everything works — chat, settings, the works —
   over TLS.

Namma itself keeps listening on loopback only; Caddy is the only thing on the
internet. That division of labor is the point.

## Troubleshooting

The [Oracle guide's table](DEPLOY_ORACLE.md#troubleshooting) applies verbatim
(minus the Oracle-console rows). One VPS-specific addition: some providers
ship UFW **enabled with everything closed** — if `ssh` worked but Caddy's
HTTPS doesn't, check `sudo ufw status` opened 80/443.
