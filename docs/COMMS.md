# Messaging / Comms Setup Guide

Connect your assistant to chat platforms so it can **send you notifications** and —
on most channels — **reply to your messages** from your phone.

Everything here is optional. Set up only the channel(s) you want; the rest stay off.
All credentials are entered in the app under **Settings → Messaging**, then saved and
started from the **Gateway** control on that same tab. Behind the scenes they're stored
in the project's `.env` file (the environment-variable name for each field is shown in
`code`).

> **Tip:** Telegram is the easiest to start with — about two minutes, no public URL, and
> full two-way chat.

---

## What each channel can do

| Channel  | Outbound (notify) | Two-way (chat back) | Needs a public URL? |
|----------|:-----------------:|:-------------------:|---------------------|
| Telegram | ✅ | ✅ (polling)              | No                  |
| Signal   | ✅ | ✅ (polling)              | No (local signal-cli) |
| Discord  | ✅ | ✅ (bot / Gateway)        | No (bot dials out)  |
| Slack    | ✅ | ✅ (Socket Mode, or webhook) | No with Socket Mode; yes for the webhook path |
| WhatsApp | ✅ | ✅ (webhook)              | Yes, for inbound    |

- **Outbound** works as soon as the credentials are saved — ask your assistant to
  "send a test notification."
