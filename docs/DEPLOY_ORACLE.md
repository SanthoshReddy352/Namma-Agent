# Your own always-on agent for $0 — Oracle Cloud free tier, from zero

This walkthrough assumes you have **never opened a cloud console**, don't know
what SSH is, and use Windows at home. Follow it top to bottom (~30 minutes);
at the end you'll message your agent from your phone and it will answer — from
a little server that runs forever and costs nothing.

> **What you're making:** Oracle gives everyone a small **Always Free** virtual
> machine — the `VM.Standard.E2.1.Micro` (1 GB RAM). *Always Free* means it
> never expires and never bills. We picked this shape on purpose over the
> bigger ARM one: the ARM shape is famously "out of capacity" almost
> everywhere, while the E2.1.Micro is actually obtainable — and Namma is sized
> to run healthy in its 1 GB (the AI brain is an API call, not a local model).

---

## Part 1 — Create the Oracle Cloud account (~10 min)

1. Go to **signup.oraclecloud.com** and fill in the form.
2. **Card verification:** Oracle asks for a credit/debit card to prove you're
   a person. *Always Free resources never charge it.* You may see a small
   temporary hold (~$1) that disappears in a few days.
3. **Home region — this matters.** Pick the region *nearest to you* (e.g.
   India → Hyderabad or Mumbai). **It can never be changed later**, and your
   free VM must live in your home region.
   - *If you see "region at capacity" during signup → pick the next-nearest
     region instead.*
4. Finish signup and sign in. You land on the **Oracle Cloud console** — the
   web dashboard where you make cloud things.

## Part 2 — Create the VM (~5 min of clicking)

An **instance** is Oracle's word for a virtual machine — your server.

1. In the console, click the **☰ menu** (top-left) → **Compute** → **Instances**.
2. Click **Create instance**.
3. **Name:** `namma-agent` (anything works).
4. **Image and shape** — click **Edit**:
   - **Image:** click **Change image** → pick **Ubuntu** → *Canonical Ubuntu
     22.04* (or newer, *not* "Minimal").
   - **Shape:** click **Change shape** → **Specialty and previous generation**
     → tick **VM.Standard.E2.1.Micro** — it's labeled **Always Free-eligible**.
   - *If you don't see the Always Free label → you're in the wrong
     region/compartment; use the region picker (top bar) to go to your home
     region.*
5. **Networking:** leave the defaults ("Create new virtual cloud network").
   Make sure **Assign a public IPv4 address** is set to **Yes**.
6. **Add SSH keys** — SSH is the remote-control connection to your server, and
   this key pair is its password:
   - Choose **Generate a key pair for me** → click **Download private key**.
   - The file (e.g. `ssh-key-2026-07-19.key`) lands in your **Downloads**.
     **Keep it — without it you can never log in.**
7. Click **Create**. In ~1 minute the instance turns green (**Running**).
8. Copy the **Public IP address** shown on the instance page — that's your
   server's address on the internet. Write it down; the steps below call it
   `YOUR_IP`.
   - *Stuck on Provisioning → wait 2 minutes and refresh. "Out of capacity"
     (rare for this shape) → try again choosing a different Availability
     Domain (AD-1/AD-2/AD-3) in step 4.*

## Part 3 — Connect from Windows (~3 min)

Windows 10/11 has SSH **built in** — no PuTTY needed.

1. Open **PowerShell** (Start menu → type "powershell" → Enter).
2. Fix the key's permissions (Windows makes downloaded files too open; SSH
   refuses keys other accounts could read — you WILL hit this, so do it now):

   ```powershell
   icacls "$env:USERPROFILE\Downloads\ssh-key-2026-07-19.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"
   ```

   (Use your real key filename. Expected output: `processed file: …`.)
3. Connect (replace `YOUR_IP`):

   ```powershell
   ssh -i "$env:USERPROFILE\Downloads\ssh-key-2026-07-19.key" ubuntu@YOUR_IP
   ```

   - First time it asks *"are you sure you want to continue connecting?"* —
     type `yes` and Enter.
   - You now see a **prompt** like `ubuntu@namma-agent:~$` — a command line
     *on your server*. Everything you type here runs there, not on your PC.
   - *"Permission denied (publickey)" → wrong key file or you typed `root@`
     instead of `ubuntu@`. "Connection timed out" → wrong IP, or the instance
     isn't Running.*

## Part 4 — Install Namma Agent (one paste, ~5–10 min)

