# Messaging gateways on a server

Which channel should your always-on agent talk through, and what does each one
demand of the box? This is the deployment view; the field-by-field credential
walkthroughs live in [COMMS.md](COMMS.md), and what senders are *allowed* to
do is the [trust model](COMMS.md#trust-levels--who-is-allowed-to-do-what).

## The at-a-glance table

| Channel | Needs a public URL? | Default trust | OK on the 1 GB box? | Verdict for servers |
|---|---|---|---|---|
| **Telegram** ★ | **No** (dials out) | `owner` (pinned chat id) | ✅ tiny | **Start here.** |
| Signal | No (local signal-cli REST) | `owner` (pinned number) | ⚠ the signal-cli service is Java — heavy for 1 GB | Fine on 2 GB+ boxes. |
| Discord (bot) | No (bot dials out) | `trusted` | ✅ | Good second channel. |
| Slack (Socket Mode) | No (dials out) | `untrusted` | ✅ | Use Socket Mode, not the webhook. |
| Slack (Events webhook) | **Yes** | `untrusted` | ✅ | Needs TLS + exposure — prefer Socket Mode. |
| WhatsApp (Cloud API) | **Yes** (Meta webhook) | `untrusted` | ✅ | Only if you really live in WhatsApp. |
| WhatsApp (QR link) | No (dials out) | `untrusted` | ⚠ heavier session | Unofficial / ToS risk — see COMMS.md. |

"Dials out" means the *server opens the connection* to the platform — your box
needs **no open ports, no domain, no TLS**, and there is nothing exposed to
attack. That's why Telegram is the recommended default everywhere in these
guides.

## Telegram, with the exact taps (~5 min)

1. **Create the bot.** In Telegram search **@BotFather** (the verified one) →
   **Start** → send `/newbot` → it asks for a display name (e.g. `My Namma`) →
   then a username ending in `bot` (e.g. `santhu_namma_bot`). It replies with
   the **HTTP API token**: `123456789:AAF...` — tap it to copy.
2. **Get your chat id.** Search **@userinfobot** → **Start** → it replies with
   `Id: 123456789`. That number pins the bridge to *you* (anyone else who
   finds the bot is ignored — this is what makes the channel `owner` trust).
3. **Give both to the agent.** On a server:

   ```bash
   sudo nano /opt/namma-agent/.env
   # add:
   #   NAMMA_TELEGRAM_TOKEN=123456789:AAF...
   #   NAMMA_TELEGRAM_CHAT_ID=123456789
   sudo systemctl restart namma-agent
   ```

   (On a desktop install: Settings → Messaging → Telegram, paste both, then
   Gateway → **Start**.)
4. **Talk to it.** Open your bot's chat, send *"hi"*. It answers. Voice notes
   work too when an STT key is configured.

## Choosing more channels

Add a second channel only when you actually need it — every channel is
surface area (that's a [deliberate position](WHY_NAMMA.md)). When you do:
Discord's bot dials out and is a comfortable `trusted` family/server channel;
Slack's Socket Mode brings the agent into a workspace without exposure —
remember every workspace member can then talk to it, which is exactly what
the `untrusted` default is for.

If a channel *must* receive webhooks (WhatsApp Cloud API, Slack Events),
you need the [VPS guide's Caddy step](DEPLOY_VPS.md#6-optional-web-ui-over-the-internet-properly)
for a TLS URL, and the security checklist in [DEPLOY.md](DEPLOY.md) stops
being optional.
