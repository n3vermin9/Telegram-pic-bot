import asyncio
import html
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message
from PIL import Image, ImageOps, UnidentifiedImageError

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tiktok-sticker-bot")

TIKWM_BASE = "https://www.tikwm.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_STICKER_BYTES = 512 * 1024
MAX_TOP_LEVEL_PAGES = 10
MAX_REPLY_PAGES = 3
MAX_API_REQUESTS = 40
PAGE_SIZE = 20
TIKWM_INTERVAL = 1.5
URL_RE = re.compile(r"https://[^\s<>]+", re.IGNORECASE)
VIDEO_PATH_RE = re.compile(r"/(?:video|v)/(\d+)(?:\.html)?(?:/|$)")
CDN_SUFFIXES = (
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
    "byteimg.com",
    "ibyteimg.com",
    "ibytedtos.com",
    "bytefcdn-oversea.com",
    "muscdn.com",
)

dp = Dispatcher()
job_limit = asyncio.Semaphore(3)


class UserError(Exception):
    pass


@dataclass(frozen=True)
class TikTokTarget:
    video_id: str
    comment_id: str

    @property
    def video_url(self) -> str:
        return f"https://m.tiktok.com/v/{self.video_id}.html"


def host_matches(host: str, suffix: str) -> bool:
    host = host.lower().rstrip(".")
    return host == suffix or host.endswith("." + suffix)


def is_tiktok_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and host_matches(host, "tiktok.com")
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def is_allowed_cdn_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and any(host_matches(host, suffix) for suffix in CDN_SUFFIXES)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def extract_tiktok_url(text: str) -> str:
    for match in URL_RE.findall(text):
        candidate = match.rstrip(".,!?:;)]}'\"")
        if is_tiktok_url(candidate):
            return candidate
    raise UserError("Send a TikTok link copied from the specific sticker comment.")


def _ids_from_url(url: str) -> tuple[str | None, str | None]:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None, None

    query = parse_qs(parsed.query)
    comment_id = None
    for key in ("reply_comment_id", "share_comment_id", "comment_id"):
        value = query.get(key)
        if value and value[0].isdigit():
            comment_id = value[0]
            break

    video_id = None
    value = query.get("share_item_id")
    if value and value[0].isdigit():
        video_id = value[0]
    if not video_id:
        match = VIDEO_PATH_RE.search(parsed.path)
        if match:
            video_id = match.group(1)
    return video_id, comment_id


def target_from_urls(urls: list[str]) -> TikTokTarget | None:
    video_id = None
    comment_id = None
    for url in reversed(urls):
        found_video, found_comment = _ids_from_url(url)
        video_id = video_id or found_video
        comment_id = comment_id or found_comment
        if video_id and comment_id:
            return TikTokTarget(video_id, comment_id)
    return None


def target_from_html(body: str) -> TikTokTarget | None:
    normalized = html.unescape(unquote(body))
    normalized = (
        normalized.replace(r"\u002F", "/")
        .replace(r"\u0026", "&")
        .replace(r"\/", "/")
    )
    comment = re.search(
        r'(?:reply_comment_id|share_comment_id|comment_id)'
        r'(?:\s*[=:]\s*|\s*["\']\s*:\s*["\'])["\']?(\d+)',
        normalized,
    )
    video = re.search(
        r'(?:share_item_id)(?:\s*[=:]\s*|\s*["\']\s*:\s*["\'])'
        r'["\']?(\d+)',
        normalized,
    )
    if not video:
        video = VIDEO_PATH_RE.search(normalized)
    if comment and video:
        return TikTokTarget(video.group(1), comment.group(1))
    return None


