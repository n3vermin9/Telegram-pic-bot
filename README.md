# TikTok Comment Sticker Bot

A Telegram bot that accepts a link copied from a TikTok sticker comment, finds
the public comment without a TikTok login, converts its image to Telegram's
static WebP sticker format, and sends it back.

## Host on a PC

Install Docker Desktop (Windows/macOS) or Docker Engine with the Compose plugin
(Linux), then clone only this isolated branch:

```bash
git clone --branch tiktok-comment-sticker-bot --single-branch https://github.com/n3vermin9/Telegram-pic-bot.git tiktok-comment-sticker-bot
cd tiktok-comment-sticker-bot
```

On Windows, right-click `start-windows.ps1` and choose **Run with PowerShell**.
On Linux/macOS, run:

```bash
./start-linux.sh
```

The launcher asks for the new bot token once, stores it only in the local
git-ignored `.env` file, builds the container, and starts it with an automatic
restart policy. Use `stop-windows.ps1` or `./stop-linux.sh` to stop it.

## How it works

1. Resolves `vt.tiktok.com` and other TikTok share links.
2. Reads `share_comment_id` and the video ID from TikTok's redirect.
3. Finds the public comment through TikWM's comment mirror, including replies.
4. Downloads the attached sticker image from TikTok's CDN.
5. Resizes it to Telegram's 512-pixel sticker limit and sends a WebP sticker.

Animated TikTok stickers are sent as static stickers using their first frame.
If one comment contains multiple images, the bot sends each as a separate
sticker.

## Run without Docker

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="token from @BotFather"
python bot.py
```

The bot uses long polling, so it does not need a public web server or webhook.

## Configuration

- `BOT_TOKEN` — required Telegram bot token.
- `LOG_LEVEL` — optional Python log level; defaults to `INFO`.

TikWM's public endpoint is rate limited. The bot spaces requests by 1.5 seconds
and limits concurrent jobs. Very old comments outside the scanned pages may not
be found.

## Deploy on Render

Create a Blueprint from this branch:

https://dashboard.render.com/blueprint/new?repo=https://github.com/n3vermin9/Telegram-pic-bot

Select the `tiktok-comment-sticker-bot` branch if prompted, then enter
`BOT_TOKEN` as the worker's secret environment variable.
