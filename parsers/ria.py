import asyncio
from playwright.async_api import async_playwright
import random
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
)

# RSS-канал для загрузки
RSS_FEED_URL = "https://ria.ru/export/rss2/archive/index.xml"

async def parse_page(url):
    """Парсинг страницы с использованием Playwright"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)  # Запуск в headless-режиме
            page = await browser.new_page()

            # Загружаем страницу
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Получаем title и content
            title_locator = page.locator("div.article__title")
            title = await title_locator.text_content()  # Получаем текст заголовка

            body_locator = page.locator("div.article__body")
            paragraphs = await body_locator.locator("div.article__text").all_text_contents()  # Все параграфы
            content = "\n\n".join(paragraphs)

            # Попробуем найти изображение
            image_url = None
            image_div_locator = page.locator("div.media__size img")
            if await image_div_locator.count() > 0:  # Проверяем, есть ли изображение
                image_url = await image_div_locator.get_attribute("src")  # Получаем URL изображения

            # Закрываем браузер
            await browser.close()

            return title, content, image_url
    except Exception as e:
        print(f"[ERROR] Ошибка при парсинге страницы {url}: {e}")
        return None

async def process_rss():
    """Обработка RSS для RIA"""
    articles = fetch_rss(RSS_FEED_URL)
    print(f"[DEBUG] Найдено {len(articles)} статей.")

    if not articles:
        print("[DEBUG] Нет статей для обработки.")
        return

    for i in range(1):
        # Выбираем случайную статью
        random_article = random.choice(articles)
        link = random_article["link"]

        while True:
            if is_article_processed(link):
                random_article = random.choice(articles)
                link = random_article["link"]
                print(f"[DEBUG] Статья уже обработана: {link}")
                continue
            break

        parsed_data = await parse_page(link)
        if not parsed_data:
            return

        title, raw_content, image_url = parsed_data
        print(f"[DEBUG] Заголовок статьи: {title}")

        # Если в RSS есть enclosure (изображение), используем его
        if random_article.get("enclosure"):
            enclosure = random_article.get("enclosure")
            if "image/jpeg" in enclosure:
                image_url = enclosure

        if not image_url:
            print("[Warning] Статья не опубликована из-за отсутствия изображения")
            mark_article_as_processed(link)
            i -= 1
            continue

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
            "Российские новости",
            image_url,
        )

        if post_id:
            published_link = get_wordpress_post_url(post_id)

            if published_link:
                print(f"[INFO] Статья опубликована. Ссылка: {published_link}")
                mark_article_as_processed(link)
            else:
                print(f"[ERROR] Не удалось получить URL для поста с ID: {post_id}")
        else:
            print(f"[ERROR] Публикация не удалась для статьи: {final_title}")

        print()

# Запуск программы
if __name__ == "__main__":
    asyncio.run(process_rss())
