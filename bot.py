import asyncio
import logging
import os

from ddgs import DDGS
from aiogram import Bot, Dispatcher
from aiogram.types import InlineQuery, InlineQueryResultPhoto

# Получаем токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не найдена!")

# Включаем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def search_images(query: str, max_results: int = 15) -> list[dict]:
    """Синхронный поиск изображений через DuckDuckGo."""
    results = []

    try:
        with DDGS() as ddgs:
            ddg_results = ddgs.images(
                query=query,
                region="wt-wt",
                safesearch="off",
                max_results=max_results,
            )

            if ddg_results:
                for item in ddg_results:
                    img_url = item.get("image")
                    thumb_url = item.get("thumbnail") or img_url

                    if img_url and img_url.startswith("http"):
                        results.append(
                            {
                                "image": img_url,
                                "thumbnail": thumb_url,
                                "title": item.get("title", "Изображение"),
                            }
                        )

    except Exception as e:
        logger.error(f"Ошибка при поиске изображений: {e}")

    return results


@dp.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    query_text = inline_query.query.strip()

    logger.info(
        f"--> Входящий инлайн-запрос от @{inline_query.from_user.username}: '{query_text}'"
    )

    if not query_text:
        await inline_query.answer(results=[], cache_time=1)
        return

    loop = asyncio.get_running_loop()
    images = await loop.run_in_executor(None, search_images, query_text, 15)

    logger.info(f"<-- Найдено изображений: {len(images)}")

    results = []

    for idx, img in enumerate(images):
        results.append(
            InlineQueryResultPhoto(
                id=str(idx),
                photo_url=img["image"],
                thumbnail_url=img["thumbnail"],
                title=img["title"],
                caption="@unvsual",
            )
        )

    try:
        await inline_query.answer(results=results, cache_time=60)
    except Exception as e:
        logger.error(f"Ошибка отправки результатов: {e}")


async def main():
    logger.info("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())