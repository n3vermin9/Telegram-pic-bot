#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required: https://docs.docker.com/engine/install/" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Start Docker, then run this script again." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  read -rsp "New Telegram bot token: " bot_token
  echo
  if [[ -z "$bot_token" ]]; then
    echo "Token cannot be empty." >&2
    exit 1
  fi
  umask 077
  printf 'BOT_TOKEN=%s\nLOG_LEVEL=INFO\n' "$bot_token" > .env
  unset bot_token
fi

docker compose up -d --build
docker compose ps
echo "Bot is running and will restart automatically with Docker."
