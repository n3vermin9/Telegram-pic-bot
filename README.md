# TikTok Comment Sticker Bot

A Telegram bot that accepts a link copied from a TikTok sticker comment, finds
the public comment without a TikTok login, converts its image to Telegram's
static WebP sticker format, and sends it back.

## How it works

1. Resolves `vt.tiktok.com` and other TikTok share links.
2. Reads `share_comment_id` and the video ID from TikTok's redirect.
3. Finds the public comment through TikWM's comment mirror, including replies.
4. Downloads the attached sticker image from TikTok's CDN.
5. resizes it to Telegram's 512-pixel sticker limit and sends a WebP sticker.

Animated TikTok stickers are currently sent as a static sticker using their
first frame. If one comment contains multiple images, the bot sends each one as
a separate sticker.

## Run

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="token from @BotFather"
python bot.py
```

The bot uses long polling, so it does not need a public web server or webhook.

## Docker

```bash
docker build -t tiktok-comment-sticker-bot .
docker run --rm -e BOT_TOKEN="token from @BotFather" tiktok-comment-sticker-bot
```

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
`BOT_TOKEN` as the worker's secret environment variable. The token is never
stored in this repository.
