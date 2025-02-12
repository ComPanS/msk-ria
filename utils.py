import sqlite3
import requests
import xml.etree.ElementTree as ET
from config import DB_NAME, WP_URL, WP_USERNAME, WP_PASSWORD, openai_api_key
from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import NewPost
from wordpress_xmlrpc.methods.media import UploadFile
from wordpress_xmlrpc.methods.posts import GetPost
from wordpress_xmlrpc.methods.posts import NewPost
from wordpress_xmlrpc.methods.taxonomies import GetTerms
import re
import time
import asyncio
import logging
import urllib3
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright


# Настройка прокси с авторизацией
PROXY = {
    "http": "http://user215587:rfqa06@163.5.39.69:2966",
    "https": "http://user215587:rfqa06@163.5.39.69:2966",
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Для обрезки фото
# from PIL import Image
# import pytesseract
import requests
from io import BytesIO

wp_client = Client(WP_URL, WP_USERNAME, WP_PASSWORD)


def setup_database():
    """Создание таблицы для хранения обработанных статей"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()


def is_article_processed(link):
    """Проверка, была ли статья уже обработана"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_articles WHERE link = ?", (link,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def mark_article_as_processed(link):
    """Пометка статьи как обработанной"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO processed_articles (link) VALUES (?)", (link,)
    )
    conn.commit()
    conn.close()


def fetch_rss(rss_url):
    """Получение и разбор RSS"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }
    logging.info(f"Загружаем RSS с URL: {rss_url}")
    response = requests.get(rss_url, headers=headers, proxies=PROXY)
    time.sleep(1)
    if response.status_code != 200:
        logging.error(f"Ошибка загрузки RSS: {response.status_code}")
        return []

    root = ET.fromstring(response.content)

    return [
        {
            "title": item.find("title").text,
            "link": item.find("link").text,
            "enclosure": (
                item.find("enclosure").attrib.get("url")
                if item.find("enclosure") is not None
                else None
            ),
            "pubDate": item.find("pubDate").text,
        }
        for item in root.findall(".//item")
    ]


def clean_text(content):
    """
    Убирает первое предложение:
    - Заканчивающееся на 'РИА Новости'.
    - Формата 'ГОРОД, дата (Рейтер) —'.
    """
    match_ria = re.match(r"^[^.!?]*?РИА Новости[.!?]", content)
    if match_ria:
        content = content[match_ria.end() :].strip()

    match_reuters = re.match(
        r"^[^.!?]*?[А-ЯЁ][а-яё]+, \d{1,2} \w+ \(Рейтер\) —", content
    )
    if match_reuters:
        content = content[match_reuters.end() :].strip()

    return content


def clean_title(title):
    """
    Очищает заголовки:
    - Убирает кавычки
    """
    title = title.replace("Заголовок: ", "").strip()
    title = title.replace("**Заголовок:**", "").strip()
    title = title.replace("**", "").strip()
    title = title.replace('"', "").replace("'", "").strip()
    return title


def rewrite_text(text, prompt):
    import openai

    openai.api_key = openai_api_key

    try:
        logging.info(f"Начинаем рерайт текста с подсказкой: {prompt}")
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "system", "content": "You are a helpful assistant."},
                      {"role": "user", "content": f"{prompt}\n\n{text}"}],
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Ошибка рерайта текста: {e}")
        return text


def generate_meta(title, content):
    """Генерация SEO мета-тегов"""
    meta_title = rewrite_text(title, "Создай короткий SEO-заголовок:")
    meta_description = rewrite_text(content, "Создай описание длиной до 160 символов:")
    return meta_title, meta_description


def get_category_id_by_name(category_name):
    """Получает ID категории по её названию."""
    try:
        logging.info(f"Ищем категорию: {category_name}")
        categories = wp_client.call(GetTerms("category", search=category_name))
        for category in categories:
            if category.name == category_name:
                return category.id
        return None
    except Exception as e:
        logging.error(f"Ошибка при получении категории: {e}")
        return None

async def publish_to_wordpress(
    title, content, meta_title, meta_description, category=None, image_url=None
):
    """Публикация на WordPress с учетом асинхронной загрузки изображения"""
    post = WordPressPost()
    post.title = title
    post.content = content
    post.post_status = "publish"
    post.custom_fields = [
        {"key": "_yoast_wpseo_title", "value": meta_title},
        {"key": "_yoast_wpseo_metadesc", "value": meta_description},
    ]

    # Добавление изображения, если оно указано
    if image_url:
        image_id, _ = await upload_image_to_wordpress(image_url)  # Асинхронный вызов
        if image_id:
            post.thumbnail = image_id
    else:
        logging.warning("Статья не опубликована из-за отсутствия изображения.")
        return

    # Добавление категории, если она указана
    if category:
        category_id = get_category_id_by_name(category)  # Асинхронный вызов для категории
        if category_id:
            post.terms_names = {"category": [category]}  # Указываем категорию
        else:
            logging.warning(f"Категория '{category}' не будет добавлена к посту.")
            return

    # Публикация поста
    try:
        post_id = wp_client.call(NewPost(post))
        logging.info(f"Статья '{title}' успешно опубликована. ID: {post_id}")
        return post_id
    except Exception as e:
        logging.error(f"Ошибка публикации статьи: {e}")
        return None



async def upload_image_to_wordpress(image_url):
    """Асинхронная загрузка изображения в WordPress через Playwright."""
    try:
        if not image_url:
            logging.warning("Нет изображения для загрузки.")
            return None, None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(proxy={
                "server": "http://163.5.39.69:2966",
                "username": "user215587",
                "password": "rfqa06"
            })
            page = await context.new_page()
            await page.goto(image_url, wait_until="load")

            # Получаем изображение в бинарном виде
            image_bytes = await page.screenshot()
            await browser.close()

        image_name = image_url.split("/")[-1]
        image_data = {
            "name": image_name,
            "type": "image/jpeg",  
            "bits": image_bytes,  
        }

        # Загружаем изображение в WordPress
        upload_response = wp_client.call(UploadFile(image_data))

        return upload_response["id"], upload_response["url"]

    except Exception as e:
        logging.error(f"Ошибка загрузки изображения в WordPress: {e}")
        return None, None


def get_wordpress_post_url(post_id):
    """
    Получение URL опубликованного поста по его ID.
    """
    try:
        post = wp_client.call(GetPost(post_id))
        return post.link
    except Exception as e:
        logging.error(f"Не удалось получить URL поста: {e}")
        return None

def check_and_crop_image(image_url):
    """Проверка изображения на наличие слова 'Reuters' и обрезка на 10% сверху и снизу"""
    try:
        # Загрузка изображения
        # response = requests.get(image_url, proxies=PROXY)
        # image = Image.open(BytesIO(response.content))

        # # Распознавание текста на изображении
        # text = pytesseract.image_to_string(image)

        # # Проверка на наличие слова 'Reuters'
        # if 'REUTERS' in text:
        #     logging.debug("На изображении найдено слово 'Reuters'. Обрезка изображения...")
        #     width, height = image.size
        #     crop_height = int(height * 0.15)  # 10% от высоты изображения

        #     # Обрезка изображения на 10% сверху и снизу
        #     cropped_image = image.crop((0, crop_height, width, height - crop_height))

        #     # Сохранение обрезанного изображения во временный файл
        #     cropped_image_path = "cropped_image.jpg"
        #     cropped_image.save(cropped_image_path)

        #     return cropped_image_path
        # else:
        return image_url

    except Exception as e:
        logging.error(f"Ошибка при обработке изображения: {e}")
        return image_url
