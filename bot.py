import asyncio
import sqlite3
import re
import os
import json
import time
import random
import html
import uuid
from collections import defaultdict, deque
from urllib.parse import urljoin
import aiohttp
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

# ================= ۱. تنظیمات اصلی و خواندن کلیدها از Railway =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

# کلیدهای جمنای (پشتیبانی از ۳ کلید از جیمیل‌های مختلف)
GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]

# لیست کلیدهای Groq و OpenRouter (جدا شده با ویرگول در متغیرهای Railway)
GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]

TARGET_CHANNEL = '@jazebestore'
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
STORE_URL = "https://jazebestore.com"

CHECK_INTERVAL_SECONDS = 3600   # اجرای چرخه خبری و فروشگاهی هر ۱ ساعت
MAX_NEWS_PER_HOUR = 10          # حداکثر ۱۰ خبر برتر در هر ساعت
MAX_CANDIDATES_FOR_AI = 65      # حداکثر ۶۵ خبر خام ارسالی به AI
PRODUCTS_PER_HOUR = 3           # انتشار ۳ محصول رندوم موجود در هر ساعت
POLL_INTERVAL_HOURS = 6         # حداقل فاصله زمانی بین دو نظرسنجی خودکار در کانال (ساعت)

# مدل‌های جمنای
GEMINI_MODELS = ['gemini-3.8-flash', 'gemini-3.5-flash-lite']

CATEGORY_HASHTAGS = {
    "gaming": "#گیمینگ",
    "technology": "#تکنولوژی",
    "hardware": "#سخت_افزار",
    "crypto": "#کریپتو",
    "film_tv": "#سینما_و_تلویزیون",
    "internet_culture": "#فرهنگ_اینترنتی",
    "music": "#موسیقی",
    "general_news": "#اخبار_عمومی"
}

CATEGORIZED_RSS_SOURCES = {
    "gaming": [
        "https://www.ign.com/rss/v2/articles/feed",
        "https://feeds.feedburner.com/ign/news",
        "https://feeds.feedburner.com/ign/reviews",
        "https://feeds.feedburner.com/ign/games-all",
        "https://www.gamespot.com/feeds/mashup/",
        "https://www.eurogamer.net/?format=rss",
        "https://www.videogameschronicle.com/feed/",
        "https://www.pcgamer.com/feeds.xml",
        "https://www.polygon.com/rss/index.xml",
        "https://kotaku.com/rss",
        "https://www.rockpapershotgun.com/feed",
        "https://www.gamesindustry.biz/feed",
        "https://www.gematsu.com/feed",
        "https://www.pushsquare.com/feeds/latest",
        "https://www.purexbox.com/feeds/latest",
        "https://www.nintendolife.com/feeds/latest",
        "https://www.gamedeveloper.com/rss.xml",
        "https://blog.playstation.com/feed/",
        "https://news.xbox.com/en-us/feed/",
        "https://www.zoomg.ir/feed/",
        "https://vigiato.net/feed",
        "https://gamefa.com/feed"
    ],
    "technology": [
        "https://www.theverge.com/rss/index.xml",
        "https://www.theverge.com/rss/tech/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.wired.com/feed/rss",
        "https://techcrunch.com/feed/",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.engadget.com/rss.xml",
        "https://www.cnet.com/rss/news/",
        "https://www.techradar.com/feeds.xml",
        "https://gizmodo.com/feed",
        "https://mashable.com/feeds/rss/all",
        "https://www.techmeme.com/feed.xml",
        "https://feeds.macrumors.com/MacRumors-All",
        "https://9to5mac.com/feed/",
        "https://www.zoomit.ir/feed/",
        "https://digiato.com/feed"
    ],
    "hardware": [
        "https://www.tomshardware.com/feeds/all",
        "https://www.techspot.com/backend.xml",
        "https://www.notebookcheck.net/RSS-Feed.8156.0.html",
        "https://www.techpowerup.com/rss/news",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCI8iQa1hv7oV_Z8D35vVuSg",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UChIs72whgZI9w6d6FhwGGHA"
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://www.theblock.co/rss.xml",
        "https://decrypt.co/feed",
        "https://bitcoinmagazine.com/feed",
        "https://www.dlnews.com/arc/outboundfeeds/rss/",
        "https://blockworks.co/feed",
        "https://cryptoslate.com/feed/",
        "https://thedefiant.io/feed",
        "https://u.today/rss",
        "https://beincrypto.com/feed/",
        "https://protos.com/feed"
    ],
    "film_tv": [
        "https://variety.com/feed/",
        "https://variety.com/v/film/feed/",
        "https://variety.com/v/tv/feed/",
        "https://variety.com/v/music/feed/",
        "https://www.hollywoodreporter.com/feed/",
        "https://deadline.com/feed/",
        "https://www.indiewire.com/feed/",
        "https://www.thewrap.com/feed/",
        "https://collider.com/feed/",
        "https://screenrant.com/feed/",
        "https://www.rogerebert.com/feed",
        "https://www.avclub.com/rss",
        "https://consequence.net/feed/",
        "https://www.slashfilm.com/feed/",
        "https://www.denofgeek.com/feed/",
        "https://bloody-disgusting.com/feed/"
    ],
    "internet_culture": [
        "https://knowyourmeme.com/newsfeed.rss",
        "https://knowyourmeme.com/editorials.rss",
        "https://www.tmz.com/rss.xml",
        "https://www.buzzfeed.com/index.xml",
        "https://www.dexerto.com/feed/",
        "https://www.complex.com/feed/",
        "https://www.thedailybeast.com/feed",
        "https://www.vulture.com/rss/index.xml",
        "https://www.themarysue.com/feed/"
    ],
    "music": [
        "https://www.billboard.com/feed/",
        "https://www.rollingstone.com/feed/",
        "https://pitchfork.com/feed/feed-news/rss",
        "https://pitchfork.com/feed/feed-album-reviews/rss",
        "https://www.stereogum.com/feed/",
        "https://www.nme.com/feed",
        "https://www.musicbusinessworldwide.com/feed/",
        "https://www.thefader.com/rss",
        "https://feeds.npr.org/1039/rss.xml",
        "https://www.digitalmusicnews.com/feed/",
        "https://musictech.com/feed/",
        "https://ra.co/xml",
        "https://www.spin.com/feed/"
    ],
    "general_news": [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://www.theguardian.com/world/rss",
        "https://feeds.npr.org/1001/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.bloomberg.com/feeds/news.rss",
        "https://www.bloomberg.com/feeds/markets/news.rss",
        "https://www.ft.com/rss/home/international",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.economist.com/finance-and-economics/rss.xml",
        "https://news.google.com/rss/search?q=site%3Areuters.com&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=site%3Aapnews.com&hl=en-US&gl=US&ceid=US:en"
    ]
}

