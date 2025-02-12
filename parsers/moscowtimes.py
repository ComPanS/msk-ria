import asyncio
import random
from playwright.async_api import async_playwright
from telegram_bot import send_report
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

PROXY = "http://user215587:rfqa06@163.5.39.69:2966"
RSS_FEED_URL = "https://www.moscowtimes.ru/rss/news"


async def parse_page(url):
    """Асинхронный парсинг страницы The Moscow Times через Playwright с прокси."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy={"server": PROXY})
        page = await browser.new_page()

        try:
            await page.goto(url, timeout=20000)  # Увеличенный таймаут
            await page.wait_for_selector("header.article__header h1", timeout=10000)

            title = await page.locator("header.article__header h1").text_content()
            paragraphs = await page.locator("div.article__content p").all_text_contents()
            content = "\n\n".join(p.strip() for p in paragraphs)

            image_url = None
            image_element = await page.locator("figure.article__featured-image img").first()
            if await image_element.is_visible():
                image_url = await image_element.get_attribute("srcset") or await image_element.get_attribute("src")

        except Exception as e:
            print(f"[ERROR] Ошибка загрузки страницы {url}: {e}")
            return None

        finally:
            await browser.close()

    return title, content, image_url


async def process_rss():
    """Асинхронная обработка RSS для Moscow Times."""
    articles = fetch_rss(RSS_FEED_URL)
    print(f"[DEBUG] Найдено {len(articles)} статей.")

    if not articles:
        print("[DEBUG] Нет статей для обработки.")
        return

    for _ in range(1):
        # Выбираем случайную статью
        random_article = random.choice(articles)
        link = random_article["link"]

        while is_article_processed(link):
            random_article = random.choice(articles)
            link = random_article["link"]
            print(f"[DEBUG] Статья уже обработана: {link}")

        parsed_data = await parse_page(link)
        if not parsed_data:
            return

        title, raw_content, image_url = parsed_data
        print(f"[DEBUG] Заголовок статьи: {title}")

        # Проверка изображения из RSS
        if random_article.get("enclosure"):
            image_url = random_article["enclosure"]

        if not image_url:
            mark_article_as_processed(link)
            continue

        # Обрезка изображения
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
                await send_report("Moscow Times Parser", link, published_link, final_title)
            else:
                print(f"[ERROR] Не удалось получить URL поста с ID: {post_id}")
        else:
            print(f"[ERROR] Публикация не удалась для статьи: {final_title}")

        print()


if __name__ == "__main__":
    asyncio.run(process_rss())
