import asyncio
import sqlite3
import re
import os
import json
import aiohttp
import feedparser
from bs4 import BeautifulSoup
from pydantic import BaseModel
from google import genai
from google.genai import types
from telegram import Bot

# ================= ۱. تنظیمات اصلی و کلیدها =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

TARGET_CHANNEL = '@jazebestore'                   # آیدی کانال مقصد شما
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"         # امضای انتهای پست
CHECK_INTERVAL_SECONDS = 900                          # بررسی سایت‌ها هر ۱۵ دقیقه (۹۰۰ ثانیه)

# لیست فیدهای RSS معتبر گیمینگ و تکنولوژی (بدون نیاز به کانال تلگرام دیگر)
SOURCE_RSS_URLS = [
    # منابع انگلیسی
    'https://feeds.feedburner.com/ign/games-all',
    'https://www.videogameschronicle.com/feed/',
    'https://www.theverge.com/rss/index.xml',
    'https://feeds.macrumors.com/MacRumors-All',
    'https://9to5mac.com/feed/',
    # منابع فارسی
    'https://www.zoomit.ir/feed/',
    'https://digiato.com/feed',
    'https://www.zoomg.ir/feed/',
    'https://vigiato.net/feed',
    'https://gamefa.com/feed',
]

# ================= ۲. راه‌اندازی دیتابیس و کلاینت‌ها =================
client_ai = genai.Client(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

os.makedirs('temp_media', exist_ok=True)
pending_news_buffer = []

def init_db():
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_urls (url TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS published_topics 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  topic_summary TEXT, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def is_url_seen(url):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_url_seen(url):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen_urls (url) VALUES (?)", (url,))
    conn.commit()
    conn.close()

def get_recent_published_topics(limit=50):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("SELECT topic_summary FROM published_topics ORDER BY id DESC LIMIT ?", (limit,))
    topics = [row[0] for row in c.fetchall()]
    conn.close()
    return topics

def save_published_topic(topic_summary):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("INSERT INTO published_topics (topic_summary) VALUES (?)", (topic_summary,))
    conn.commit()
    conn.close()

# ================= ۳. توابع پاکسازی و استخراج عکس =================
def clean_raw_text(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return text.strip()

def extract_rss_image(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url')
    if 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get('url')
    html_body = getattr(entry, 'summary', '') or ''
    if hasattr(entry, 'content') and len(entry.content) > 0:
        html_body += entry.content[0].value
    soup = BeautifulSoup(html_body, 'html.parser')
    img_tag = soup.find('img')
    if img_tag and img_tag.get('src'):
        return img_tag['src']
    return None

async def download_image_from_url(url, filename):
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    filepath = os.path.join('temp_media', filename)
                    with open(filepath, 'wb') as f:
                        f.write(await resp.read())
                    return filepath
    except Exception as e:
        print(f"Error downloading image {url}: {e}")
    return None

# ================= ۴. ساختار خروجی هوش مصنوعی (Schema) =================
class SelectedNewsItem(BaseModel):
    selected_id: int
    topic_fingerprint: str
    final_persian_text: str

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۵. جمع‌آوری اخبار از سایت‌ها =================
async def fetch_rss_sources():
    global pending_news_buffer
    for url in SOURCE_RSS_URLS:
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
            for entry in feed.entries[:3]:
                link = getattr(entry, 'link', None)
                if not link or is_url_seen(link):
                    continue
                mark_url_seen(link)
                
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                cleaned_body = clean_raw_text(f"{title}\n{summary}")
                
                if len(cleaned_body) < 35:
                    continue

                img_url = extract_rss_image(entry)
                item_id = len(pending_news_buffer) + 1

                pending_news_buffer.append({
                    'id': item_id,
                    'source': url,
                    'text': cleaned_body,
                    'image_url': img_url
                })
        except Exception as e:
            print(f"Error checking RSS {url}: {e}")

# ================= ۶. پردازش هوشمند و انتشار در کانال =================
async def process_and_publish_batch():
    global pending_news_buffer
    if not pending_news_buffer:
        return

    current_batch = pending_news_buffer.copy()
    pending_news_buffer.clear()

    recent_topics = get_recent_published_topics(limit=50)
    candidates_for_ai = [
        {"id": item['id'], "text": item['text'], "has_media": bool(item['image_url'])}
        for item in current_batch
    ]

    prompt = f"""
    You are the Chief Editor for a Persian Gaming & Technology channel.
    Already published topics in the last 48 hours (DO NOT repeat):
    {json.dumps(recent_topics, ensure_ascii=False)}

    New incoming news candidates from websites:
    {json.dumps(candidates_for_ai, ensure_ascii=False)}

    Tasks:
    1. Filter out duplicates against history and cluster similar news stories, picking the best and most complete one.
    2. Translate/edit into fluent journalistic Persian (`final_persian_text`) with a bold title at the top. Length under 850 chars.
    3. CRITICAL: Do NOT translate proper nouns, game titles, hardware models, or company names (keep PlayStation, iPhone, God of War, Steam, Sony, NVIDIA, etc. in original English form).
    4. Provide a 1-sentence English `topic_fingerprint`.
    """

    try:
        response = client_ai.models.generate_content(
            model='gemini-3.1-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=BatchProcessResult,
                temperature=0.3
            )
        )
        
        result_data = json.loads(response.text)
        selected_items = result_data.get("selected_json", []) or result_data.get("selected_news", [])
        batch_map = {item['id']: item for item in current_batch}

        for sel in selected_items:
            orig_item = batch_map.get(sel['selected_id'])
            if not orig_item:
                continue

            final_caption = sel['final_persian_text'].strip() + CHANNEL_SIGNATURE
            save_published_topic(sel['topic_fingerprint'])

            if orig_item['image_url']:
                img_path = await download_image_from_url(orig_item['image_url'], f"img_{orig_item['id']}.jpg")
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as photo_file:
                        await bot.send_photo(chat_id=TARGET_CHANNEL, photo=photo_file, caption=final_caption)
                    os.remove(img_path)
                else:
                    await bot.send_message(chat_id=TARGET_CHANNEL, text=final_caption)
            else:
                await bot.send_message(chat_id=TARGET_CHANNEL, text=final_caption)

            await asyncio.sleep(5)

    except Exception as e:
        print(f"Error in Gemini processing: {e}")

# ================= ۷. حلقه اصلی اجرا =================
async def main_loop():
    init_db()
    print("RSS News Bot is running...")
    while True:
        await fetch_rss_sources()
        await process_and_publish_batch()
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == '__main__':
    asyncio.run(main_loop())