# ================= ۲. راه‌اندازی دیتابیس و حافظه موقت =================
DB_PATH = 'rss_news_history.db'
bot = Bot(token=TELEGRAM_BOT_TOKEN)
BOT_USERNAME_CACHE = None

os.makedirs('temp_media', exist_ok=True)
pending_news_buffer = []

# حافظه کوتاه‌مدت چت کاربران با دستیار هوشمند (حداکثر ۶ پیام آخر برای هر کاربر)
user_chat_histories = defaultdict(lambda: deque(maxlen=6))

async def get_bot_chat_url() -> str:
    """دریافت خودکار یوزرنیم ربات و ساخت لینک مستقیم ورود به چت هوش مصنوعی"""
    global BOT_USERNAME_CACHE
    if not BOT_USERNAME_CACHE:
        try:
            me = await bot.get_me()
            BOT_USERNAME_CACHE = me.username
        except Exception:
            pass
    if BOT_USERNAME_CACHE:
        return f"https://t.me/{BOT_USERNAME_CACHE}?start=advisor"
    return STORE_URL

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_urls (url TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS published_topics 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  topic_summary TEXT, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS post_likes 
                 (post_id TEXT PRIMARY KEY, 
                  like_count INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recent_products 
                 (product_id TEXT PRIMARY KEY, 
                  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS store_products_cache 
                 (id TEXT PRIMARY KEY,
                  name TEXT,
                  price TEXT,
                  link TEXT,
                  image_url TEXT,
                  short_desc TEXT,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_metadata 
                 (key TEXT PRIMARY KEY, 
                  value TEXT)''')
    conn.commit()
    conn.close()

def is_url_seen(url):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_url_seen(url):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen_urls (url) VALUES (?)", (url,))
    conn.commit()
    conn.close()

def get_recent_published_topics(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT topic_summary FROM published_topics ORDER BY id DESC LIMIT ?", (limit,))
    topics = [row[0] for row in c.fetchall()]
    conn.close()
    return topics

def save_published_topic(topic_summary):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO published_topics (topic_summary) VALUES (?)", (topic_summary,))
    conn.commit()
    conn.close()

def get_recently_sent_product_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM recent_products WHERE sent_at <= datetime('now', '-24 hours')")
    conn.commit()
    c.execute("SELECT product_id FROM recent_products")
    ids = {row[0] for row in c.fetchall()}
    conn.close()
    return ids

def mark_product_sent(product_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO recent_products (product_id, sent_at) VALUES (?, CURRENT_TIMESTAMP)", (str(product_id),))
    conn.commit()
    conn.close()

def save_products_to_cache(products: list[dict]):
    if not products:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for p in products:
        c.execute('''INSERT OR REPLACE INTO store_products_cache 
                     (id, name, price, link, image_url, short_desc, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (str(p['id']), p['name'], p['price'], p['link'], p.get('image_url'), p.get('short_desc', '')))
    conn.commit()
    conn.close()

def search_cached_products(query: str = "", limit: int = 15) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if not query.strip():
        c.execute('''SELECT id, name, price, link, image_url, short_desc 
                     FROM store_products_cache 
                     ORDER BY updated_at DESC LIMIT ?''', (limit,))
    else:
        words = [w.strip() for w in query.strip().split() if w.strip()]
        sql = "SELECT id, name, price, link, image_url, short_desc FROM store_products_cache WHERE "
        conditions = []
        params = []
        for w in words[:4]:
            conditions.append("(name LIKE ? OR short_desc LIKE ?)")
            params.extend([f"%{w}%", f"%{w}%"])
        sql += " AND ".join(conditions) + " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        c.execute(sql, tuple(params))
    rows = c.fetchall()
    conn.close()
    return [
        {
            'id': r[0],
            'name': r[1],
            'price': r[2],
            'link': r[3],
            'image_url': r[4],
            'short_desc': r[5]
        }
        for r in rows
    ]

def can_publish_poll() -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_metadata WHERE key = 'last_poll_ts'")
    row = c.fetchone()
    conn.close()
    if not row:
        return True
    try:
        last_ts = float(row[0])
        return (time.time() - last_ts) >= (POLL_INTERVAL_HOURS * 3600)
    except Exception:
        return True

def mark_poll_published():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_metadata (key, value) VALUES ('last_poll_ts', ?)", (str(time.time()),))
    conn.commit()
    conn.close()

# ================= ۳. توابع پاکسازی متن و دانلود تصویر =================
def clean_raw_text(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def sanitize_telegram_html(text: str) -> str:
    """ایمن‌سازی تگ‌های HTML برای جلوگیری از خطای Parse در تلگرام"""
    if not text:
        return ""
    allowed_tags = ['b', '/b', 'i', '/i', 'u', '/u', 's', '/s', 'code', '/code', 'pre', '/pre']
    placeholders = {}
    for idx, tag in enumerate(allowed_tags):
        token = f"__TG_TAG_{idx}__"
        placeholders[token] = f"<{tag}>"
        text = re.sub(fr"<{tag}>", token, text, flags=re.IGNORECASE)
    text = html.escape(text)
    for token, orig_tag in placeholders.items():
        text = text.replace(token, orig_tag)
    return text

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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': STORE_URL
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15, ssl=False) as resp:
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
    selected_id: int = Field(description="ID of the selected news candidate")
    category_id: str = Field(description="Must be one of: gaming, technology, hardware, crypto, film_tv, internet_culture, music, general_news")
    topic_hashtags: list[str] = Field(description="2 to 3 specific Persian hashtags starting with # using underscores instead of spaces")
    topic_fingerprint: str = Field(description="1-sentence English summary for deduplication")
    final_persian_text: str = Field(description="Formatted Persian news with HTML <b> title and summary body (without hashtags or signature)")

class PollData(BaseModel):
    question: str = Field(description="Engaging Persian poll question about gaming, consoles, hardware, or the hottest news of this batch (under 250 chars)")
    options: list[str] = Field(description="3 to 4 short, clear Persian poll options (each under 90 chars)")

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]
    interactive_poll: PollData = Field(description="An engaging poll based on the top gaming/tech/hardware topic in this batch")

# ================= ۵. موتور پردازش چندگانه AI (اخبار + دستیار چت) =================
async def generate_news_with_fallback(prompt: str) -> dict | None:
    # ۱. تست تمام کلیدها و مدل‌های جمنای (غیرمسدودکننده با to_thread)
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            try:
                print(f"تلاش پردازش خبر با جمنای (کلید #{key_idx} | مدل: {model_name})...")
                response = await asyncio.to_thread(
                    temp_client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchProcessResult,
                        temperature=0.3
                    )
                )
                print(f"✅ موفقیت با جمنای (کلید #{key_idx} | مدل: {model_name})")
                return json.loads(response.text)
            except Exception as e:
                print(f"⚠️ خطا در جمنای (کلید #{key_idx} | {model_name}): {e}")
                await asyncio.sleep(2)

    json_schema_instruction = """
    Respond ONLY with a valid JSON object matching this exact schema:
    {
      "selected_news": [
        {
          "selected_id": 1,
          "category_id": "gaming",
          "topic_hashtags": ["#هشتگ_اول", "#هشتگ_دوم"],
          "topic_fingerprint": "1-sentence English summary",
          "final_persian_text": "<b>تیتر خبر</b>\\n\\nمتن خلاصه خبر به فارسی..."
        }
      ],
      "interactive_poll": {
        "question": "سوال جذاب نظرسنجی مرتبط با اخبار گیمینگ یا سخت‌افزار؟",
        "options": ["گزینه اول", "گزینه دوم", "گزینه سوم", "گزینه چهارم"]
      }
    }
    """

    # ۲. تست تمام کلیدهای Groq
    for key_idx, groq_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            print(f"تلاش با Groq (کلید #{key_idx})...")
            groq_client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            completion = await groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a JSON-only API. " + json_schema_instruction},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            print(f"✅ موفقیت با Groq (کلید #{key_idx})")
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"⚠️ خطا در Groq (کلید #{key_idx}): {e}")
            await asyncio.sleep(2)

    # ۳. تست تمام کلیدهای OpenRouter
    for key_idx, or_key in enumerate(OPENROUTER_API_KEYS, start=1):
        try:
            print(f"تلاش با OpenRouter (کلید #{key_idx})...")
            or_client = AsyncOpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
            completion = await or_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                messages=[
                    {"role": "system", "content": "You are a JSON-only API. " + json_schema_instruction},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            print(f"✅ موفقیت با OpenRouter (کلید #{key_idx})")
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"⚠️ خطا در OpenRouter (کلید #{key_idx}): {e}")
            await asyncio.sleep(2)

    return None

async def generate_chat_reply_with_fallback(system_prompt: str, user_message: str) -> str:
    """موتور پاسخگویی سریع برای دستیار هوشمند (چت با کاربران)"""
    full_prompt = f"{system_prompt}\n\nUser Question:\n{user_message}"

    # ۱. تلاش با کلیدهای جمنای
    for api_key in GEMINI_API_KEYS:
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            try:
                response = await asyncio.to_thread(
                    temp_client.models.generate_content,
                    model=model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(temperature=0.5)
                )
                if response and response.text:
                    return response.text.strip()
            except Exception:
                continue

    # ۲. تلاش با کلیدهای Groq
    for groq_key in GROQ_API_KEYS:
        try:
            groq_client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            completion = await groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.5
            )
            return completion.choices[0].message.content.strip()
        except Exception:
            continue

    # ۳. تلاش با کلیدهای OpenRouter
    for or_key in OPENROUTER_API_KEYS:
        try:
            or_client = AsyncOpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
            completion = await or_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.5
            )
            return completion.choices[0].message.content.strip()
        except Exception:
            continue

    return "در حال حاضر ترافیک سرورهای پاسخگویی بالاست. لطفاً چند لحظه دیگر مجدداً سوال خود را بپرسید یا به سایت jazebestore.com مراجعه فرمایید. 🙏"