async def resolve_target(session: aiohttp.ClientSession, link: str) -> TikTokTarget:
    try:
        async with session.get(
            link,
            allow_redirects=True,
            max_redirects=10,
        ) as response:
            chain = [str(item.url) for item in response.history]
            chain.append(str(response.url))
            target = target_from_urls(chain)
            if target:
                return target

            raw = await response.content.read(1_000_001)
            if len(raw) <= 1_000_000:
                target = target_from_html(raw.decode("utf-8", "replace"))
                if target:
                    return target
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise UserError("TikTok did not resolve this link. Try copying it again.") from exc

    raise UserError(
        "This is not a TikTok comment-share link. "
        "In TikTok, hold the sticker comment and choose Share → Copy link."
    )


class TikwmClient:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def get_page(
        self,
        session: aiohttp.ClientSession,
        path: str,
        params: dict[str, str],
    ) -> dict:
        last_error: Exception | None = None

        for attempt in range(3):
            async with self._lock:
                loop = asyncio.get_running_loop()
                delay = TIKWM_INTERVAL - (loop.time() - self._last_request)
                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    async with session.get(
                        TIKWM_BASE + path,
                        params=params,
                        allow_redirects=False,
                    ) as response:
                        raw = await response.content.read(MAX_JSON_BYTES + 1)
                        status = response.status
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    status = 0
                    raw = b""
                finally:
                    self._last_request = loop.time()

            if len(raw) > MAX_JSON_BYTES:
                raise UserError("The comment service returned too much data.")

            if status == 200:
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    last_error = exc
                else:
                    if payload.get("code") == 0:
                        return payload
                    last_error = RuntimeError(
                        f"comment service error {payload.get('code')}: "
                        f"{payload.get('msg', '')}"
                    )
            elif status not in (0, 429) and status < 500:
                last_error = RuntimeError(f"comment service HTTP {status}")
                break

            if attempt < 2:
                await asyncio.sleep(attempt + 1)

        log.warning("TikWM request failed: %r", last_error)
        raise UserError("The public TikTok comment service is temporarily unavailable.")


tikwm = TikwmClient()


def page_comments(payload: dict) -> list[dict]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    comments = data.get("comments")
    return comments if isinstance(comments, list) else []


def page_cursor(payload: dict) -> int:
    data = payload.get("data")
    if not isinstance(data, dict):
        return 0
    try:
        return int(data.get("cursor", 0))
    except (TypeError, ValueError):
        return 0


def page_has_more(payload: dict) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    return bool(data.get("hasMore", data.get("has_more", False)))


async def find_comment(
    session: aiohttp.ClientSession,
    target: TikTokTarget,
) -> dict:
    budget = MAX_API_REQUESTS
    reply_threads: list[dict] = []

    async def request(path: str, params: dict[str, str]) -> dict:
        nonlocal budget
        if budget <= 0:
            raise UserError("The linked comment is too deep in the discussion.")
        budget -= 1
        return await tikwm.get_page(session, path, params)

    cursor = 0
    for _ in range(MAX_TOP_LEVEL_PAGES):
        payload = await request(
            "/api/comment/list",
            {
                "url": target.video_url,
                "count": str(PAGE_SIZE),
                "cursor": str(cursor),
            },
        )
        for comment in page_comments(payload):
            if str(comment.get("id", comment.get("cid", ""))) == target.comment_id:
                return comment
            try:
                replies = int(comment.get("reply_total", 0))
            except (TypeError, ValueError):
                replies = 0
            if replies > 0:
                reply_threads.append(comment)

        next_cursor = page_cursor(payload)
        if not page_has_more(payload) or next_cursor <= cursor:
            break
        cursor = next_cursor

    for parent in reply_threads:
        parent_id = str(parent.get("id", parent.get("cid", "")))
        if not parent_id:
            continue

        cursor = 0
        for _ in range(MAX_REPLY_PAGES):
            payload = await request(
                "/api/comment/reply",
                {
                    "video_id": target.video_id,
                    "comment_id": parent_id,
                    "count": str(PAGE_SIZE),
                    "cursor": str(cursor),
                },
            )
            for comment in page_comments(payload):
                if str(comment.get("id", comment.get("cid", ""))) == target.comment_id:
                    return comment

            next_cursor = page_cursor(payload)
            if not page_has_more(payload) or next_cursor <= cursor:
                break
            cursor = next_cursor

    raise UserError(
        "I could not find that comment. It may have been deleted or be too old."
    )