Paste this at the server prompt and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/SanthoshReddy352/Namma-Agent/main/deploy/install.sh | sudo bash
```

What you'll see, step by step (it prints `== 1/10 …` through `== 10/10 …`):
system packages, then **a 2 GB swap file** (borrowed disk that acts as
overflow memory — the 1 GB box's survival step; the UI build leans on it),
the code, Python packages, **the memory embedding model** (Ollama + the 46 MB
`all-minilm` — this is what lets the agent recall things you phrase
differently later; it's installed for you and the install stops if it fails),
the web UI build (the slowest part — a few minutes; it's fine), a
memory-friendly config profile, a generated **access token**, and a **systemd
service** (Ubuntu's "keep this program running and restart it after reboots"
manager).

At the end it prints:

```
  Access token (also in /opt/namma-agent/.env — you need it if you expose the web UI):
      <long random string>
```

**Copy that token somewhere safe** (you only need it if you later open the
web UI to the internet — the phone-messaging path below doesn't use it).

Then add your AI provider key:

```bash
sudo nano /opt/namma-agent/.env
```

Add a line like `ANTHROPIC_API_KEY=sk-ant-...` (or your OpenAI/Google key —
whichever provider `namma_agent/config.yaml` names). Save with **Ctrl+O**,
Enter, exit with **Ctrl+X**, then:

```bash
sudo systemctl restart namma-agent
```

## Part 5 — About Oracle's TWO firewalls (read, probably skip)

A **firewall** decides which network doors (ports) of your server are open.
Oracle has **two**: the **Security List** in the console (cloud-side) *and*
`iptables` on the box itself (Ubuntu-side). Both must open a port before the
internet can reach it.

**You almost certainly need NEITHER.** The recommended setup — Telegram, next
part — *dials out* from the server, so **no ports open at all**: nothing
exposed, nothing to attack. Only if you someday want the web UI over the
internet do you open port 8000 in *both* layers — and set the access token
first, and prefer an SSH tunnel instead:
`ssh -i <key> -L 8000:localhost:8000 ubuntu@YOUR_IP` → open
http://localhost:8000 on your PC (no open ports, full UI, the token unlock
screen appears once).

## Part 6 — Connect Telegram (~5 min, phone only)

Full details in [GATEWAYS.md](GATEWAYS.md); the short version:

1. In Telegram, search **@BotFather** → send `/newbot` → pick a name and a
   username. BotFather replies with a **bot token** (`123456:ABC-...`).
2. Search **@userinfobot** → press Start → it replies with your numeric
   **chat id**.
3. On the server:

   ```bash
   sudo nano /opt/namma-agent/.env
   ```

   add:

   ```
   NAMMA_TELEGRAM_TOKEN=123456:ABC-your-token
   NAMMA_TELEGRAM_CHAT_ID=your-chat-id
   ```

   save, exit, then `sudo systemctl restart namma-agent`.
4. Message your bot on Telegram: *"hello — what can you do?"*
   **It answers. That's your agent, always on, $0/month.**

Because the bridge is pinned to *your* chat id, it runs at `owner` trust —
see [COMMS.md](COMMS.md#trust-levels--who-is-allowed-to-do-what).

## Part 7 — Verify & celebrate

```bash
sudo systemctl status namma-agent     # expect: Active: active (running)
curl -s http://127.0.0.1:8000/api/health   # expect: {"ok":true}
sudo reboot                           # the acid test
```

The reboot kicks you off SSH — wait ~2 minutes, message the bot again: it
answers **by itself**, because the service auto-starts. Done.

**Keep-alive facts:** the E2.1.Micro is *not* idle-reclaimed (that's the ARM
shape's rule) — it just runs. The free network allowance (10 TB/month) is
thousands of times more than a chat workload uses.

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| "Out of capacity" creating the VM | Rare for E2.1.Micro. Try another Availability Domain, or later in the day. |
| SSH times out | Wrong IP, or instance not Running. Check the instance page. |
| SSH "permission denied" | Key permissions (Part 3 step 2) or `root@` instead of `ubuntu@`. |
| Bot silent | Token/chat-id typo in `.env` (no quotes, no spaces) → fix, `sudo systemctl restart namma-agent`. Check `sudo journalctl -u namma-agent -n 50`. |
| Bot replies "provider error" | Missing/wrong AI provider key in `.env`. |
| Service dead after a busy day / OOM in logs | Swap missing (`swapon --show` empty?) → re-run the installer; it re-creates it. |
| Web UI unreachable from your PC | That's the default (nothing exposed). Use the SSH tunnel from Part 5. |