# ================= ۶. جمع‌آوری سریع و هم‌زمان اخبار از فیدها =================
async def fetch_single_feed(sem, category, url):
    async with sem:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=12, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
                    if resp.status != 200:
                        return []
                    xml_data = await resp.text()
            
            feed = await asyncio.to_thread(feedparser.parse, xml_data)
            extracted = []
            for entry in feed.entries[:1]:
                link = getattr(entry, 'link', None)
                if not link or is_url_seen(link):
                    continue
                
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                cleaned_body = clean_raw_text(f"{title}\n{summary}")
                
                if len(cleaned_body) < 35:
                    continue

                img_url = extract_rss_image(entry)
                extracted.append({
                    'category': category,
                    'source': url,
                    'link': link,
                    'text': cleaned_body[:450],
                    'image_url': img_url
                })
            return extracted
        except Exception:
            return []

async def fetch_rss_sources():
    global pending_news_buffer
    if len(pending_news_buffer) > MAX_CANDIDATES_FOR_AI:
        pending_news_buffer = pending_news_buffer[-MAX_CANDIDATES_FOR_AI:]

    sem = asyncio.Semaphore(15)
    tasks = []
    for category, urls in CATEGORIZED_RSS_SOURCES.items():
        for url in urls:
            tasks.append(fetch_single_feed(sem, category, url))
            
    results = await asyncio.gather(*tasks)
    
    for feed_items in results:
        for item in feed_items:
            if not is_url_seen(item['link']):
                mark_url_seen(item['link'])
                item['id'] = len(pending_news_buffer) + 1
                pending_news_buffer.append(item)