def comment_images(comment: dict) -> list[str]:
    raw_images = comment.get("images")
    if not isinstance(raw_images, list):
        return []

    images: list[str] = []
    for item in raw_images:
        if isinstance(item, str) and is_allowed_cdn_url(item):
            images.append(item)
        elif isinstance(item, dict):
            candidates = item.get("url_list") or item.get("urls") or []
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, str) and is_allowed_cdn_url(candidate):
                        images.append(candidate)
                        break
    return list(dict.fromkeys(images))


async def download_image(session: aiohttp.ClientSession, url: str) -> bytes:
    if not is_allowed_cdn_url(url):
        raise UserError("TikTok returned an unsupported sticker address.")

    try:
        async with session.get(url, allow_redirects=True, max_redirects=5) as response:
            redirect_urls = [str(item.url) for item in response.history]
            redirect_urls.append(str(response.url))
            if not all(is_allowed_cdn_url(item) for item in redirect_urls):
                raise UserError("TikTok redirected the sticker to an unsupported host.")
            if response.status != 200:
                raise UserError("TikTok refused the sticker download.")

            length = response.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
                raise UserError("The TikTok sticker is too large.")

            output = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                output.extend(chunk)
                if len(output) > MAX_IMAGE_BYTES:
                    raise UserError("The TikTok sticker is too large.")
            return bytes(output)
    except UserError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise UserError("Could not download the TikTok sticker.") from exc


def make_telegram_sticker(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UserError("TikTok returned an unsupported sticker image.") from exc

    width, height = image.size
    if width < 1 or height < 1:
        raise UserError("TikTok returned an empty sticker image.")

    scale = 512 / max(width, height)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    image = image.resize(size, Image.Resampling.LANCZOS)

    for quality in (95, 88, 80, 70, 60, 48, 36, 24, 12):
        output = io.BytesIO()
        image.save(output, "WEBP", quality=quality, method=6)
        if output.tell() <= MAX_STICKER_BYTES:
            return output.getvalue()

    raise UserError("The converted sticker is larger than Telegram allows.")


async def safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except Exception:
        pass


@dp.message(CommandStart())
@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Send me a TikTok link copied from a sticker comment. "
        "I will fetch the public comment, convert its image to a Telegram "
        "WebP sticker, and send it back. No TikTok login is needed."
    )


@dp.message(F.text)
async def handle_link(message: Message) -> None:
    try:
        link = extract_tiktok_url(message.text or "")
    except UserError as exc:
        await message.answer(str(exc))
        return

    status = await message.answer("Fetching the TikTok comment sticker…")

    async with job_limit:
        timeout = aiohttp.ClientTimeout(total=35, connect=10, sock_read=25)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,image/avif,image/webp,*/*",
        }
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            ) as session:
                target = await resolve_target(session, link)
                comment = await find_comment(session, target)
                images = comment_images(comment)
                if not images:
                    raise UserError("The linked comment does not contain an image sticker.")

                sent = 0
                for image_url in images:
                    try:
                        raw = await download_image(session, image_url)
                        sticker = await asyncio.to_thread(make_telegram_sticker, raw)
                        await message.answer_sticker(
                            BufferedInputFile(sticker, filename="sticker.webp")
                        )
                        sent += 1
                    except UserError as exc:
                        log.info("Skipping one comment image: %s", exc)

                if not sent:
                    raise UserError("The sticker could not be converted.")

            try:
                await status.delete()
            except Exception:
                pass
        except UserError as exc:
            await safe_edit(status, str(exc))
        except Exception:
            log.exception("Unexpected conversion failure")
            await safe_edit(status, "Something went wrong while converting this sticker.")


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN environment variable is required.")

    async with Bot(token=token) as bot:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
