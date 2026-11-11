import asyncio
import sqlite3
import re
import os
import json
import random
import aiohttp
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

# ================= ۱. تنظیمات اصلی و کلیدهای API =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

# کلیدهای API سرویس اول: Gemini
GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]

# کلیدهای API سرویس دوم و سوم: Groq و OpenRouter
GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]

TARGET_CHANNEL = '@jazebestore'
STORE_BASE_URL = 'https://jazebestore.com'
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"

# تنظیمات زمانی جدید: هر نیم ساعت (۱۸۰۰ ثانیه) | ۲۴ ساعته | ۱۵ خبر در هر نیم ساعت
CHECK_INTERVAL_SECONDS = 1800
MAX_NEWS_PER_CYCLE = 15
MAX_CANDIDATES_FOR_AI = 90
PRODUCTS_PER_CYCLE = 3

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

# کلمات کلیدی برای فیلتر کردن فقط محصولات دیجیتالی (اکانت بازی و پلی‌استیشن پلاس)
DIGITAL_POSITIVE_KEYWORDS = [
    "اکانت", "ظرفیت", "پلاس", "plus", "playstation plus", "ps plus",
    "بازی", "game", "گیفت کارت", "gift card", "شتاب", "اشتراک",
    "fc 26", "fc 25", "gta", "call of duty", "assassin", "god of war",
    "spider-man", "elden ring", "resident evil", "black myth", "astro bot",
    "silent hill", "ghost of", "last of us", "cyberpunk", "red dead",
    "mortal kombat", "tekken", "forza", "halo", "minecraft", "witcher",
    "battlefield", "death stranding", "final fantasy", "persona"
]

# کلمات کلیدی محصولات فیزیکی و سخت‌افزاری که باید کاملاً نادیده گرفته شوند
PHYSICAL_EXCLUDE_KEYWORDS = [
    "کنسول", "تبلت", "آیپد", "ipad", "آیفون", "iphone", "گوشی", "موبایل",
    "لپ تاپ", "لپ‌تاپ", "macbook", "مک بوک", "مانیتور", "تلویزیون",
    "دسته بازی", "dualsense", "دوآل سنس", "هدست", "هدفون", "ایرپاد", "airpods",
    "پایه شارژر", "دیسک‌خور", "دیسک خور", "ریجن اروپا سری", "کارت گرافیک",
    "ساعت هوشمند", "apple watch", "اپل واچ", "کیبورد", "ماوس", "موس", "اسپیکر",
    "هارد", "ssd", "فلش", "پاوربانک", "شارژر", "کابل"
]

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

# ================= ۲. راه‌اندازی دیتابیس و حافظه کش =================
bot = Bot(token=TELEGRAM_BOT_TOKEN)
os.makedirs('temp_media', exist_ok=True)
pending_news_buffer = []
cached_digital_products = []  # کش محصولات دیجیتالی سایت برای تطبیق سریع با هایپ اخبار
provider_rotation_index = 0   # چرخش هوشمند بار بین ۳ سرویس API