# ================= ۷. پردازش هوشمند اخبار + ارسال نظرسنجی خودکار =================
async def process_and_publish_batch():
    global pending_news_buffer
    if not pending_news_buffer:
        return

    current_batch = pending_news_buffer[-MAX_CANDIDATES_FOR_AI:]
    recent_topics = get_recent_published_topics(limit=50)
    
    candidates_for_ai = [
        {
            "id": item['id'],
            "default_category": item['category'],
            "text": item['text'],
            "has_media": bool(item['image_url'])
        }
        for item in current_batch
    ]

    prompt = f"""
    You are the Chief Editor for a popular Persian Telegram channel (@jazebestore) covering Gaming, Tech, Hardware, Crypto, Entertainment, and World News.
    
    Already published topics in the last 48 hours (DO NOT repeat these topics):
    {json.dumps(recent_topics, ensure_ascii=False)}

    New incoming news candidates:
    {json.dumps(candidates_for_ai, ensure_ascii=False)}

    Tasks:
    1. Filter out duplicates against history and cluster similar news stories.
    2. PRIORITY SELECTION: Select AT MOST {MAX_NEWS_PER_HOUR} (maximum 10) of the highest-priority, most breaking, viral, and globally important news items from the candidates. Order them from highest priority to lowest.
    3. Translate/edit each selected item into fluent journalistic Persian (`final_persian_text`). Wrap ONLY the news title at the very beginning inside HTML bold tags like <b>Title here</b>, followed by double line breaks and the summary. Keep length under 750 chars. Do NOT put hashtags inside `final_persian_text`.
    4. CRITICAL: Do NOT translate proper nouns, game titles, hardware models, crypto tokens, or company names (keep PlayStation, iPhone, GTA VI, Bitcoin, NVIDIA, etc. in original English form).
    5. CATEGORIZATION & HASHTAGS:
       - Assign the most accurate `category_id` from: ["gaming", "technology", "hardware", "crypto", "film_tv", "internet_culture", "music", "general_news"].
       - Generate 2 to 3 relevant Persian `topic_hashtags` for the news story (e.g., ["#هوش_مصنوعی", "#اپل"]). Always start with # and use underscores (_) instead of spaces.
    6. Provide a 1-sentence English `topic_fingerprint`.
    7. GAMIFICATION POLL (`interactive_poll`): Create 1 highly engaging Persian poll question (`question`) and 3 to 4 short options (`options`) inspired by the hottest gaming, console, or hardware topic in this batch so channel members can vote and debate.
    """

    result_data = await generate_news_with_fallback(prompt)

    if not result_data:
        print("❌ تمامی کلیدها و سرویس‌های AI با خطا یا محدودیت مواجه شدند. این چرخه خبری رد شد.")
        pending_news_buffer.clear()
        return

    try:
        selected_items = result_data.get("selected_news", [])[:MAX_NEWS_PER_HOUR]
        batch_map = {item['id']: item for item in current_batch}
        bot_chat_url = await get_bot_chat_url()

        for sel in selected_items:
            orig_item = batch_map.get(sel['selected_id'])
            if not orig_item:
                continue

            cat_id = sel.get('category_id', orig_item.get('category', 'general_news'))
            main_cat_hashtag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")
            
            extra_tags = []
            for tag in sel.get('topic_hashtags', []):
                clean_tag = tag.strip().replace(" ", "_")
                if not clean_tag.startswith("#"):
                    clean_tag = "#" + clean_tag
                if clean_tag != main_cat_hashtag:
                    extra_tags.append(clean_tag)
            
            hashtags_line = " ".join([main_cat_hashtag] + extra_tags[:3])
            safe_body = sanitize_telegram_html(sel['final_persian_text'].strip())
            final_caption = f"{safe_body}\n\n🏷 {hashtags_line}{CHANNEL_SIGNATURE}"
            save_published_topic(sel['topic_fingerprint'])

            news_link = orig_item.get('link', 'https://t.me/jazebestore')
            keyboard = [
                [
                    InlineKeyboardButton("❤️ 0", callback_data=f"like_{orig_item['id']}"),
                    InlineKeyboardButton("🔗 متن کامل خبر", url=news_link)
                ],
                [
                    InlineKeyboardButton("🤖 چت با هوش مصنوعی", url=bot_chat_url),
                    InlineKeyboardButton("🔍 جستجوی کالا", switch_inline_query_current_chat="")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if orig_item['image_url']:
                img_path = await download_image_from_url(orig_item['image_url'], f"img_{orig_item['id']}.jpg")
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as photo_file:
                        await bot.send_photo(
                            chat_id=TARGET_CHANNEL,
                            photo=photo_file,
                            caption=final_caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                    os.remove(img_path)
                else:
                    await bot.send_message(
                        chat_id=TARGET_CHANNEL,
                        text=final_caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            else:
                await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=final_caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )

            await asyncio.sleep(5)

        # ارسال نظرسنجی خودکار در کانال (در صورت گذشتن زمان مجاز)
        poll_info = result_data.get("interactive_poll")
        if poll_info and can_publish_poll():
            q_text = poll_info.get("question", "").strip()
            raw_opts = poll_info.get("options", [])
            clean_opts = [str(o).strip()[:95] for o in raw_opts if str(o).strip()][:4]
            if q_text and len(clean_opts) >= 2:
                try:
                    await bot.send_poll(
                        chat_id=TARGET_CHANNEL,
                        question=f"📊 {q_text[:280]}",
                        options=clean_opts,
                        is_anonymous=True,
                        allows_multiple_answers=False
                    )
                    mark_poll_published()
                    print("✅ نظرسنجی تعاملی با موفقیت در کانال منتشر شد.")
                except Exception as pe:
                    print(f"Error sending poll: {pe}")

        pending_news_buffer.clear()

    except Exception as e:
        print(f"Error publishing news to channel: {e}")
        pending_news_buffer.clear()

# ================= ۸. بخش فروشگاه: همگام‌سازی کش محصولات و انتشار ساعتی =================
async def discover_product_urls_from_site(session) -> list[str]:
    product_urls = set()
    product_keywords = ['/product/', '/products/', '/p/', '/item/', '/shop/']

    sitemap_candidates = [
        f"{STORE_URL}/sitemap.xml",
        f"{STORE_URL}/sitemap_index.xml",
        f"{STORE_URL}/product-sitemap.xml",
        f"{STORE_URL}/sitemap-products.xml"
    ]

    sub_sitemaps = []
    for sm_url in sitemap_candidates:
        try:
            async with session.get(sm_url, timeout=12, ssl=False) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    soup = BeautifulSoup(xml_text, 'xml')
                    for loc in soup.find_all('loc'):
                        link = loc.get_text(strip=True)
                        if 'product' in link.lower() and link.endswith('.xml'):
                            sub_sitemaps.append(link)
                        elif any(kw in link.lower() for kw in product_keywords) and not link.endswith('/shop/'):
                            product_urls.add(link)
        except Exception:
            continue

    for sub_url in sub_sitemaps[:3]:
        try:
            async with session.get(sub_url, timeout=12, ssl=False) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    soup = BeautifulSoup(xml_text, 'xml')
                    for loc in soup.find_all('loc'):
                        link = loc.get_text(strip=True)
                        if link.startswith(STORE_URL):
                            product_urls.add(link)
        except Exception:
            continue

    if len(product_urls) < 10:
        for page_url in [STORE_URL, f"{STORE_URL}/shop/", f"{STORE_URL}/products/"]:
            try:
                async with session.get(page_url, timeout=15, ssl=False) as resp:
                    if resp.status == 200:
                        html_text = await resp.text()
                        soup = BeautifulSoup(html_text, 'html.parser')
                        for a_tag in soup.find_all('a', href=True):
                            full_url = urljoin(STORE_URL, a_tag['href']).split('#')[0].split('?')[0]
                            if full_url.startswith(STORE_URL) and any(kw in full_url.lower() for kw in product_keywords):
                                if full_url.rstrip('/') not in [STORE_URL, f"{STORE_URL}/shop", f"{STORE_URL}/products"]:
                                    product_urls.add(full_url)
            except Exception:
                continue

    return list(product_urls)

async def parse_single_product_page(session, url: str) -> dict | None:
    try:
        async with session.get(url, timeout=15, ssl=False) as resp:
            if resp.status != 200:
                return None
            html_text = await resp.text()

        soup = BeautifulSoup(html_text, 'html.parser')
        page_text = soup.get_text(" ", strip=True)

        og_avail = soup.find('meta', property='og:availability') or soup.find('meta', property='product:availability')
        if og_avail and og_avail.get('content', '').lower() in ['out of stock', 'oos', 'outofstock']:
            return None

        out_of_stock_phrases = ['ناموجود', 'اتمام موجودی', 'موجود نیست', 'به زودی']
        status_area = " ".join([el.get_text(" ", strip=True) for el in soup.select('.stock, .availability, .single_add_to_cart_button, button')])
        if any(phrase in status_area for phrase in out_of_stock_phrases):
            return None

        title_tag = soup.find('meta', property='og:title')
        h1_tag = soup.find('h1')
        name = ""
        if h1_tag and len(h1_tag.get_text(strip=True)) > 3:
            name = h1_tag.get_text(strip=True)
        elif title_tag and title_tag.get('content'):
            name = title_tag['content'].split('|')[0].split('-')[0].strip()

        if not name:
            return None

        img_tag = soup.find('meta', property='og:image')
        img_url = img_tag['content'] if img_tag and img_tag.get('content') else None
        if img_url and not img_url.startswith('http'):
            img_url = urljoin(STORE_URL, img_url)

        formatted_price = ""
        price_meta = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
        if price_meta and price_meta.get('content'):
            raw_val = re.sub(r'[^\d]', '', price_meta['content'])
            if raw_val and int(raw_val) > 1000:
                formatted_price = f"{int(raw_val):,} تومان"

        if not formatted_price:
            price_match = re.search(r'([\d,،٬]{4,15})\s*(?:تومان|ریال)', page_text)
            if price_match:
                formatted_price = f"{price_match.group(1)} تومان"

        desc_meta = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        short_desc = clean_raw_text(desc_meta['content']) if desc_meta and desc_meta.get('content') else ""
        if len(short_desc) > 220:
            short_desc = short_desc[:217] + "..."

        return {
            'id': url,
            'name': name,
            'price': formatted_price,
            'link': url,
            'image_url': img_url,
            'short_desc': short_desc
        }
    except Exception:
        return None

async def sync_and_fetch_store_products(count=3) -> list[dict]:
    """به‌روزرسانی کش محصولات فروشگاه (برای جستجوی اینلاین و AI) و انتخاب ۳ محصول موجود"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8'
    }
    discovered_products = []

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # لایه اول: دریافت سریع لیست محصولات از WooCommerce Store API در صورت فعال بودن
            api_url = f"{STORE_URL}/wp-json/wc/store/v1/products?per_page=80"
            try:
                async with session.get(api_url, timeout=15, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            for p in data:
                                if p.get('is_in_stock') is True and p.get('is_purchasable', True):
                                    name = clean_raw_text(p.get('name', ''))
                                    permalink = p.get('permalink', STORE_URL)
                                    prices = p.get('prices', {})
                                    raw_price = str(prices.get('price', ''))
                                    minor_unit = int(prices.get('currency_minor_unit', 0))
                                    currency_code = str(prices.get('currency_code', '')).upper()
                                    formatted_price = ""
                                    if raw_price.isdigit():
                                        val = int(raw_price) // (10 ** minor_unit)
                                        if currency_code in ['IRR', 'RIAL']:
                                            val = val // 10
                                        if val > 0:
                                            formatted_price = f"{val:,} تومان"
                                    images = p.get('images', [])
                                    img_url = images[0].get('src') if images else None
                                    short_desc = clean_raw_text(p.get('short_description', ''))[:220]
                                    if name and permalink:
                                        discovered_products.append({
                                            'id': permalink,
                                            'name': name,
                                            'price': formatted_price,
                                            'link': permalink,
                                            'image_url': img_url,
                                            'short_desc': short_desc
                                        })
            except Exception:
                pass

            # لایه دوم: اگر API بسته بود، کشف از Sitemap و صفحات HTML
            if not discovered_products:
                all_urls = await discover_product_urls_from_site(session)
                print(f"تعداد {len(all_urls)} لینک محصول از نقشه سایت شناسایی شد.")
                recently_sent = get_recently_sent_product_ids()
                candidates = [u for u in all_urls if u not in recently_sent] or all_urls
                random.shuffle(candidates)

                for prod_url in candidates[:18]:
                    prod_data = await parse_single_product_page(session, prod_url)
                    if prod_data:
                        discovered_products.append(prod_data)
                    if len(discovered_products) >= max(count * 3, 10):
                        break
                    await asyncio.sleep(0.5)

    except Exception as e:
        print(f"Error syncing store catalog: {e}")

    # ذخیره محصولات کشف‌شده در کش SQLite برای استفاده فوری در Inline Mode و AI Assistant
    if discovered_products:
        save_products_to_cache(discovered_products)

    recently_sent_ids = get_recently_sent_product_ids()
    available_pool = discovered_products if discovered_products else search_cached_products("", limit=50)
    fresh_pool = [p for p in available_pool if str(p['id']) not in recently_sent_ids]
    if not fresh_pool:
        fresh_pool = available_pool

    if not fresh_pool:
        return []

    return random.sample(fresh_pool, min(count, len(fresh_pool)))

async def publish_random_store_products():
    """انتشار ۳ محصول رندوم به همراه دکمه‌های خرید اقساطی، مشاوره هوشمند و جستجوی سریع"""
    products = await sync_and_fetch_store_products(count=PRODUCTS_PER_HOUR)
    if not products:
        print("⚠️ محصولی برای انتشار ساعتی یافت نشد.")
        return

    bot_chat_url = await get_bot_chat_url()
    print(f"Publishing {len(products)} random in-stock products to {TARGET_CHANNEL}...")

    for prod in products:
        safe_name = html.escape(prod['name'])
        caption_parts = [f"🔥 <b>{safe_name}</b>"]
        
        if prod.get('short_desc'):
            caption_parts.append(f"\n📝 {html.escape(prod['short_desc'])}")
            
        if prod.get('price'):
            caption_parts.append(f"\n💰 قیمت: <b>{html.escape(prod['price'])}</b>")
            
        caption_parts.append("\n✅ موجود و آماده ارسال | امکان خرید اقساطی آسان")
        caption_parts.append("\n🏷 #فروشگاه #خرید_اقساطی")
        final_caption = "\n".join(caption_parts) + CHANNEL_SIGNATURE

        keyboard = [
            [InlineKeyboardButton("💳 خرید اقساطی این محصول", url=prod['link'])],
            [
                InlineKeyboardButton("🤖 مشاوره هوشمند خرید", url=bot_chat_url),
                InlineKeyboardButton("🔍 جستجوی کالا", switch_inline_query_current_chat="")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            safe_filename = f"prod_{abs(hash(prod['id']))}.jpg"
            if prod.get('image_url'):
                img_path = await download_image_from_url(prod['image_url'], safe_filename)
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as photo_file:
                        await bot.send_photo(
                            chat_id=TARGET_CHANNEL,
                            photo=photo_file,
                            caption=final_caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                    os.remove(img_path)
                else:
                    await bot.send_message(
                        chat_id=TARGET_CHANNEL,
                        text=final_caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            else:
                await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=final_caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            mark_product_sent(prod['id'])
        except Exception as e:
            print(f"Error sending product '{prod['name']}': {e}")

        await asyncio.sleep(5)

# ================= ۹. قابلیت اول: دستیار هوشمند (AI Assistant) در ربات و گروه =================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیام خوش‌آمدگویی حرفه‌ای به همراه دکمه‌های دسترسی سریع برای مخاطب"""
    if not update.message:
        return
    welcome_text = (
        "سلام! به دستیار هوشمند <b>جاذبه استور (Jazebe Store)</b> خوش آمدید 🎮✨\n\n"
        "من اینجا هستم تا به شما کمک کنم:\n"
        "🔹 <b>مشاوره تخصصی خرید:</b> مقایسه کنسول‌ها، کارت‌های گرافیک، لپ‌تاپ و قطعات سخت‌افزاری\n"
        "🔹 <b>استعلام محصولات و خرید اقساطی:</b> معرفی محصولات موجود در فروشگاه با لینک مستقیم خرید اقساطی\n"
        "🔹 <b>جستجوی آنی (Inline):</b> با زدن دکمه زیر می‌توانید محصولات فروشگاه را در یک ثانیه جستجو و مشاهده کنید!\n\n"
        "💬 <i>همین الان هر سوالی درباره بازی‌ها، سخت‌افزار یا خرید محصول دارید بنویسید تا راهنمایی‌تان کنم:</i>"
    )
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی سریع محصولات (Inline)", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📤 اشتراک‌گذاری محصول با دوستان", switch_inline_query="")],
        [
            InlineKeyboardButton("🌐 سایت جاذبه استور", url=STORE_URL),
            InlineKeyboardButton("📢 کانال تلگرام", url="https://t.me/jazebestore")
        ]
    ]
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ai_assistant_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخگویی هوشمند به سوالات کاربران در پی‌وی و گروه کامنت‌های کانال"""
    message = update.effective_message
    if not message or not message.text:
        return

    user_text = message.text.strip()
    if user_text.startswith("/"):
        return

    chat_type = update.effective_chat.type
    bot_username = context.bot.username or BOT_USERNAME_CACHE or "jazebestore_bot"

    # در گروه‌ها (مثل گروه کامنت‌های کانال)، فقط در صورت ریپلای روی ربات یا منشن کردن آیدی ربات پاسخ بده
    if chat_type in ["group", "supergroup"]:
        is_reply_to_bot = (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == context.bot.id
        )
        is_mentioned = f"@{bot_username.lower()}" in user_text.lower()
        if not (is_reply_to_bot or is_mentioned):
            return
        user_text = re.sub(fr"@{bot_username}", "", user_text, flags=re.IGNORECASE).strip()

    if not user_text:
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    user_id = update.effective_user.id if update.effective_user else 0
    history_list = list(user_chat_histories[user_id])

    # جستجوی محصولات مرتبط در کش فروشگاه بر اساس کلمات کلیدی پیام کاربر
    matched_products = search_cached_products(user_text, limit=5)
    if not matched_products:
        matched_products = search_cached_products("", limit=5)

    store_context_lines = []
    for p in matched_products:
        price_str = p['price'] if p.get('price') else "مشاهده در سایت"
        store_context_lines.append(f"- نام: {p['name']} | قیمت: {price_str} | لینک خرید اقساطی: {p['link']}")
    store_catalog_text = "\n".join(store_context_lines) if store_context_lines else f"فروشگاه اینترنتی جاذبه استور: {STORE_URL}"

    history_formatted = "\n".join([f"{h['role']}: {h['text']}" for h in history_list])

    system_prompt = f"""
    You are the official AI Gaming, Tech & Shopping Assistant for 'Jazebe Store' (جاذبه استور - {STORE_URL} | Telegram: @jazebestore).
    Your role:
    1. Answer user questions about video games, consoles (PS5, Xbox, Nintendo), PC hardware, laptops, phones, and tech specs accurately in warm, professional, and fluent Persian.
    2. Act as a helpful sales advisor: highlight that Jazebe Store offers easy installment purchasing (خرید اقساطی آسان) on products.
    3. If any products from the Store Catalog below match or relate to the user's request, introduce them with their exact price and link.
    4. Formatting rules: Use ONLY simple HTML bold tags like <b>متن</b> for emphasis. Do NOT use Markdown (** or ##). Keep answers concise, structured with bullet points, and under 1200 characters.

    Store Catalog Sample (In-stock items at jazebestore.com):
    {store_catalog_text}

    Recent Conversation History with this user:
    {history_formatted}
    """

    ai_reply = await generate_chat_reply_with_fallback(system_prompt, user_text)
    safe_reply = sanitize_telegram_html(ai_reply)

    user_chat_histories[user_id].append({"role": "User", "text": user_text[:300]})
    user_chat_histories[user_id].append({"role": "Assistant", "text": ai_reply[:400]})

    keyboard = [
        [
            InlineKeyboardButton("💳 مشاهده سایت و خرید اقساطی", url=STORE_URL),
            InlineKeyboardButton("🔍 جستجوی محصول", switch_inline_query_current_chat="")
        ]
    ]
    await message.reply_text(
        safe_reply,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ۱۰. قابلیت چهارم: جستجوی اینلاین محصولات (Inline Search) =================
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجوی فوق سریع محصولات در هر چتی با زدن دکمه جستجو یا تایپ آیدی ربات"""
    inline_query = update.inline_query
    if not inline_query:
        return

    query_str = inline_query.query.strip()
    products = search_cached_products(query_str, limit=25)
    bot_chat_url = await get_bot_chat_url()

    results = []
    for prod in products:
        prod_name = prod['name']
        prod_price = prod.get('price') or "استعلام قیمت در سایت"
        prod_link = prod.get('link') or STORE_URL
        prod_desc = prod.get('short_desc') or "موجود در جاذبه استور | امکان خرید اقساطی"
        prod_img = prod.get('image_url')

        safe_name = html.escape(prod_name)
        safe_price = html.escape(prod_price)
        safe_desc = html.escape(prod_desc)

        message_text = (
            f"🔥 <b>{safe_name}</b>\n\n"
            f"📝 {safe_desc}\n\n"
            f"💰 قیمت: <b>{safe_price}</b>\n"
            f"✅ موجود در جاذبه استور | شرایط ویژه خرید اقساطی"
            f"{CHANNEL_SIGNATURE}"
        )

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 خرید اقساطی و مشاهده محصول", url=prod_link)],
            [
                InlineKeyboardButton("🤖 مشاوره هوشمند خرید", url=bot_chat_url),
                InlineKeyboardButton("🔍 جستجوی سایر محصولات", switch_inline_query_current_chat="")
            ]
        ])

        article_kwargs = {
            "id": str(uuid.uuid4()),
            "title": prod_name[:60],
            "description": f"💰 {prod_price} | 💳 خرید اقساطی",
            "input_message_content": InputTextMessageContent(
                message_text=message_text,
                parse_mode="HTML"
            ),
            "reply_markup": reply_markup,
        }
        if prod_img and prod_img.startswith("http"):
            article_kwargs["thumbnail_url"] = prod_img

        results.append(InlineQueryResultArticle(**article_kwargs))

    if not results:
        fallback_text = (
            f"🎮 <b>فروشگاه اینترنتی جاذبه استور</b>\n\n"
            f"مرجع تخصصی کنسول‌های بازی، قطعات سخت‌افزاری و گجت‌های روز با امکان <b>خرید اقساطی آسان</b>.\n\n"
            f"🌐 مشاهده تمامی محصولات در سایت:\n{STORE_URL}"
            f"{CHANNEL_SIGNATURE}"
        )
        results.append(
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="🌐 مشاهده همه محصولات در سایت جاذبه استور",
                description="کلیک کنید تا لینک فروشگاه و خرید اقساطی ارسال شود",
                input_message_content=InputTextMessageContent(
                    message_text=fallback_text,
                    parse_mode="HTML"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 ورود به سایت جاذبه استور", url=STORE_URL)],
                    [InlineKeyboardButton("🤖 چت با هوش مصنوعی جاذبه استور", url=bot_chat_url)]
                ])
            )
        )

    try:
        await inline_query.answer(results, cache_time=60, is_personal=True)
    except Exception as e:
        print(f"Inline query answer error: {e}")