- **Two-way (inbound)** also requires starting the **Gateway** (Settings → Messaging →
  **Start**). Telegram, Signal, the **Discord bot**, and **Slack Socket Mode** all dial
  *out*, so they work fully locally — no public URL. Only the Slack **webhook** path and
  WhatsApp need your server reachable from the internet (see
  [Exposing your server](#exposing-your-server-for-sl--whatsapp-inbound)).
- **A webhook is send-only.** Discord/Slack *incoming webhooks* can post notifications but
  can never *receive* a message — that's why two-way Discord needs a **bot** and local
  two-way Slack needs **Socket Mode** (an app-level token), not just the webhook URL.

---

## Telegram

**Fields:** Bot token (`NAMMA_TELEGRAM_TOKEN`), Chat id (`NAMMA_TELEGRAM_CHAT_ID`)

1. In Telegram, open **[@BotFather](https://t.me/BotFather)** and send `/newbot`.
   Follow the prompts (a display name, then a unique username ending in `bot`).
2. BotFather replies with a **bot token** like `123456789:AAH...`.
   → paste it into **Bot token** (`NAMMA_TELEGRAM_TOKEN`).
3. **Message your new bot once** (send it any text). A bot can't message you until you've
   started a chat with it.
4. Get your **chat id** — either:
   - Message **[@userinfobot](https://t.me/userinfobot)**; it replies with your numeric id, **or**
   - Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and find
     `"chat":{"id":123456789}`.

   → paste the number into **Chat id** (`NAMMA_TELEGRAM_CHAT_ID`).

With both set, your assistant sends notifications **and** you can chat with it from your
phone (commands like `/new`, `/mode`, `/model` work in-chat).

---

## Signal

**Fields:** API URL (`NAMMA_SIGNAL_API_URL`), Sender number (`NAMMA_SIGNAL_NUMBER`),
Recipient / group id (`NAMMA_SIGNAL_RECIPIENT`)

Signal has no public bot API, so you run a small local bridge —
[`signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api).

1. **Run the bridge** (Docker is easiest):
   ```bash
   docker run -d --name signal-api -p 8080:8080 \
     -v $HOME/.local/share/signal-cli:/home/.local/share/signal-cli \
     bbernhard/signal-cli-rest-api
   ```
   → **API URL** = `http://localhost:8080` (`NAMMA_SIGNAL_API_URL`).
2. **Register a number** with the bridge. The simplest path is to **link** it as a second
   device to an existing Signal account: open
   `http://localhost:8080/v1/qrcodelink?device_name=namma` and scan the QR from
   Signal → *Settings → Linked devices*. (You can also register a fresh number — see the
   project's README.) The registered number in **E.164** (e.g. `+919876543210`) goes in
   **Sender number** (`NAMMA_SIGNAL_NUMBER`).
3. **Recipient / group id** — the number you want it to talk to in E.164, **or** a Signal
   group id → **Recipient / group id** (`NAMMA_SIGNAL_RECIPIENT`).

With these set, your assistant both sends **and** replies to Signal messages (polling — no
public URL needed).

---

## Slack

**Fields:** Webhook URL (`NAMMA_SLACK_WEBHOOK_URL`),
*(two-way, local)* App token (`NAMMA_SLACK_APP_TOKEN`) + Bot token (`NAMMA_SLACK_BOT_TOKEN`),
*(two-way, public-URL alternative)* Signing secret (`NAMMA_SLACK_SIGNING_SECRET`)

1. Go to **[api.slack.com/apps](https://api.slack.com/apps)** → **Create New App** →
   **From scratch**. Name it and pick your workspace.
2. **Outbound:** open **Incoming Webhooks** → toggle **On** → **Add New Webhook to
   Workspace** → choose a channel → **Allow**. Copy the URL (`https://hooks.slack.com/services/...`)
   → **Webhook URL** (`NAMMA_SLACK_WEBHOOK_URL`). This alone enables notifications.
3. **For two-way replies — Socket Mode (recommended; works locally, no public URL):**
   - **Socket Mode** → toggle **On**. This generates an **app-level token** (`xapp-…`) with
     `connections:write` → **App token** (`NAMMA_SLACK_APP_TOKEN`).
   - **OAuth & Permissions** → add the **`chat:write`** bot scope → **Install to Workspace**
     → copy the **Bot User OAuth Token** (`xoxb-…`) → **Bot token** (`NAMMA_SLACK_BOT_TOKEN`).
   - **Event Subscriptions** → toggle **On** and subscribe to bot message events
     (`message.channels` for channels, `message.im` for DMs). With Socket Mode on, Slack
     delivers these over the websocket — **no Request URL needed**.
   - Invite the bot to the channel (`/invite @YourApp`), then start the Gateway.
4. **Alternative — HTTP Events API (needs a public URL):** instead of Socket Mode, copy the
   **Signing Secret** from **Basic Information** → `NAMMA_SLACK_SIGNING_SECRET`, and under
   **Event Subscriptions** set the **Request URL** to `https://<your-public-host>/webhooks/slack`.
   Used only when no app-level token is set.

---

## WhatsApp

**Fields:** Access token (`NAMMA_WHATSAPP_TOKEN`), Phone number id
(`NAMMA_WHATSAPP_PHONE_ID`), Recipient (`NAMMA_WHATSAPP_TO`),
*(optional, for two-way)* Verify token (`NAMMA_WHATSAPP_VERIFY_TOKEN`)

Uses the **WhatsApp Cloud API** from Meta.

1. At **[developers.facebook.com](https://developers.facebook.com/)** → **My Apps** →
   **Create App** → add the **WhatsApp** product.
2. Open **WhatsApp → API Setup**:
   - Copy the **Temporary access token** → **Access token** (`NAMMA_WHATSAPP_TOKEN`).
     For long-term use, generate a permanent token via a **System User** in Business
     Settings (the temporary one expires in ~24h).
   - Copy the **Phone number ID** (the sender) → **Phone number id**
     (`NAMMA_WHATSAPP_PHONE_ID`). Until you register your own number, Meta provides a test
     sender number.
3. **Recipient** — your phone number in **E.164 digits only**, e.g. `919876543210`
   (no `+`, no spaces) → **Recipient** (`NAMMA_WHATSAPP_TO`). Add it to the allowed
   recipients in the API Setup page first, or messages won't deliver.
4. **For two-way replies:**
   - Choose any string as your **verify token** and put the same value in **Verify token**
     (`NAMMA_WHATSAPP_VERIFY_TOKEN`).
   - In the app's **Configuration → Webhooks**, set the callback URL to
     `https://<your-public-host>/webhooks/whatsapp` and the verify token to the same
     string. Subscribe to `messages`. Inbound requires a publicly reachable server.

---

## Discord

**Fields:** Webhook URL (`NAMMA_DISCORD_WEBHOOK_URL`) — outbound;
*(two-way)* Bot token (`NAMMA_DISCORD_BOT_TOKEN`),
*(optional)* Channel id (`NAMMA_DISCORD_CHANNEL_ID`)

**Outbound (notifications only):**
1. In your Discord server, open a channel's **settings (gear icon)** →
   **Integrations** → **Webhooks** → **New Webhook**.
2. Pick the target channel, optionally rename it, then **Copy Webhook URL**
   (`https://discord.com/api/webhooks/...`)
   → paste into **Webhook URL** (`NAMMA_DISCORD_WEBHOOK_URL`).

**Two-way (receive + reply) — needs a bot, because a webhook is send-only.** The bot
connects to the Discord Gateway over a websocket and dials *out*, so it works locally
(no public URL):
1. **[discord.com/developers](https://discord.com/developers/applications)** → **New
   Application** → name it → **Bot** (left nav) → **Reset Token** → **Copy** →
   **Bot token** (`NAMMA_DISCORD_BOT_TOKEN`).
2. On the same **Bot** page, under **Privileged Gateway Intents**, enable
   **MESSAGE CONTENT INTENT** (without it, incoming message text arrives empty).
3. **OAuth2 → URL Generator** → scopes **`bot`**, bot permissions **View Channels** +
   **Send Messages** → open the generated URL → add the bot to your server.
4. *(Optional)* To restrict the assistant to one channel, enable Developer Mode
   (User Settings → Advanced), right-click the channel → **Copy Channel ID** →
   **Channel id** (`NAMMA_DISCORD_CHANNEL_ID`). Leave blank to listen everywhere the
   bot can see.
5. Start the Gateway (Settings → Messaging → **Start**).

Discord is send-only here — your assistant posts notifications, but doesn't read replies.

---

## Turning it on

1. Enter credentials in **Settings → Messaging** and click **Save**.
2. On the **Gateway** control at the top of that tab, click **Start**.
   - Configured channels are listed; Telegram and Signal begin polling immediately.
   - Editing a token later? Click **Save**, then **Stop** and **Start** so the gateway
     reloads it (no app restart needed).
3. Test outbound by asking your assistant to **"send a test notification."**

The Gateway governs only the **inbound** side. Outbound notifications work whether or not
the gateway is running.

---

## Reference: environment variables

| Field                     | Variable                      | Channel  | Required for |
|---------------------------|-------------------------------|----------|--------------|
| Bot token                 | `NAMMA_TELEGRAM_TOKEN`        | Telegram | out + in     |
| Chat id                   | `NAMMA_TELEGRAM_CHAT_ID`      | Telegram | outbound     |
| API URL                   | `NAMMA_SIGNAL_API_URL`        | Signal   | out + in     |
| Sender number             | `NAMMA_SIGNAL_NUMBER`         | Signal   | out + in     |
| Recipient / group id      | `NAMMA_SIGNAL_RECIPIENT`      | Signal   | outbound     |
| Webhook URL               | `NAMMA_SLACK_WEBHOOK_URL`     | Slack    | outbound     |
| App token (xapp-)         | `NAMMA_SLACK_APP_TOKEN`       | Slack    | inbound (Socket Mode) |
| Bot token (xoxb-)         | `NAMMA_SLACK_BOT_TOKEN`       | Slack    | inbound replies |
| Signing secret            | `NAMMA_SLACK_SIGNING_SECRET`  | Slack    | inbound (webhook path) |
| Access token              | `NAMMA_WHATSAPP_TOKEN`        | WhatsApp | out + in     |
| Phone number id           | `NAMMA_WHATSAPP_PHONE_ID`     | WhatsApp | out + in     |
| Recipient                 | `NAMMA_WHATSAPP_TO`           | WhatsApp | outbound     |
| Verify token              | `NAMMA_WHATSAPP_VERIFY_TOKEN` | WhatsApp | inbound      |
| Webhook URL               | `NAMMA_DISCORD_WEBHOOK_URL`   | Discord  | outbound     |
| Bot token                 | `NAMMA_DISCORD_BOT_TOKEN`     | Discord  | inbound (two-way) |
| Channel id                | `NAMMA_DISCORD_CHANNEL_ID`    | Discord  | inbound (optional) |

`NAMMA_*` variable names are stable identifiers — don't rename them. You can also set these
directly in `.env` instead of the UI; shell environment variables take precedence over
`.env` at runtime. A template lives in [`namma_agent/.env.example`](../namma_agent/.env.example).

---

## Exposing your server (for Slack / WhatsApp inbound)

Webhook channels need Slack/Meta to reach your machine. For a quick local setup, tunnel
your server (default `http://127.0.0.1:8000`) with a tool like
[ngrok](https://ngrok.com/):

```bash
ngrok http 8000
```

Use the resulting `https://<random>.ngrok.app` host in the callback URLs above
(`…/webhooks/slack`, `…/webhooks/whatsapp`). For always-on use, deploy the server to a host
with a stable public HTTPS URL instead.

---

## Notes on formatting

- **E.164** phone format = `+` `<country code>` `<number>`, e.g. `+919876543210`.
  Signal keeps the leading `+`; WhatsApp's **Recipient** field wants **digits only**
  (`919876543210`).
- **E.164** group ids for Signal are the raw group identifier from your signal-cli setup.
