# Sf2AiS (aka: AI-Gateway-FTP) — Secure Files to AI Server 🤖📂

A password-protected, self-hosted bridge that lets web-browsing AI chatbots
(ChatGPT, Claude, Gemini, Copilot, etc.) securely browse, read, and download
files from your own computer or home server — no API keys or MCP support
required.

## What you get

- A guided, glassmorphism-themed **setup wizard** — no config files to hand-edit
- **Password-complexity enforcement** on every account (12+ chars, mixed case,
  number, special character)
- Support for a **custom domain**, **dynamic DNS**, a **static IP**, or your
  **current IP with an auto-updating probe** (works on Windows, macOS, Linux)
- A **live dashboard**: online/offline status, your current shareable link,
  and which logins are actively connected
- **Multiple shares**: give different folders their own separate
  username/password pairs, added anytime from the dashboard

## Running it

### With Python
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### With Docker
```bash
docker-compose up -d
```
If you plan to share folders that live elsewhere on your host machine, add a
volume line for each one in `docker-compose.yml` before starting the wizard
(see the comments in that file).

Then open `http://localhost:8000` (or your server's address) in a browser.

## First-run walkthrough

1. **Welcome screen** — Sf2AiS branding, one click to begin.
2. **Dashboard login** — choose the username/password *you* will use to manage
   the server. Must meet the password policy (checked live as you type).
3. **Network setup** — tell it how your AI will reach this machine:
   - **Custom domain** — you already point a domain here
   - **Dynamic DNS** — you use a DuckDNS/No-IP style hostname
   - **Static IP** — your public IP never changes
   - **Current IP + probe** (recommended if you're not sure) — Sf2AiS gives you
     a small script for whichever computer stays on; it checks your public IP
     every 5 minutes and updates your link automatically if it changes.
4. **Choose folders** — add one or more folders to share. Each one
   automatically gets its own generated username and password, shown once on
   the finish screen — save them!
5. **Dashboard** — shows your live shareable link, an online/offline status
   badge, a table of all shares with connection status, and a **+ Add Share**
   button to create more username/password pairs for additional folders at
   any time.

## The IP probe

Installers for Windows/macOS/Linux IP update probe ships as a small cross-platform
**Python script** instead — it works identically on all three, you just point
it at your gateway and schedule it:

- **Windows** — Task Scheduler, "repeat every 5 minutes"
- **macOS / Linux** — a `cron` entry (`*/5 * * * * python3 /path/to/probe.py`)

Full instructions are generated for you on the dashboard once you choose the
"current IP" option.

## Security notes

- Every password (yours and each share's) is hashed with bcrypt — plaintext is
  never stored, other than the auto-generated share passwords shown once on
  the finish screen.
- **Use HTTPS in production.** Basic Auth sends credentials on every request —
  put this behind a TLS-terminating reverse proxy (Caddy, nginx, Cloudflare
  Tunnel) rather than exposing plain HTTP directly, especially for the static
  IP / current-IP options.
- Anyone with a share's username/password can read every file in that share's
  folder — only add folders you're comfortable to an external AI service reading.
- Path traversal protection is included, but this project hasn't had a
  professional security audit — use it at your own risk on a home server.
- To reset your dashboard login or start over, stop the server and delete
  `data/config.json`, then restart.

#Licence: 🤖📂

[![License: Sf2AiS v1.0](https://shields.io)](LICENSE.md)
[![GitHub Sponsor](https://shields.io)](https://github.com)

An open-source-style, source-available secure file gateway...

...

## ⚖️ License

This project is licensed under the **Sf2AiS Noncommercial License v1.0**. 

* **Hobbyists, Students, and Home Labs:** 100% Free to use, modify, and distribute for personal or educational purposes.
* **Commercial Entities / Monetization:** Any commercial use, SaaS bundling, or monetization requires written permission from the copyright holder (Wayne).

See the full terms in [LICENSE.md](LICENSE.md). For commercial licensing inquiries, please open an issue or contact the maintainer directly.