# ================= ۱۱. مدیریت کلیک روی دکمه‌های شیشه‌ای (لایک پست‌ها با حفظ سایر دکمه‌ها) =================
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    data = query.data or ""
    if data.startswith("like_"):
        try:
            current_text = query.message.reply_markup.inline_keyboard[0][0].text
            count = int(current_text.split(" ")[1]) + 1
        except Exception:
            count = 1
            
        try:
            existing_rows = [list(row) for row in query.message.reply_markup.inline_keyboard]
            existing_rows[0][0] = InlineKeyboardButton(f"❤️ {count}", callback_data=data)
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(existing_rows))
        except Exception as e:
            print(f"Error updating like button UI: {e}")

# ================= ۱۲. حلقه اصلی اجرا و راه‌اندازی ایمن ربات =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید (نسخه قبلی در حال بسته شدن است)...")
    else:
        print(f"Telegram network/update warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    await get_bot_chat_url()
    print("RSS News, Store Sync, Polls & AI Assistant worker is running...")
    tehran_tz = ZoneInfo("Asia/Tehran")

    await asyncio.sleep(10)

    # همگام‌سازی اولیه محصولات فروشگاه در بدو شروع ربات تا جستجوی اینلاین بلافاصله پر باشد
    try:
        print("Initial store catalog sync for Inline Search & AI Assistant...")
        await sync_and_fetch_store_products(count=1)
    except Exception as e:
        print(f"Initial catalog sync warning: {e}")

    while True:
        try:
            now_tehran = datetime.now(tehran_tz)
            current_hour = now_tehran.hour

            if 9 <= current_hour < 23:
                print(f"[{now_tehran.strftime('%H:%M')}] Fetching RSS feeds concurrently...")
                await fetch_rss_sources()
                print(f"Collected {len(pending_news_buffer)} new candidate items. Processing top {MAX_NEWS_PER_HOUR}...")
                await process_and_publish_batch()
                
                # دریافت و انتشار ۳ محصول رندوم موجود از سایت + آپدیت کش محصولات
                await publish_random_store_products()
            else:
                print(f"Outside active hours (Tehran time hour: {current_hour}). Bot is resting...")

        except Exception as e:
            print(f"Error in background loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

def main():
    print("Waiting 20 seconds for old container to shut down cleanly...")
    time.sleep(20)  # جلوگیری کامل از خطای Conflict در زمان دیپلوی مجدد روی Railway

    init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ثبت هندلرهای کامل ربات
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("help", start_command_handler))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(CallbackQueryHandler(button_click_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_assistant_message_handler))
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started successfully!")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
