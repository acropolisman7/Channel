import os
import sqlite3
import logging
import asyncio
from datetime import datetime
from typing import List, Optional

import aiohttp
import feedparser
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from telegram import Bot
from google import genai
from google.genai import types

# ----------------- تنظیمات اولیه لاگینگ -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- تنظیمات کلیدها و کانال -----------------
# توکن ربات تلگرام و کلید جمینای (می‌توانید مستقیم اینجا قرار دهید یا از متغیر محیطی بخوانید)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

# آیدی کانال مقصد (مثلاً @YourChannelName یا آیدی عددی)
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@YourChannelName")

# راه‌اندازی کلاینت هوش مصنوعی جمینای با نسخه جدید
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- منابع فید RSS -----------------
RSS_FEEDS = [
    "https://www.zoomit.ir/feed/",
    "https://www.digiato.com/feed",
    "https://www.zoomg.ir/feed/",
    "https://vigiato.net/feed",
    "https://gamefa.com/feed",
    "https://www.ign.com/rss/articles",
    "https://www.vgc247.com/feed"
]

# ----------------- پایگاه داده SQLite -----------------
DB_NAME = "news_bot.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seen_urls (
            url TEXT PRIMARY KEY,
            published_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_url_seen(url: str) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM seen_urls WHERE url = ?', (url,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_url_as_seen(url: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO seen_urls (url, published_at) VALUES (?, ?)', 
                   (url, datetime.now()))
    conn.commit()
    conn.close()

# ----------------- ساختار خروجی Pydantic برای هوش مصنوعی -----------------
class NewsItemOutput(BaseModel):
    title: str = Field(description="عنوان جذاب و روان فارسی خبر")
    summary: str = Field(description="متن خلاصه، ویراستاری‌شده و جذاب خبر به زبان فارسی روان. قانون حیاتی: اسامی خاص، برندها، نام بازی‌ها، شرکت‌ها و سخت‌افزارها نباید ترجمه شوند و باید به انگلیسی یا لاتین دقیق نوشته شوند.")
    image_url: Optional[str] = Field(description="لینک تصویر اصلی و باکیفیت خبر اگر موجود باشد")

class BatchProcessResult(BaseModel):
    selected_news: Optional[NewsItemOutput] = Field(description="خبر منتخب و پردازش‌شده نهایی")

# ----------------- توابع کمکی -----------------
async def fetch_feed_entries():
    entries = []
    async with aiohttp.ClientSession() as session:
        for feed_url in RSS_FEEDS:
            try:
                async with session.get(feed_url, timeout=15) as response:
                    if response.status == 200:
                        content = await response.text()
                        parsed = feedparser.parse(content)
                        for entry in parsed.entries[:5]: # بررسی ۵ خبر آخر هر فید
                            if hasattr(entry, 'link') and entry.link:
                                if not is_url_seen(entry.link):
                                    entries.append({
                                        "title": getattr(entry, 'title', ''),
                                        "link": entry.link,
                                        "summary": getattr(entry, 'summary', getattr(entry, 'description', '')),
                                        "feed": feed_url
                                    })
            except Exception as e:
                logger.error(f"Error fetching feed {feed_url}: {e}")
    return entries

async def process_news_with_gemini(news_list: List[dict]) -> Optional[NewsItem output if needed]:
    if not news_list:
        return None

    # آماده‌سازی متن اخبار برای تحلیل توسط جمینای
    news_text_block = ""
    for i, item in enumerate(news_list):
        clean_summary = BeautifulSoup(item['summary'], "html.parser").get_text()
        news_text_block += f"--- خبر شماره {i+1} ---\nعنوان: {item['title']}\nلینک: {item['link']}\nمتن: {clean_summary[:500]}\n\n"

    prompt = f"""
    شما یک سردبیر و ویراستار حرفه‌ای اخبار تکنولوژی و گیمینگ هستید.
    وظیفه شما این است که از میان اخبار زیر، مهم‌ترین و کامل‌ترین خبر را انتخاب کنید (یا اگر اخبار مشابه هستند، کامل‌ترین نسخه را تجمیع و انتخاب کنید).
    
    قوانین حیاتی:
    1. اسامی خاص، برندها (مثل Sony, Microsoft, Apple)، نام بازی‌ها (مثل GTA, God of War) و شرکت‌ها نباید به هیچ وجه ترجمه شوند و باید به شکل اصلی خود (انگلیسی/لاتین) نوشته شوند.
    2. متن باید به زبان فارسی روان، جذاب و مناسب برای کانال تلگرامی ویراستاری شود.
    3. اگر تصویر شاخص یا معتبری در متن وجود دارد لینک آن را استخراج کنید.

    اخبار ورودی:
    {news_text_block}
    """

    for attempt in range(3): # سیستم تلاش مجدد برای خطاهای موقتی 503
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.8-flash',  # استفاده از مدل پایدار و جدید سری 3.8
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=NewsItemOutput,
                    temperature=0.3
                )
            )
            # تبدیل خروجی به مدل Pydantic
            import json
            data = json.loads(response.text)
            return data, news_list
        except Exception as e:
            logger.error(f"Error in Gemini processing (Attempt {attempt+1}): {e}")
            await asyncio.sleep(3)
    return None, None

# ----------------- حلقه اصلی ربات -----------------
async def main():
    init_db()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("RSS News Bot is running...")

    while True:
        try:
            logger.info("Checking RSS feeds...")
            new_entries = await fetch_feed_entries()
            
            if new_entries:
                # دسته‌بندی و پردازش اخبار جدید با جمینای
                processed_data, original_items = await process_news_with_gemini(new_entries[:5])
                
                if processed_data and processed_data.get("title"):
                    title = processed_data.get("title")
                    summary = processed_data.get("summary")
                    image_url = processed_data.get("image_url")
                    
                    # پیدا کردن لینک اصلی خبر برای ثبت در دیتابیس
                    target_link = original_items[0]['link'] if original_items else ""
                    
                    formatted_message = f"🔥 **{title}**\n\n{summary}\n\n🔗 منبع: {target_link}"

                    # ارسال به کانال تلگرام
                    if image_url and image_url.startswith("http"):
                        try:
                            await bot.send_photo(
                                chat_id=CHANNEL_USERNAME,
                                photo=image_url,
                                caption=formatted_message,
                                parse_mode="Markdown"
                            )
                        except Exception:
                            # اگر ارسال عکس خطا داد، فقط متن را بفرست
                            await bot.send_message(
                                chat_id=CHANNEL_USERNAME,
                                text=formatted_message,
                                parse_mode="Markdown"
                            )
                    else:
                        await bot.send_message(
                            chat_id=CHANNEL_USERNAME,
                            text=formatted_message,
                            parse_mode="Markdown"
                        )

                    # علامت‌گذاری همه لینک‌های بررسی شده به عنوان دیده‌شده
                    for item in original_items:
                        mark_url_as_seen(item['link'])
                    
                    logger.info(f"Successfully published news: {title}")

        except Exception as e:
            logger.error(f"Error in main loop: {e}")

        # بررسی هر ۱۵ دقیقه یک‌بار
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
