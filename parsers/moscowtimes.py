import asyncio
from playwright.async_api import async_playwright
import logging
import random
import requests
from utils import (
    fetch_rss,
    is_article_processed,
    mark_article_as_processed,
    publish_to_wordpress,
    clean_text,
    clean_title,
    rewrite_text,
    generate_meta,
    get_wordpress_post_url,
    check_and_crop_image
)

# Логирование
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

# RSS-канал для загрузки
RSS_FEED_URL = "https://www.moscowtimes.ru/rss/news"

# Функция для парсинга страницы
async def parse_page(url):
    """Парсинг страницы The Moscow Times"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Загружаем страницу
            logger.info(f"[INFO] Загружаем страницу: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Получаем title и content
            title = await page.inner_text("header.article__header h1")
            content = await page.inner_text("div.article__content")

            # Попробуем найти изображение с увеличенным таймаутом
            image_url = None
            try:
                # Ожидаем появления элемента с изображением
                await page.wait_for_selector('figure.article__featured-image img', timeout=60000)
                # Если изображение найдено, получаем его атрибут 'src'
                image_url = await page.get_attribute('figure.article__featured-image img', 'src')
                if not image_url:
                    # Если атрибут 'src' отсутствует, пробуем 'srcset'
                    image_url = await page.get_attribute('figure.article__featured-image img', 'srcset')
            except Exception as e:
                # Если изображения нет или ошибка получения, логируем предупреждение
                logger.warning(f"[WARNING] Изображение не найдено или ошибка при получении: {e}")

            # Закрываем браузер
            await browser.close()

            return title, content, image_url
    except Exception as e:
        logger.error(f"[ERROR] Ошибка при парсинге страницы {url}: {e}")
        return None

# Функция для обработки RSS и работы с парсерами
async def process_rss():
    """Обработка RSS для Championat"""
    articles = fetch_rss(RSS_FEED_URL)
    logger.debug(f"[DEBUG] Найдено {len(articles)} статей.")

    if not articles:
        logger.debug("[DEBUG] Нет статей для обработки.")
        return

    # Выбираем случайную статью
    random_article = random.choice(articles)
    link = random_article["link"]

    while True:
        if is_article_processed(link):
            random_article = random.choice(articles)
            link = random_article["link"]
            logger.debug(f"[DEBUG] Статья уже обработана: {link}")
            continue
        break

    parsed_data = await parse_page(link)
    if not parsed_data:
        return

    title, raw_content, image_url = parsed_data
    logger.debug(f"[DEBUG] Заголовок статьи: {title}")

    # Если в RSS есть enclosure (изображение), используем его
    if random_article.get("enclosure"):
        image_url = random_article["enclosure"]

    if not image_url:
        mark_article_as_processed(link)
        return

    # Проверка и обрезка изображения
    image_url = check_and_crop_image(image_url)

    cleaned_content = clean_text(raw_content)

    rewritten_title = rewrite_text(
        f"Заголовок: {title}\n\nТекст: {cleaned_content}",
        "Создай уникальный заголовок на основе следующего текста статьи и исходного заголовка:",
    )
    rewritten_content = rewrite_text(
        cleaned_content,
        "Перепиши этот текст с уникальными формулировками, сохраняя смысл:",
    )

    final_title = clean_title(rewritten_title)

    meta_title, meta_description = generate_meta(final_title, rewritten_content)

    final_meta_title = clean_title(meta_title)

    mark_article_as_processed(link)

    post_id = publish_to_wordpress(
        final_title,
        rewritten_content,
        final_meta_title,
        meta_description,
        "Мировые новости",
        image_url,
    )

    if post_id:
        published_link = get_wordpress_post_url(post_id)

        if published_link:
            logger.info(f"[INFO] Статья опубликована. Ссылка: {published_link}")
            mark_article_as_processed(link)
        else:
            logger.error(f"[ERROR] Не удалось получить URL для поста с ID: {post_id}")
    else:
        logger.error(f"[ERROR] Публикация не удалась для статьи: {final_title}")

# Запуск асинхронной обработки
async def main():
    await process_rss()

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())