def init_db():
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS seen_urls (url TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS published_topics 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  topic_summary TEXT, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_hype 
                 (game_title TEXT PRIMARY KEY, 
                  hype_score INTEGER DEFAULT 1, 
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS posted_products 
                 (product_url TEXT PRIMARY KEY, 
                  posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

def get_recent_published_topics(limit=80):
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

def update_game_hype(game_title: str, score: int):
    """ثبت و افزایش ضریب هایپ بازی‌ها بر اساس اخبار منتشرشده"""
    if not game_title or len(game_title.strip()) < 2:
        return
    clean_title = game_title.strip().lower()
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO game_hype (game_title, hype_score, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(game_title) DO UPDATE SET
            hype_score = hype_score + excluded.hype_score,
            updated_at = CURRENT_TIMESTAMP
    """, (clean_title, max(1, min(score, 10))))
    # پاکسازی هایپ‌های قدیمی‌تر از ۷ روز برای بروز ماندن ضریب‌ها
    c.execute("DELETE FROM game_hype WHERE updated_at < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

def get_hype_scores_map() -> dict:
    """دریافت لیست بازی‌های دارای هایپ خبری در ۷ روز گذشته"""
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("SELECT game_title, hype_score FROM game_hype ORDER BY hype_score DESC LIMIT 100")
    hype_map = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return hype_map

def was_product_recently_posted(product_url: str, hours: int = 12) -> bool:
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("DELETE FROM posted_products WHERE posted_at < datetime('now', ?)", (f'-{hours} hours',))
    conn.commit()
    c.execute("SELECT 1 FROM posted_products WHERE product_url = ?", (product_url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_product_posted(product_url: str):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO posted_products (product_url, posted_at) VALUES (?, CURRENT_TIMESTAMP)", (product_url,))
    conn.commit()
    conn.close()

# ================= ۳. توابع کمکی متن و تصویر =================
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
            async with session.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
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
    related_game: str = Field(default="", description="Exact English name of the video game or PlayStation service if the news is about one (e.g., 'GTA VI', 'EA SPORTS FC 26', 'PlayStation Plus', 'Resident Evil 9'), otherwise empty string")
    hype_score: int = Field(default=5, description="Hype and viral importance score from 1 to 10 based on 2022-2026 trends")
    final_persian_text: str = Field(description="Well-edited Persian news with moderate emojis, HTML <b> bold headline, and <b> bold key phrases inside the body")

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۵. موتور پردازش ۳ گانه AI (با توزیع بار هوشمند ۲۴ ساعته) =================
async def call_gemini_provider(prompt: str) -> dict | None:
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            try:
                print(f"تلاش با Gemini (کلید #{key_idx} | مدل: {model_name})...")
                response = temp_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchProcessResult,
                        temperature=0.3
                    )
                )
                print(f"✅ موفقیت با Gemini (کلید #{key_idx} | {model_name})")
                return json.loads(response.text)
            except Exception as e:
                print(f"⚠️ خطا در Gemini (کلید #{key_idx} | {model_name}): {e}")
                await asyncio.sleep(2)
    return None

JSON_SCHEMA_INSTRUCTION = """
Respond ONLY with a valid JSON object matching this exact schema:
{
  "selected_news": [
    {
      "selected_id": 1,
      "category_id": "gaming",
      "topic_hashtags": ["#هشتگ_اول", "#هشتگ_دوم"],
      "topic_fingerprint": "1-sentence English summary",
      "related_game": "GTA VI",
      "hype_score": 9,
      "final_persian_text": "🔥 <b>تیتر جذاب خبر</b>\\n\\n▫️ متن پاراگراف اول با <b>بولد کردن نکات کلیدی</b> و ویراستاری دقیق..."
    }
  ]
}
"""

async def call_groq_provider(prompt: str) -> dict | None:
    for key_idx, groq_key in enumerate(GROQ_API_KEYS, start=1):
        try:
            print(f"تلاش با Groq (کلید #{key_idx})...")
            groq_client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            completion = await groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a professional Persian Chief Editor API. " + JSON_SCHEMA_INSTRUCTION},
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
    return None

async def call_openrouter_provider(prompt: str) -> dict | None:
    for key_idx, or_key in enumerate(OPENROUTER_API_KEYS, start=1):
        try:
            print(f"تلاش با OpenRouter (کلید #{key_idx})...")
            or_client = AsyncOpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
            completion = await or_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                messages=[
                    {"role": "system", "content": "You are a professional Persian Chief Editor API. " + JSON_SCHEMA_INSTRUCTION},
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

async def generate_news_with_fallback(prompt: str) -> dict | None:
    """چرخش هوشمند بین ۳ سرویس API برای پوشش ۲۴ ساعته بدون اتمام سهمیه"""
    global provider_rotation_index
    providers = [call_gemini_provider, call_groq_provider, call_openrouter_provider]
    
    # شروع از سرویس نوبت فعلی و تست بقیه در صورت خطا
    ordered_providers = providers[provider_rotation_index % 3:] + providers[:provider_rotation_index % 3]
    provider_rotation_index += 1

    for provider_fn in ordered_providers:
        result = await provider_fn(prompt)
        if result and "selected_news" in result:
            return result
    return None

# ================= ۶. استخراج فقط محصولات دیجیتالی سایت و محاسبه ضریب هایپ =================
def is_digital_game_or_plus_product(title: str, url: str = "") -> bool:
    """
    بررسی دقیق برای اطمینان از اینکه محصول فقط دیجیتالی (اکانت بازی یا پلی‌استیشن پلاس) است
    و هیچ‌گونه کالای فیزیکی/سخت‌افزاری (کنسول، تبلت، دسته و...) ارسال نمی‌شود.
    """
    combined = f"{title} {unquote(url)}".lower()

    # ۱. رد فوری کالاهای فیزیکی و سخت‌افزاری
    for bad_kw in PHYSICAL_EXCLUDE_KEYWORDS:
        if bad_kw.lower() in combined:
            return False

    # ۲. تایید وجود کلمات کلیدی اکانت بازی، پلاس یا نام بازی‌های دیجیتالی
    for good_kw in DIGITAL_POSITIVE_KEYWORDS:
        if good_kw.lower() in combined:
            return True

    return False

def calculate_product_hype_weight(product: dict, hype_map: dict) -> float:
    """
    محاسبه ضریب شانس ارسال محصول بر اساس هایپ و اخبار اخیر مربوط به آن بازی
    """
    base_weight = 1.0
    title_lower = product['title'].lower()
    url_lower = unquote(product['url']).lower()

    # اگر محصول پلی‌استیشن پلاس است، یک ضریب پایه خوب دریافت می‌کند
    if "پلاس" in title_lower or "plus" in title_lower:
        base_weight += 2.5

    # بررسی تطابق نام بازی‌های پرخبر (Hype) با عنوان یا لینک محصول در سایت
    for hyped_game, score in hype_map.items():
        if len(hyped_game) >= 3 and (hyped_game in title_lower or hyped_game in url_lower):
            # افزایش چشمگیر ضریب ارسال لینک صفحه بازی متناسب با میزان هایپ خبرها
            base_weight += (score * 4.0)

    return base_weight

def find_matching_store_product_for_news(related_game: str) -> dict | None:
    """پیدا کردن لینک صفحه بازی در سایت زمانی که خبر داغی درباره آن بازی منتشر می‌شود"""
    if not related_game or not cached_digital_products:
        return None
    game_clean = related_game.strip().lower()
    if len(game_clean) < 3:
        return None

    for prod in cached_digital_products:
        t_low = prod['title'].lower()
        u_low = unquote(prod['url']).lower()
        if game_clean in t_low or game_clean in u_low:
            return prod
    return None

async def discover_product_urls_from_site(session: aiohttp.ClientSession) -> list[str]:
    discovered_urls = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    sitemap_candidates = [
        f"{STORE_BASE_URL}/product-sitemap.xml",
        f"{STORE_BASE_URL}/sitemap_index.xml",
        f"{STORE_BASE_URL}/sitemap.xml",
    ]

    for sm_url in sitemap_candidates:
        try:
            async with session.get(sm_url, timeout=12, headers=headers) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    locs = re.findall(r'<loc>(https?://[^<]+)</loc>', xml_text)
                    sub_sitemaps = [u for u in locs if 'product' in u and u.endswith('.xml')]
                    for sub_sm in sub_sitemaps[:3]:
                        async with session.get(sub_sm, timeout=12, headers=headers) as sub_resp:
                            if sub_resp.status == 200:
                                sub_xml = await sub_resp.text()
                                sub_locs = re.findall(r'<loc>(https?://[^<]+)</loc>', sub_xml)
                                for u in sub_locs:
                                    if any(p in u for p in ['/product/', '/products/', '/p/', '/shop/']):
                                        discovered_urls.add(u)
                    for u in locs:
                        if not u.endswith('.xml') and any(p in u for p in ['/product/', '/products/', '/p/']):
                            discovered_urls.add(u)
            if discovered_urls:
                break
        except Exception:
            continue

    if not discovered_urls:
        for page_url in [STORE_BASE_URL, f"{STORE_BASE_URL}/shop", f"{STORE_BASE_URL}/products"]:
            try:
                async with session.get(page_url, timeout=12, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            full_url = urljoin(STORE_BASE_URL, a['href'])
                            if full_url.startswith(STORE_BASE_URL) and any(p in full_url for p in ['/product/', '/products/', '/p/']):
                                discovered_urls.add(full_url)
            except Exception:
                continue

    # فیلتر اولیه لینک‌ها برای حذف سریع لینک‌های سخت‌افزاری واضح
    filtered_urls = [
        u for u in discovered_urls
        if not any(bad in unquote(u).lower() for bad in PHYSICAL_EXCLUDE_KEYWORDS)
    ]
    return filtered_urls

async def scrape_single_digital_product(session: aiohttp.ClientSession, url: str) -> dict | None:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        async with session.get(url, timeout=12, headers=headers) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')

        # ۱. استخراج عنوان
        title = None
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content'].split('|')[0].split('- جاذبه')[0].strip()
        if not title and soup.find('h1'):
            title = soup.find('h1').get_text(strip=True)
        if not title:
            return None

        # ۲. فیلتر قطعی: فقط اکانت بازی و پلی‌استیشن پلاس (رد کامل محصولات فیزیکی)
        if not is_digital_game_or_plus_product(title, url):
            return None

        # ۳. بررسی موجود بودن محصول
        page_text = soup.get_text(" ", strip=True)
        avail_meta = soup.find('meta', property='og:availability') or soup.find('meta', property='product:availability')
        if avail_meta and 'outofstock' in str(avail_meta.get('content', '')).lower():
            return None
        if 'ناموجود' in page_text and 'افزودن به سبد' not in page_text and 'خرید' not in page_text:
            return None

        # ۴. استخراج تصویر
        image_url = None
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            image_url = og_img['content']

        # ۵. استخراج قیمت
        price_str = "مشاهده قیمت و ظرفیت‌ها در سایت"
        price_meta = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
        if price_meta and price_meta.get('content'):
            try:
                raw_price = int(float(str(price_meta['content']).replace(',', '').strip()))
                if raw_price > 0:
                    price_str = f"{raw_price:,} تومان"
            except Exception:
                pass
        else:
            price_match = re.search(r'(\d{1,3}(?:,\d{3})+)\s*تومان', page_text)
            if price_match:
                price_str = f"{price_match.group(1)} تومان"

        return {
            'title': title,
            'url': url,
            'image_url': image_url,
            'price': price_str
        }
    except Exception:
        return None

async def refresh_digital_products_cache():
    """بروزرسانی لیست محصولات دیجیتالی موجود در سایت"""
    global cached_digital_products
    async with aiohttp.ClientSession() as session:
        all_urls = await discover_product_urls_from_site(session)
        if not all_urls:
            print("⚠️ لینکی از نقشه سایت دریافت نشد.")
            return

        random.shuffle(all_urls)
        sampled_urls = all_urls[:45]
        sem = asyncio.Semaphore(8)

        async def fetch_with_sem(u):
            async with sem:
                return await scrape_single_digital_product(session, u)

        results = await asyncio.gather(*(fetch_with_sem(u) for u in sampled_urls))
        valid_digital = [r for r in results if r is not None]
        if valid_digital:
            cached_digital_products = valid_digital
            print(f"✅ تعداد {len(cached_digital_products)} محصول دیجیتالی (اکانت بازی/پلاس) آماده ارسال شد.")

async def publish_weighted_digital_products():
    """
    انتخاب و انتشار محصولات دیجیتالی با ضریب شانس بالاتر برای بازی‌های دارای هایپ خبری
    """
    global cached_digital_products
    if len(cached_digital_products) < PRODUCTS_PER_CYCLE:
        await refresh_digital_products_cache()

    if not cached_digital_products:
        print("هیچ محصول دیجیتالی موجودی برای ارسال یافت نشد.")
        return

    # حذف محصولاتی که در ۱۲ ساعت اخیر ارسال شده‌اند (در صورت وجود جایگزین کافی)
    unposted_pool = [p for p in cached_digital_products if not was_product_recently_posted(p['url'], hours=12)]
    candidate_pool = unposted_pool if len(unposted_pool) >= PRODUCTS_PER_CYCLE else cached_digital_products

    hype_map = get_hype_scores_map()
    
    # انتخاب وزن‌دار بدون تکرار (Weighted Random Selection) بر اساس هایپ بازی‌ها
    selected_products = []
    temp_pool = candidate_pool.copy()

    for _ in range(min(PRODUCTS_PER_CYCLE, len(temp_pool))):
        weights = [calculate_product_hype_weight(p, hype_map) for p in temp_pool]
        chosen = random.choices(temp_pool, weights=weights, k=1)[0]
        chosen['_weight'] = round(calculate_product_hype_weight(chosen, hype_map), 1)
        selected_products.append(chosen)
        temp_pool.remove(chosen)

    for idx, prod in enumerate(selected_products, start=1):
        is_plus = "پلاس" in prod['title'].lower() or "plus" in prod['title'].lower()
        badge_emoji = "💎" if is_plus else "🎮"
        product_type_text = "اشتراک رسمی پلی‌استیشن پلاس" if is_plus else "اکانت قانونی و ظرفیتی بازی"

        caption = (
            f"{badge_emoji} <b>{prod['title']}</b>\n\n"
            f"🔹 نوع محصول: <b>{product_type_text}</b>\n"
            f"💰 قیمت: <b>{prod['price']}</b>\n"
            f"✅ <b>تحویل فوری</b> به همراه گارانتی دائمی و امکان <b>خرید اقساطی</b>\n\n"
            f"🏷 #اکانت_ظرفیتی #پلی_استیشن_پلاس #خرید_بازی"
            f"{CHANNEL_SIGNATURE}"
        )

        keyboard = [
            [InlineKeyboardButton("💳 خرید اقساطی و مشاهده محصول", url=prod['url'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if prod.get('image_url'):
                img_path = await download_image_from_url(prod['image_url'], f"prod_{idx}.jpg")
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as photo_file:
                        await bot.send_photo(
                            chat_id=TARGET_CHANNEL,
                            photo=photo_file,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                    os.remove(img_path)
                else:
                    await bot.send_message(
                        chat_id=TARGET_CHANNEL,
                        text=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
            else:
                await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            mark_product_posted(prod['url'])
            print(f"🛒 محصول دیجیتالی ارسال شد: {prod['title']} (ضریب هایپ: {prod.get('_weight', 1.0)})")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error sending digital product '{prod['title']}': {e}")

# ================= ۷. جمع‌آوری هم‌زمان اخبار از فیدهای RSS =================
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
            for entry in feed.entries[:2]:
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
                    'text': cleaned_body[:500],
                    'image_url': img_url
                })
            return extracted
        except Exception:
            return []

async def fetch_rss_sources():
    global pending_news_buffer
    if len(pending_news_buffer) > MAX_CANDIDATES_FOR_AI:
        pending_news_buffer = pending_news_buffer[-MAX_CANDIDATES_FOR_AI:]

    sem = asyncio.Semaphore(18)
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

# ================= ۸. پردازش هوشمند اخبار با معیارهای ۲۰۲۲-۲۰۲۶ و ویراستاری دقیق =================
async def process_and_publish_batch():
    global pending_news_buffer
    if not pending_news_buffer:
        return

    current_batch = pending_news_buffer[-MAX_CANDIDATES_FOR_AI:]
    recent_topics = get_recent_published_topics(limit=80)
    
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
    You are the Chief Editor for '@jazebestore', a premier Persian Gaming, Tech, Hardware, Crypto, and Entertainment Telegram channel.
    Current Year Context: 2026. You are trained on and strictly apply modern digital journalism & editorial standards from 2022 to 2026.

    Already published topics in the last 48 hours (DO NOT repeat these topics):
    {json.dumps(recent_topics, ensure_ascii=False)}

    New incoming news candidates:
    {json.dumps(candidates_for_ai, ensure_ascii=False)}

    STRICT EDITORIAL & VISUAL GUIDELINES (2022-2026 STANDARDS):
    1. DEDUPLICATION & SELECTION: Filter out duplicates against history, cluster similar news, and select AT MOST {MAX_NEWS_PER_CYCLE} (maximum 15) of the highest-priority, breaking, and viral news stories. Order from highest priority to lowest.
    2. 2022-2026 JOURNALISTIC ACCURACY:
       - Lead with the core fact immediately (Inverted Pyramid style). Avoid clickbait or vague openings.
       - Clearly distinguish between official confirmations ("به‌طور رسمی تایید شد") and leaks/rumors ("بر اساس گزارش اینسایدرها / شایعات").
       - Maintain accurate 2022-2026 industry context (e.g., PS5 Pro, GTA VI, RTX 50 series, modern AI models, current PlayStation Plus tiers).
    3. PERSIAN EDITORIAL PRECISION & BOLDING (`final_persian_text`):
       - Write in fluent, polished, professional Persian with proper punctuation and half-spaces (نیم‌فاصله، مثل «می‌شود»، «بازی‌ها»).
       - HEADLINE: Start with 1 relevant emoji + HTML bold headline: `🔥 <b>تیتر دقیق و جذاب خبر</b>` followed by two line breaks (`\\n\\n`).
       - BODY BOLDING (CRITICAL): Inside the summary body, wrap **2 to 4 of the most important phrases, release dates, stats, or key facts** in HTML `<b>...</b>` tags so readers can scan the key points instantly.
       - EMOJI BALANCE (LOW TO MODERATE): Use only 2 to 4 purposeful emojis in the entire post (1 in the headline, and 1 to 3 as clean paragraph/bullet markers like `▫️`, `🔹`, `🎮`, `⚡`). Never overuse emojis.
       - Keep total length between 250 and 750 characters. Do NOT include hashtags inside `final_persian_text`.
    4. PROPER NOUNS: Keep game titles, hardware models, crypto tokens, and company names in original English (e.g., PlayStation 5, GTA VI, NVIDIA, Steam, Xbox, PlayStation Plus).
    5. GAME HYPE TRACKING:
       - If the news relates to a specific video game or PlayStation Plus, put its exact English title in `related_game` (e.g., "GTA VI", "EA SPORTS FC 26", "PlayStation Plus", "Ghost of Yotei"). Otherwise leave `related_game` as "".
       - Set `hype_score` (1 to 10) reflecting how hyped/viral this topic is right now.
    6. CATEGORIZATION & HASHTAGS:
       - Assign `category_id` from: ["gaming", "technology", "hardware", "crypto", "film_tv", "internet_culture", "music", "general_news"].
       - Generate 2 to 3 specific Persian `topic_hashtags` starting with # and using underscores (_) instead of spaces.
    """

    result_data = await generate_news_with_fallback(prompt)

    if not result_data:
        print("❌ تمامی سرویس‌های AI در این چرخه با خطا مواجه شدند.")
        pending_news_buffer.clear()
        return

    try:
        selected_items = result_data.get("selected_news", [])[:MAX_NEWS_PER_CYCLE]
        batch_map = {item['id']: item for item in current_batch}

        for sel in selected_items:
            orig_item = batch_map.get(sel.get('selected_id'))
            if not orig_item:
                continue

            # ثبت ضریب هایپ بازی در دیتابیس برای افزایش شانس ارسال لینک محصول آن بازی
            related_game = sel.get('related_game', '').strip()
            hype_score = int(sel.get('hype_score', 5) or 5)
            if related_game:
                update_game_hype(related_game, hype_score)

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
            final_caption = f"{sel['final_persian_text'].strip()}\n\n🏷 {hashtags_line}{CHANNEL_SIGNATURE}"
            save_published_topic(sel.get('topic_fingerprint', orig_item['link']))

            news_link = orig_item.get('link', STORE_BASE_URL)
            keyboard = [
                [
                    InlineKeyboardButton("❤️ 0", callback_data=f"like_{orig_item['id']}"),
                    InlineKeyboardButton("🔗 منبع خبر", url=news_link)
                ]
            ]

            # اگر خبر درباره یک بازی پرهایپ است که اکانت آن در سایت موجود است، دکمه مستقیم خرید همان بازی اضافه شود
            matched_product = find_matching_store_product_for_news(related_game)
            if matched_product:
                keyboard.append([
                    InlineKeyboardButton(f"🎮 خرید اکانت {related_game} از سایت", url=matched_product['url'])
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            if orig_item.get('image_url'):
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

            await asyncio.sleep(4)

        pending_news_buffer.clear()

    except Exception as e:
        print(f"Error publishing news batch to channel: {e}")
        pending_news_buffer.clear()

# ================= ۹. مدیریت دکمه لایک پست‌ها (حفظ دکمه لینک بازی در صورت وجود) =================
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data and data.startswith("like_"):
        try:
            existing_rows = list(query.message.reply_markup.inline_keyboard)
            first_row = list(existing_rows[0])
            current_text = first_row[0].text
            count = int(current_text.split(" ")[1]) + 1
        except Exception:
            count = 1
            existing_rows = list(query.message.reply_markup.inline_keyboard)
            first_row = list(existing_rows[0])

        first_row[0] = InlineKeyboardButton(f"❤️ {count}", callback_data=data)
        existing_rows[0] = first_row
        
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(existing_rows))
        except Exception as e:
            print(f"Error updating like button UI: {e}")

# ================= ۱۰. حلقه اصلی ۲۴ ساعته (هر نیم ساعت) =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید (نسخه قبلی در حال بسته شدن است)...")
    else:
        print(f"Telegram network/update warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    print("🚀 24/7 RSS News & Digital Store Bot is running (Every 30 mins | 15 News/cycle)...")
    tehran_tz = ZoneInfo("Asia/Tehran")

    # تاخیر ۱۵ ثانیه‌ای برای بسته شدن کامل کانتینر قبلی در Railway
    await asyncio.sleep(15)

    cycle_counter = 0
    while True:
        try:
            now_tehran = datetime.now(tehran_tz)
            cycle_counter += 1
            print(f"\n--- [Cycle #{cycle_counter} | {now_tehran.strftime('%Y-%m-%d %H:%M')} Tehran] ---")

            # بروزرسانی کش محصولات دیجیتالی سایت در ابتدای کار و هر ۴ چرخه یک‌بار (هر ۲ ساعت)
            if cycle_counter == 1 or cycle_counter % 4 == 0:
                await refresh_digital_products_cache()

            # ۱. جمع‌آوری سریع فیدها و انتشار حداکثر ۱۵ خبر برتر
            await fetch_rss_sources()
            print(f"Collected {len(pending_news_buffer)} new items. Selecting & editing top {MAX_NEWS_PER_CYCLE}...")
            await process_and_publish_batch()

            # ۲. ارسال محصولات دیجیتالی (اکانت بازی و پلاس) با ضریب شانس مبتنی بر هایپ اخبار
            await publish_weighted_digital_products()

        except Exception as e:
            print(f"Error in 24/7 background loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(button_click_handler))
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started (24/7 Mode)...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
