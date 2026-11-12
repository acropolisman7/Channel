import asyncio
import sqlite3
import re
import os
import json
import math
import html
import random
import statistics
import aiohttp
import feedparser
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

try:
    from telegram import ReplyParameters
except ImportError:
    ReplyParameters = None

# ================= ۱. تنظیمات اصلی و کلیدهای API =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]

GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")
NAVASAN_API_KEY = os.environ.get("NAVASAN_API_KEY", "")
BRSAPI_KEY = os.environ.get("BRSAPI_KEY", "")

TARGET_CHANNEL = '@jazebestore'
STORE_BASE_URL = '[https://jazebestore.com](https://jazebestore.com)'
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
DB_PATH = 'rss_news_history.db'

# تنظیمات زمانی: بررسی اخبار فوری هر ۳ دقیقه | چرخه کامل هر ۳۰ دقیقه | حداکثر ۳۵ کاندیدا در هر پرامپت (زیر سقف 7000 توکن Groq)
BREAKING_CHECK_INTERVAL_SECONDS = 180
REGULAR_CYCLE_SECONDS = 1800
MAX_NEWS_PER_CYCLE = 12
MAX_BREAKING_PER_CYCLE = 3
MAX_CANDIDATES_FOR_AI = 35
SEMANTIC_SIMILARITY_THRESHOLD = 0.78
CLUSTER_SIMILARITY_THRESHOLD = 0.72
HYPE_HALF_LIFE_HOURS = 18.0

# تنظیمات افزونه‌های روزانه و تعاملی
TEHRAN = ZoneInfo("Asia/Tehran")
USD_POST_HOUR = 11
USD_WINDOW_END_HOUR = 14
DAILY_REC_HOUR = 12
DAILY_REC_WINDOW_END_HOUR = 17
MEME_MAX_PER_CYCLE = 2
MEME_MIN_HYPE = 6
MEME_STANDALONE_GAP_MIN = 90
ARTICLE_MAX_CHARS = 1800
ENRICH_CHUNK = 3

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
REDDIT_UA = {"User-Agent": "jazebe-news-bot/1.0"}
MEME_SUBREDDITS = {
    "gaming", "memes", "pcmasterrace", "playstation", "ps5", "xbox", "nintendo", "nintendoswitch",
    "gamingmemes", "gamingcirclejerk", "dankmemes", "funny", "me_irl", "technology", "technicallythetruth",
    "movies", "television", "music", "bitcoin", "cryptocurrency", "apple", "iphone", "android", "gamephysics",
}

# مدل‌های فعال و به‌روز برای هر سه سرویس API
GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.8-flash', 'gemini-3.5-flash-lite']
GROQ_MODELS = ['llama-3.3-70b-versatile', 'openai/gpt-oss-120b', 'openai/gpt-oss-20b']
OPENROUTER_MODELS = ['meta-llama/llama-3.3-70b-instruct:free', 'google/gemma-3-27b-it:free', 'openrouter/free']
GEMINI_EMBEDDING_MODEL = 'text-embedding-004'

CATEGORY_HASHTAGS = {
    "gaming": "#گیمینگ",
    "technology": "#تکنولوژی",
    "hardware": "#سخت_افزار",
    "crypto": "#کریپتو",
    "film_tv": "#سینما_و_تلویزیون",
    "internet_culture": "#فرهنگ_اینترنتی",
    "fun_meme": "#فان_و_میم",
    "music": "#موسیقی",
    "general_news": "#اخبار_عمومی"
}

CATEGORY_PERSIAN_NAMES = {
    "gaming": "گیمینگ",
    "technology": "تکنولوژی",
    "hardware": "سخت‌افزار",
    "crypto": "کریپتو و بلاک‌چین",
    "film_tv": "سینما و تلویزیون",
    "internet_culture": "فرهنگ اینترنتی",
    "fun_meme": "فان، شوخی کاربران و میم",
    "music": "موسیقی",
    "general_news": "اخبار عمومی"
}

SERIALIZED_SERIES_HEADERS = {
    "Game of the Week": "🎮 مجموعه هفتگی: Game of the Week (بازی منتخب هفته)",
    "Movie of the Week": "🍿 مجموعه هفتگی: Movie of the Week (فیلم منتخب هفته)",
    "Tech Breakdown": "💻 پرونده فنی: Tech Breakdown (کالبدشکافی تکنولوژی)",
    "Weekly Gaming News": "⚡ مرور هفتگی: Weekly Gaming News (مهم‌ترین‌های گیمینگ)",
    "Best Hardware Deals": "🏆 راهنمای ارزش خرید: Best Hardware Deals",
    "This Week in Gaming": "🚀 رویدادهای هفته: This Week in Gaming"
}

BREAKING_TRIGGER_KEYWORDS = [
    "breaking", "officially announced", "official trailer", "release date announced",
    "delayed", "canceled", "cancelled", "state of play", "playstation showcase",
    "xbox games showcase", "gta vi", "gta 6", "ps5 pro", "nintendo switch 2",
    "rtx 5090", "rtx 5080", "فوری", "به‌طور رسمی معرفی شد", "تاریخ انتشار", "تریلر رسمی"
]

CATEGORIZED_RSS_SOURCES = {
    "gaming": [
        "[https://www.ign.com/rss/v2/articles/feed](https://www.ign.com/rss/v2/articles/feed)",
        "[https://feeds.feedburner.com/ign/news](https://feeds.feedburner.com/ign/news)",
        "[https://feeds.feedburner.com/ign/reviews](https://feeds.feedburner.com/ign/reviews)",
        "[https://feeds.feedburner.com/ign/games-all](https://feeds.feedburner.com/ign/games-all)",
        "[https://www.gamespot.com/feeds/mashup/](https://www.gamespot.com/feeds/mashup/)",
        "[https://www.eurogamer.net/?format=rss](https://www.eurogamer.net/?format=rss)",
        "[https://www.videogameschronicle.com/feed/](https://www.videogameschronicle.com/feed/)",
        "[https://www.pcgamer.com/feeds.xml](https://www.pcgamer.com/feeds.xml)",
        "[https://www.polygon.com/rss/index.xml](https://www.polygon.com/rss/index.xml)",
        "[https://kotaku.com/rss](https://kotaku.com/rss)",
        "[https://www.rockpapershotgun.com/feed](https://www.rockpapershotgun.com/feed)",
        "[https://www.gamesindustry.biz/feed](https://www.gamesindustry.biz/feed)",
        "[https://www.gematsu.com/feed](https://www.gematsu.com/feed)",
        "[https://www.pushsquare.com/feeds/latest](https://www.pushsquare.com/feeds/latest)",
        "[https://www.purexbox.com/feeds/latest](https://www.purexbox.com/feeds/latest)",
        "[https://www.nintendolife.com/feeds/latest](https://www.nintendolife.com/feeds/latest)",
        "[https://www.gamedeveloper.com/rss.xml](https://www.gamedeveloper.com/rss.xml)",
        "[https://blog.playstation.com/feed/](https://blog.playstation.com/feed/)",
        "[https://news.xbox.com/en-us/feed/](https://news.xbox.com/en-us/feed/)",
        "[https://www.zoomg.ir/feed/](https://www.zoomg.ir/feed/)",
        "[https://vigiato.net/feed](https://vigiato.net/feed)",
        "[https://gamefa.com/feed](https://gamefa.com/feed)"
    ],
    "technology": [
        "[https://www.theverge.com/rss/index.xml](https://www.theverge.com/rss/index.xml)",
        "[https://www.theverge.com/rss/tech/index.xml](https://www.theverge.com/rss/tech/index.xml)",
        "[https://feeds.arstechnica.com/arstechnica/index](https://feeds.arstechnica.com/arstechnica/index)",
        "[https://www.wired.com/feed/rss](https://www.wired.com/feed/rss)",
        "[https://techcrunch.com/feed/](https://techcrunch.com/feed/)",
        "[https://techcrunch.com/category/artificial-intelligence/feed/](https://techcrunch.com/category/artificial-intelligence/feed/)",
        "[https://www.engadget.com/rss.xml](https://www.engadget.com/rss.xml)",
        "[https://www.cnet.com/rss/news/](https://www.cnet.com/rss/news/)",
        "[https://www.techradar.com/feeds.xml](https://www.techradar.com/feeds.xml)",
        "[https://gizmodo.com/feed](https://gizmodo.com/feed)",
        "[https://mashable.com/feeds/rss/all](https://mashable.com/feeds/rss/all)",
        "[https://www.techmeme.com/feed.xml](https://www.techmeme.com/feed.xml)",
        "[https://feeds.macrumors.com/MacRumors-All](https://feeds.macrumors.com/MacRumors-All)",
        "[https://9to5mac.com/feed/](https://9to5mac.com/feed/)",
        "[https://www.zoomit.ir/feed/](https://www.zoomit.ir/feed/)",
        "[https://digiato.com/feed](https://digiato.com/feed)"
    ],
    "hardware": [
        "[https://www.tomshardware.com/feeds/all](https://www.tomshardware.com/feeds/all)",
        "[https://www.techspot.com/backend.xml](https://www.techspot.com/backend.xml)",
        "[https://www.notebookcheck.net/RSS-Feed.8156.0.html](https://www.notebookcheck.net/RSS-Feed.8156.0.html)",
        "[https://www.techpowerup.com/rss/news](https://www.techpowerup.com/rss/news)",
        "[https://www.youtube.com/feeds/videos.xml?channel_id=UCI8iQa1hv7oV_Z8D35vVuSg](https://www.youtube.com/feeds/videos.xml?channel_id=UCI8iQa1hv7oV_Z8D35vVuSg)",
        "[https://www.youtube.com/feeds/videos.xml?channel_id=UChIs72whgZI9w6d6FhwGGHA](https://www.youtube.com/feeds/videos.xml?channel_id=UChIs72whgZI9w6d6FhwGGHA)"
    ],
    "crypto": [
        "[https://www.coindesk.com/arc/outboundfeeds/rss/](https://www.coindesk.com/arc/outboundfeeds/rss/)",
        "[https://cointelegraph.com/rss](https://cointelegraph.com/rss)",
        "[https://www.theblock.co/rss.xml](https://www.theblock.co/rss.xml)",
        "[https://decrypt.co/feed](https://decrypt.co/feed)",
        "[https://bitcoinmagazine.com/feed](https://bitcoinmagazine.com/feed)",
        "[https://www.dlnews.com/arc/outboundfeeds/rss/](https://www.dlnews.com/arc/outboundfeeds/rss/)",
        "[https://blockworks.co/feed](https://blockworks.co/feed)",
        "[https://cryptoslate.com/feed/](https://cryptoslate.com/feed/)",
        "[https://thedefiant.io/feed](https://thedefiant.io/feed)",
        "[https://u.today/rss](https://u.today/rss)",
        "[https://beincrypto.com/feed/](https://beincrypto.com/feed/)",
        "[https://protos.com/feed](https://protos.com/feed)"
    ],
    "film_tv": [
        "[https://variety.com/feed/](https://variety.com/feed/)",
        "[https://variety.com/v/film/feed/](https://variety.com/v/film/feed/)",
        "[https://variety.com/v/tv/feed/](https://variety.com/v/tv/feed/)",
        "[https://variety.com/v/music/feed/](https://variety.com/v/music/feed/)",
        "[https://www.hollywoodreporter.com/feed/](https://www.hollywoodreporter.com/feed/)",
        "[https://deadline.com/feed/](https://deadline.com/feed/)",
        "[https://www.indiewire.com/feed/](https://www.indiewire.com/feed/)",
        "[https://www.thewrap.com/feed/](https://www.thewrap.com/feed/)",
        "[https://collider.com/feed/](https://collider.com/feed/)",
        "[https://screenrant.com/feed/](https://screenrant.com/feed/)",
        "[https://www.rogerebert.com/feed](https://www.rogerebert.com/feed)",
        "[https://www.avclub.com/rss](https://www.avclub.com/rss)",
        "[https://consequence.net/feed/](https://consequence.net/feed/)",
        "[https://www.slashfilm.com/feed/](https://www.slashfilm.com/feed/)",
        "[https://www.denofgeek.com/feed/](https://www.denofgeek.com/feed/)",
        "[https://bloody-disgusting.com/feed/](https://bloody-disgusting.com/feed/)"
    ],
    "internet_culture": [
        "[https://knowyourmeme.com/newsfeed.rss](https://knowyourmeme.com/newsfeed.rss)",
        "[https://knowyourmeme.com/editorials.rss](https://knowyourmeme.com/editorials.rss)",
        "[https://www.tmz.com/rss.xml](https://www.tmz.com/rss.xml)",
        "[https://www.buzzfeed.com/index.xml](https://www.buzzfeed.com/index.xml)",
        "[https://www.dexerto.com/feed/](https://www.dexerto.com/feed/)",
        "[https://www.complex.com/feed/](https://www.complex.com/feed/)",
        "[https://www.thedailybeast.com/feed](https://www.thedailybeast.com/feed)",
        "[https://www.vulture.com/rss/index.xml](https://www.vulture.com/rss/index.xml)",
        "[https://www.themarysue.com/feed/](https://www.themarysue.com/feed/)"
    ],
    "music": [
        "[https://www.billboard.com/feed/](https://www.billboard.com/feed/)",
        "[https://www.rollingstone.com/feed/](https://www.rollingstone.com/feed/)",
        "[https://pitchfork.com/feed/feed-news/rss](https://pitchfork.com/feed/feed-news/rss)",
        "[https://pitchfork.com/feed/feed-album-reviews/rss](https://pitchfork.com/feed/feed-album-reviews/rss)",
        "[https://www.stereogum.com/feed/](https://www.stereogum.com/feed/)",
        "[https://www.nme.com/feed](https://www.nme.com/feed)",
        "[https://www.musicbusinessworldwide.com/feed/](https://www.musicbusinessworldwide.com/feed/)",
        "[https://www.thefader.com/rss](https://www.thefader.com/rss)",
        "[https://feeds.npr.org/1039/rss.xml](https://feeds.npr.org/1039/rss.xml)",
        "[https://www.digitalmusicnews.com/feed/](https://www.digitalmusicnews.com/feed/)",
        "[https://musictech.com/feed/](https://musictech.com/feed/)",
        "[https://ra.co/xml](https://ra.co/xml)",
        "[https://www.spin.com/feed/](https://www.spin.com/feed/)"
    ],
    "general_news": [
        "[https://feeds.bbci.co.uk/news/rss.xml](https://feeds.bbci.co.uk/news/rss.xml)",
        "[https://feeds.bbci.co.uk/news/technology/rss.xml](https://feeds.bbci.co.uk/news/technology/rss.xml)",
        "[https://www.theguardian.com/world/rss](https://www.theguardian.com/world/rss)",
        "[https://feeds.npr.org/1001/rss.xml](https://feeds.npr.org/1001/rss.xml)",
        "[https://www.aljazeera.com/xml/rss/all.xml](https://www.aljazeera.com/xml/rss/all.xml)",
        "[https://www.bloomberg.com/feeds/news.rss](https://www.bloomberg.com/feeds/news.rss)",
        "[https://www.bloomberg.com/feeds/markets/news.rss](https://www.bloomberg.com/feeds/markets/news.rss)",
        "[https://www.ft.com/rss/home/international](https://www.ft.com/rss/home/international)",
        "[https://www.cnbc.com/id/100003114/device/rss/rss.html](https://www.cnbc.com/id/100003114/device/rss/rss.html)",
        "[https://www.economist.com/finance-and-economics/rss.xml](https://www.economist.com/finance-and-economics/rss.xml)",
        "[https://news.google.com/rss/search?q=site%3Areuters.com&hl=en-US&gl=US&ceid=US:en](https://news.google.com/rss/search?q=site%3Areuters.com&hl=en-US&gl=US&ceid=US:en)",
        "[https://news.google.com/rss/search?q=site%3Aapnews.com&hl=en-US&gl=US&ceid=US:en](https://news.google.com/rss/search?q=site%3Aapnews.com&hl=en-US&gl=US&ceid=US:en)"
    ]
}

# ================= ۲. راه‌اندازی دیتابیس و مدیریت چرخه حیات خبر =================
bot = Bot(token=TELEGRAM_BOT_TOKEN)
os.makedirs('temp_media', exist_ok=True)
provider_rotation_index = 0
_extra_ai_rot = 0

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    category TEXT,
                    source TEXT,
                    raw_title TEXT,
                    raw_text TEXT,
                    image_url TEXT,
                    has_video_or_audio INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'discovered',
                    is_breaking_candidate INTEGER DEFAULT 0,
                    source_count INTEGER DEFAULT 1,
                    retry_count INTEGER DEFAULT 0,
                    embedding_json TEXT,
                    ai_payload_json TEXT,
                    topic_fingerprint TEXT,
                    published_category TEXT,
                    published_headline TEXT,
                    related_entity TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS hype_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_name TEXT,
                    category TEXT,
                    score REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )''')
    conn.commit()
    conn.close()

def get_metadata(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_metadata WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_metadata(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_metadata (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def update_news_status(item_ids: list[int], new_status: str, increment_retry: bool = False):
    if not item_ids:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(item_ids))
    if new_status == 'published':
        c.execute(f"UPDATE news_items SET status = ?, published_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                  [new_status] + item_ids)
    elif increment_retry:
        c.execute(f"UPDATE news_items SET status = ?, retry_count = retry_count + 1 WHERE id IN ({placeholders})",
                  [new_status] + item_ids)
    else:
        c.execute(f"UPDATE news_items SET status = ? WHERE id IN ({placeholders})",
                  [new_status] + item_ids)
    conn.commit()
    conn.close()

def save_published_news_details(item_id: int, fingerprint: str, pub_cat: str, pub_headline: str, related_entity: str, ai_payload: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE news_items
        SET status = 'published',
            published_at = CURRENT_TIMESTAMP,
            topic_fingerprint = ?,
            published_category = ?,
            published_headline = ?,
            related_entity = ?,
            ai_payload_json = ?
        WHERE id = ?
    """, (fingerprint, pub_cat, pub_headline, related_entity, json.dumps(ai_payload, ensure_ascii=False), item_id))
    conn.commit()
    conn.close()

# ================= ۳. زبان فارسی، تاریخ شمسی و ویرایش نگارشی =================
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_PERSIAN = "\u0600-\u06FF"
JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
GREG_MONTHS_FA = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
                  "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]

def get_current_tehran_time() -> datetime:
    return datetime.now(TEHRAN)

def to_fa_digits(value) -> str:
    return str(value).translate(str.maketrans("0123456789", _FA_DIGITS))

def to_en_digits(value) -> str:
    return str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))

def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd

def format_dates(dt: datetime) -> dict:
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    weekday = WEEKDAYS_FA[dt.weekday()]
    return {
        "weekday": weekday,
        "jalali": f"{to_fa_digits(jd)} {JALALI_MONTHS[jm - 1]} {to_fa_digits(jy)}",
        "gregorian": f"{to_fa_digits(dt.day)} {GREG_MONTHS_FA[dt.month - 1]} {to_fa_digits(dt.year)}",
        "date_key": dt.strftime("%Y-%m-%d"),
    }

def persian_polish(text: str) -> str:
    if not text:
        return text
    t = text.replace("ي", "ی").replace("ك", "ک")
    t = re.sub(rf"(?<![{_PERSIAN}])(ن?می) (?=[{_PERSIAN}]{{2,}})", "\\1\u200c", t)
    t = re.sub(rf"(?<=[{_PERSIAN}]) (ها|های)(?![{_PERSIAN}])", "\u200c\\1", t)
    t = re.sub(rf"(?<=[{_PERSIAN}]),", "،", t)
    t = re.sub(rf"(?<=[{_PERSIAN}])\?", "؟", t)
    t = re.sub(rf"(?<=[{_PERSIAN}]);", "؛", t)
    t = re.sub(r"\s+([،؛؟.!])", r"\1", t)
    return t.strip()

def polish_selected(sel) -> None:
    for field in ("headline_persian", "summary_persian", "background_persian",
                  "image_alt_persian", "av_transcript_summary_persian"):
        val = getattr(sel, field, "")
        if val:
            setattr(sel, field, persian_polish(val))
    if getattr(sel, "key_points_persian", None):
        sel.key_points_persian = [persian_polish(p) for p in sel.key_points_persian]

# ================= ۴. موتور Embedding و محاسبه Cosine Similarity =================
def compute_local_ngram_embedding(text: str, dim: int = 256) -> list[float]:
    clean = re.sub(r'[^\w\s]', ' ', text.lower())
    tokens = [t for t in clean.split() if len(t) > 2]
    vec = [0.0] * dim
    if not tokens:
        return vec
    counts = Counter(tokens)
    for i in range(len(tokens) - 1):
        counts[f"{tokens[i]}_{tokens[i+1]}"] += 1.5
    for token, weight in counts.items():
        h = hash(token)
        idx = abs(h) % dim
        sign = 1.0 if (h & 1) == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log1p(weight))
    norm = math.sqrt(sum(x * x for x in vec))
    return [round(x / norm, 5) for x in vec] if norm > 0 else vec

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

async def run_semantic_clustering_and_deduplication():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, raw_title, raw_text, source, is_breaking_candidate
        FROM news_items
        WHERE status = 'discovered'
        ORDER BY id ASC LIMIT 120
    """)
    discovered_rows = c.fetchall()
    if not discovered_rows:
        conn.close()
        return

    c.execute("""
        SELECT embedding_json, raw_title
        FROM news_items
        WHERE status = 'published' AND published_at >= datetime('now', '-72 hours')
        ORDER BY id DESC LIMIT 150
    """)
    published_rows = c.fetchall()
    conn.close()

    published_embeddings = []
    for emb_str, pub_title in published_rows:
        if emb_str:
            try:
                published_embeddings.append((json.loads(emb_str), pub_title))
            except Exception:
                pass

    discovered_items = []
    for row_id, r_title, r_text, src, is_brk in discovered_rows:
        emb = compute_local_ngram_embedding(f"{r_title} {r_text}")
        discovered_items.append({
            'id': row_id,
            'title': r_title,
            'text': r_text,
            'source': src,
            'is_breaking': is_brk,
            'emb': emb
        })

    rejected_ids = []
    valid_items = []
    for item in discovered_items:
        is_dup = False
        for pub_emb, _ in published_embeddings:
            if len(pub_emb) == len(item['emb']) and cosine_similarity(item['emb'], pub_emb) >= SEMANTIC_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            rejected_ids.append(item['id'])
        else:
            valid_items.append(item)

    clusters = []
    for item in valid_items:
        placed = False
        for cluster in clusters:
            rep = cluster[0]
            if cosine_similarity(item['emb'], rep['emb']) >= CLUSTER_SIMILARITY_THRESHOLD:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if rejected_ids:
        placeholders = ",".join(["?"] * len(rejected_ids))
        c.execute(f"UPDATE news_items SET status = 'rejected' WHERE id IN ({placeholders})", rejected_ids)

    for cluster in clusters:
        primary = cluster[0]
        unique_sources = len({x['source'] for x in cluster})
        is_breaking = 1 if (any(x['is_breaking'] for x in cluster) or unique_sources >= 3) else 0
        c.execute("""
            UPDATE news_items
            SET status = 'pending',
                source_count = ?,
                is_breaking_candidate = ?,
                embedding_json = ?
            WHERE id = ?
        """, (unique_sources, is_breaking, json.dumps(primary['emb']), primary['id']))
        for extra in cluster[1:]:
            c.execute("UPDATE news_items SET status = 'rejected' WHERE id = ?", (extra['id'],))

    conn.commit()
    conn.close()

# ================= ۵. الگوریتم هایپ زمان‌دار (Decay) و شناسایی ترند ۲۴ ساعته =================
def record_hype_event(entity_name: str, category: str, score: float):
    if not entity_name or len(entity_name.strip()) < 2:
        return
    clean_name = entity_name.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO hype_events (entity_name, category, score, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (clean_name, category, float(max(1.0, min(score, 10.0)))))
    c.execute("DELETE FROM hype_events WHERE created_at < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

def detect_24h_trends(top_n: int = 8) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT entity_name, COUNT(*) as mentions, SUM(score) as total_score
        FROM hype_events
        WHERE created_at >= datetime('now', '-24 hours')
        GROUP BY entity_name
        ORDER BY total_score DESC, mentions DESC
        LIMIT ?
    """, (top_n,))
    rows = c.fetchall()
    conn.close()
    return [{"entity": r[0], "mentions": r[1], "score": round(r[2], 1)} for r in rows]

# ================= ۶. توابع پاک‌سازی، Sanitization HTML و ارسال امن =================
def clean_raw_text(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def sanitize_telegram_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*em\s*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*em\s*>', '</i>', text, flags=re.IGNORECASE)

    allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'blockquote']
    placeholders = {}
    counter = 0

    for tag in allowed_tags:
        pattern = re.compile(fr'<{tag}>(.*?)</{tag}>', flags=re.IGNORECASE | re.DOTALL)
        while True:
            match = pattern.search(text)
            if not match:
                break
            inner_content = match.group(1)
            open_tok = f"__TG_OPEN_{tag.upper()}_{counter}__"
            close_tok = f"__TG_CLOSE_{tag.upper()}_{counter}__"
            placeholders[open_tok] = f"<{tag}>"
            placeholders[close_tok] = f"</{tag}>"
            counter += 1
            text = text[:match.start()] + open_tok + inner_content + close_tok + text[match.end():]

    text = re.sub(r'<[^>]+>', '', text)
    text = html.escape(text)

    for tok, real_tag in placeholders.items():
        text = text.replace(tok, real_tag)

    return text.strip()

def extract_rss_media_info(entry) -> tuple[str | None, bool]:
    img_url = None
    has_av = False

    if 'media_content' in entry and len(entry.media_content) > 0:
        for mc in entry.media_content:
            m_type = str(mc.get('type', '')).lower()
            m_url = mc.get('url', '')
            if 'video' in m_type or 'audio' in m_type or 'youtube.com' in m_url:
                has_av = True
            elif not img_url and m_url:
                img_url = m_url

    if not img_url and 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        img_url = entry.media_thumbnail[0].get('url')

    link_str = getattr(entry, 'link', '') or ''
    if 'youtube.com' in link_str or 'youtu.be' in link_str or 'twitch.tv' in link_str:
        has_av = True

    html_body = getattr(entry, 'summary', '') or ''
    if hasattr(entry, 'content') and len(entry.content) > 0:
        html_body += entry.content[0].value
    soup = BeautifulSoup(html_body, 'html.parser')
    if soup.find(['video', 'audio', 'iframe']):
        has_av = True
    if not img_url:
        img_tag = soup.find('img')
        if img_tag and img_tag.get('src'):
            img_url = img_tag['src']

    return img_url, has_av

async def download_image_from_url(session: aiohttp.ClientSession, url: str, filename: str) -> str | None:
    if not url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
            if resp.status == 200:
                filepath = os.path.join('temp_media', filename)
                with open(filepath, 'wb') as f:
                    f.write(await resp.read())
                return filepath
    except Exception as e:
        print(f"Error downloading image {url}: {e}")
    return None

def _visible_len(text: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))

def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))

def _fit_lines(text: str, limit: int) -> str:
    if _visible_len(text) <= limit:
        return text
    lines = text.split("\n")
    tail = lines[-1]
    kept = []
    for line in lines[:-1]:
        if _visible_len("\n".join(kept + [line, tail])) > limit:
            break
        kept.append(line)
    return "\n".join(kept + [tail])

def _short_caption(text: str, limit: int = 260) -> str:
    kept = []
    for line in text.split("\n"):
        if not line.strip():
            if kept:
                break
            continue
        if kept and _visible_len("\n".join(kept + [line])) > limit:
            break
        kept.append(line)
    return "\n".join(kept)

def _reply_kwargs(message_id):
    if not message_id:
        return {}
    if ReplyParameters is not None:
        return {"reply_parameters": ReplyParameters(message_id=message_id, allow_sending_without_reply=True)}
    return {"reply_to_message_id": message_id, "allow_sending_without_reply": True}

async def send_post(session, text, image_url=None, reply_markup=None, silent=False,
                    reply_to=None, filename="post.jpg", link_preview=False):
    text = _fit_lines(text, 4000)

    async def send_text(body, parse_mode, markup, reply_id):
        return await bot.send_message(
            chat_id=TARGET_CHANNEL, text=body, parse_mode=parse_mode, reply_markup=markup,
            disable_notification=silent, disable_web_page_preview=not link_preview,
            **_reply_kwargs(reply_id))

    async def send_photo(path, caption, parse_mode, markup, reply_id):
        with open(path, "rb") as fh:
            return await bot.send_photo(
                chat_id=TARGET_CHANNEL, photo=fh, caption=caption, parse_mode=parse_mode, reply_markup=markup,
                disable_notification=silent, **_reply_kwargs(reply_id))

    img_path = None
    if image_url:
        img_path = await download_image_from_url(session, image_url, filename)
    try:
        async def attempt(body, parse_mode):
            if img_path and os.path.exists(img_path):
                try:
                    if _visible_len(body) <= 1000:
                        return await send_photo(img_path, body, parse_mode, reply_markup, reply_to)
                    photo_msg = await send_photo(img_path, _short_caption(body), parse_mode, None, reply_to)
                    return await send_text(body, parse_mode, reply_markup, photo_msg.message_id)
                except Exception as photo_err:
                    if "entities" in str(photo_err).lower() or "parse" in str(photo_err).lower():
                        raise
                    print(f"⚠️ ارسال عکس ناموفق بود، ارسال متنی: {photo_err}")
            return await send_text(body, parse_mode, reply_markup, reply_to)

        try:
            return await attempt(text, "HTML")
        except Exception as err:
            if "entities" in str(err).lower() or "parse" in str(err).lower():
                print("⚠️ خطای HTML؛ ارسال نسخه‌ی متن ساده.")
                return await attempt(_strip_tags(text), None)
            raise
    finally:
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass

# ================= ۷. پین کردن تا ۰۰:۰۰ =================
def _pins_load() -> list:
    try:
        return json.loads(get_metadata("pinned_posts", "[]"))
    except Exception:
        return []

async def pin_post(message_id: int):
    try:
        await bot.pin_chat_message(chat_id=TARGET_CHANNEL, message_id=message_id, disable_notification=True)
        pins = _pins_load()
        pins.append({"id": message_id, "date": get_current_tehran_time().strftime("%Y-%m-%d")})
        set_metadata("pinned_posts", json.dumps(pins))
        print(f"📌 پست {message_id} پین شد (تا ۰۰:۰۰ همین روز).")
    except Exception as e:
        print(f"⚠️ پین ناموفق (ربات باید ادمین با دسترسی Pin Messages باشد): {e}")

async def unpin_expired_pins(session=None):
    today = get_current_tehran_time().strftime("%Y-%m-%d")
    pins = _pins_load()
    if not pins:
        return
    remaining = []
    for pin in pins:
        if pin.get("date", today) < today:
            try:
                await bot.unpin_chat_message(chat_id=TARGET_CHANNEL, message_id=pin["id"])
                print(f"📍 پین پست {pin['id']} برداشته شد.")
            except Exception as e:
                msg = str(e).lower()
                if "not found" in msg or "not modified" in msg or "message to unpin" in msg:
                    continue
                remaining.append(pin)
                print(f"⚠️ خطا در برداشتن پین: {e}")
        else:
            remaining.append(pin)
    set_metadata("pinned_posts", json.dumps(remaining))

# ================= ۸. ساختار خروجی هوش مصنوعی (Schema یکپارچه برای هر ۳ سرویس) =================
class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="ID of the selected news candidate")
    category_id: str = Field(description="One of: gaming, technology, hardware, crypto, film_tv, internet_culture, fun_meme, music, general_news")
    verification_status: str = Field(description="Must be one of: 'خبر رسمی', 'گزارش رسانه معتبر', 'شایعه و لیک', 'خبر تأییدنشده'")
    confidence_score: int = Field(default=85, description="Confidence percentage between 40 and 100 based on source reliability and confirmation")
    is_breaking: bool = Field(default=False, description="True if this is major breaking news requiring immediate attention")
    is_new_game_release: bool = Field(default=False, description="True if the news is about a new game release or pre-order announcement")
    series_name: str = Field(default="", description="Optional recurring series name if applicable: 'Game of the Week', 'Movie of the Week', 'Tech Breakdown', 'Weekly Gaming News', 'Best Hardware Deals', 'This Week in Gaming', or empty string")
    headline_persian: str = Field(description="Descriptive, clear Persian headline without HTML tags or emojis")
    summary_persian: str = Field(description="Detailed, accurate, well-edited Persian summary (4-6 short sentences) answering who/what/when/where/why with every concrete name, number, date, platform and price from the source; wrap 1 to 4 key facts in <b>...</b>")
    key_points_persian: list[str] = Field(description="3 to 5 short, factual bullet points in Persian (e.g., 'تاریخ انتشار: ...', 'پلتفرم‌ها: ...', 'قیمت: ...')")
    background_persian: str = Field(default="", description="1-2 sentence Persian background/context supported by the source text, or empty string")
    image_alt_persian: str = Field(default="", description="Clear Persian visual description of the news context/image for blind/screen-reader users")
    av_transcript_summary_persian: str = Field(default="", description="If the source contains video/trailer/audio, provide a clear Persian text transcript/summary of what happens or is said in the video for deaf users")
    topic_hashtags: list[str] = Field(description="2 to 3 specific Persian hashtags starting with # using underscores")
    topic_fingerprint: str = Field(description="1-sentence English summary for deduplication")
    related_game: str = Field(default="", description="Exact English canonical name of the related game, service, or console, otherwise empty string")
    hype_score: int = Field(default=5, description="Hype and viral importance score from 1 to 10")

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۹. موتور پردازش ۳ گانه AI با اعتبارسنجی Pydantic و Retry =================
JSON_SCHEMA_INSTRUCTION = """
Respond ONLY with a valid JSON object matching this exact schema (no markdown fences):
{
  "selected_news": [
    {
      "selected_id": 1,
      "category_id": "gaming",
      "verification_status": "خبر رسمی",
      "confidence_score": 95,
      "is_breaking": false,
      "is_new_game_release": false,
      "series_name": "",
      "headline_persian": "تأیید تاریخ انتشار بازی GTA VI توسط Rockstar",
      "summary_persian": "شرکت Rockstar به‌طور رسمی اعلام کرد که <b>پاییز سال جاری</b> نسخه جدید این مجموعه عرضه خواهد شد.",
      "key_points_persian": [
        "پلتفرم‌های مقصد: PlayStation 5 و Xbox Series X/S",
        "وضعیت توسعه: ورود به مرحله پولیش نهایی",
        "ناشر: Rockstar Games"
      ],
      "background_persian": "این عنوان پس از چند بار تأخیر، حالا وارد مرحله‌ی پولیش نهایی شده است.",
      "image_alt_persian": "تصویر تبلیغاتی رسمی بازی GTA VI با نمایش شخصیت‌های اصلی در فضای شهری",
      "av_transcript_summary_persian": "",
      "topic_hashtags": ["#راکستار", "#جی_تی_ای"],
      "topic_fingerprint": "Rockstar officially confirms GTA VI release window",
      "related_game": "GTA VI",
      "hype_score": 9
    }
  ]
}
"""

def _extract_json_from_llm_content(raw_content: str | None) -> dict:
    if not raw_content or not isinstance(raw_content, str):
        raise ValueError("Empty or None content returned from LLM")
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
    # استخراج اولین بلوک JSON معتبر در صورت وجود متن اضافی در ابتدا یا انتها
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)

async def call_gemini_provider(prompt: str) -> BatchProcessResult | None:
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            for attempt in range(1, 3):
                try:
                    print(f"تلاش با Gemini (کلید #{key_idx} | مدل: {model_name} | نوبت {attempt})...")
                    response = await asyncio.to_thread(
                        temp_client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=BatchProcessResult,
                            temperature=0.25
                        )
                    )
                    raw_dict = _extract_json_from_llm_content(response.text)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت و اعتبارسنجی Schema با Gemini (کلید #{key_idx} | {model_name})")
                    return validated
                except (ValidationError, json.JSONDecodeError, ValueError) as ve:
                    print(f"⚠️ خطای اعتبارسنجی Schema در Gemini: {ve}")
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"⚠️ خطا در ارتباط با Gemini (کلید #{key_idx} | {model_name}): {e}")
                    await asyncio.sleep(1.5)
                    break
    return None

async def call_groq_provider(prompt: str) -> BatchProcessResult | None:
    for key_idx, groq_key in enumerate(GROQ_API_KEYS, start=1):
        groq_client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        for model_name in GROQ_MODELS:
            for attempt in range(1, 3):
                try:
                    print(f"تلاش با Groq (کلید #{key_idx} | مدل: {model_name} | نوبت {attempt})...")
                    completion = await groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.25
                    )
                    content = completion.choices[0].message.content if completion.choices else None
                    raw_dict = _extract_json_from_llm_content(content)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت و اعتبارسنجی Schema با Groq (کلید #{key_idx} | {model_name})")
                    return validated
                except (ValidationError, json.JSONDecodeError, ValueError) as ve:
                    print(f"⚠️ خطای اعتبارسنجی Schema در Groq ({model_name}): {ve}")
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"⚠️ خطا در Groq (کلید #{key_idx} | {model_name}): {e}")
                    await asyncio.sleep(1)
                    break
    return None

async def call_openrouter_provider(prompt: str) -> BatchProcessResult | None:
    for key_idx, or_key in enumerate(OPENROUTER_API_KEYS, start=1):
        or_client = AsyncOpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        for model_name in OPENROUTER_MODELS:
            for attempt in range(1, 3):
                try:
                    print(f"تلاش با OpenRouter (کلید #{key_idx} | مدل: {model_name} | نوبت {attempt})...")
                    # عدم ارسال اجباری response_format در OpenRouter برای جلوگیری از بازگشت None در مدل‌های رایگان
                    completion = await or_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.25
                    )
                    content = completion.choices[0].message.content if completion.choices else None
                    raw_dict = _extract_json_from_llm_content(content)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت و اعتبارسنجی Schema با OpenRouter (کلید #{key_idx} | {model_name})")
                    return validated
                except (ValidationError, json.JSONDecodeError, ValueError) as ve:
                    print(f"⚠️ خطای اعتبارسنجی Schema در OpenRouter ({model_name}): {ve}")
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"⚠️ خطا در OpenRouter (کلید #{key_idx} | {model_name}): {e}")
                    await asyncio.sleep(1)
                    break
    return None

async def generate_news_with_fallback(prompt: str) -> BatchProcessResult | None:
    global provider_rotation_index
    providers = [call_gemini_provider, call_groq_provider, call_openrouter_provider]
    ordered_providers = providers[provider_rotation_index % 3:] + providers[:provider_rotation_index % 3]
    provider_rotation_index += 1

    for provider_fn in ordered_providers:
        validated_result = await provider_fn(prompt)
        if validated_result and validated_result.selected_news:
            return validated_result
    return None

async def ask_ai_json(prompt: str, model_cls, temperature: float = 0.5):
    global _extra_ai_rot
    schema_hint = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    sys_msg = ("You are a JSON API. Respond ONLY with one valid JSON object (no markdown fences) "
               "that validates against this JSON Schema:\n" + schema_hint)

    async def gemini_fn():
        for key in GEMINI_API_KEYS:
            client = genai.Client(api_key=key)
            for model in GEMINI_MODELS:
                try:
                    resp = await asyncio.to_thread(
                        client.models.generate_content, model=model, contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json", response_schema=model_cls, temperature=temperature))
                    return model_cls.model_validate(_extract_json_from_llm_content(resp.text))
                except (ValidationError, json.JSONDecodeError, ValueError):
                    continue
                except Exception:
                    break
        return None

    async def openai_compat(keys, base_url, models, use_json_mode: bool = True):
        for key in keys:
            client = AsyncOpenAI(api_key=key, base_url=base_url)
            for model in models:
                try:
                    kwargs = {
                        "model": model,
                        "temperature": temperature,
                        "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
                    }
                    if use_json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    comp = await client.chat.completions.create(**kwargs)
                    content = comp.choices[0].message.content if comp.choices else None
                    return model_cls.model_validate(_extract_json_from_llm_content(content))
                except (ValidationError, json.JSONDecodeError, ValueError):
                    continue
                except Exception:
                    break
        return None

    backends = [
        gemini_fn,
        lambda: openai_compat(GROQ_API_KEYS, "https://api.groq.com/openai/v1", GROQ_MODELS, True),
        lambda: openai_compat(OPENROUTER_API_KEYS, "https://openrouter.ai/api/v1", OPENROUTER_MODELS, False),
    ]
    start = _extra_ai_rot % 3
    _extra_ai_rot += 1
    for fn in backends[start:] + backends[:start]:
        result = await fn()
        if result:
            return result
    return None

# ================= ۱۰. پست روزانه قیمت دلار (ساعت ۱۱) + بیتی از سعدی =================
FALLBACK_VERSES = [
    ("بنی‌آدم اعضای یکدیگرند", "که در آفرینش ز یک گوهرند", "گلستان، باب اول، حکایت ۱۰"),
    ("چو عضوی به درد آورد روزگار", "دگر عضوها را نماند قرار", "گلستان، باب اول، حکایت ۱۰"),
    ("تو کز محنت دیگران بی‌غمی", "نشاید که نامت نهند آدمی", "گلستان، باب اول، حکایت ۱۰"),
    ("دوست آن باشد که گیرد دست دوست", "در پریشان‌حالی و درماندگی", "دیوان سعدی"),
]

def _extract_beit(poem: dict):
    verses = poem.get("verses") or []
    full_url = poem.get("fullUrl") or ""
    if not full_url.startswith("/saadi"):
        return None
    pairs = []
    for i in range(len(verses) - 1):
        a, b = verses[i], verses[i + 1]
        if a.get("versePosition") == 0 and b.get("versePosition") == 1:
            m1, m2 = (a.get("text") or "").strip(), (b.get("text") or "").strip()
            if 8 <= len(m1) <= 90 and 8 <= len(m2) <= 90:
                pairs.append((m1, m2))
    if not pairs:
        return None
    m1, m2 = random.choice(pairs)
    return {"m1": persian_polish(m1), "m2": persian_polish(m2),
            "title": poem.get("fullTitle") or "دیوان سعدی",
            "url": "https://ganjoor.net" + full_url}

async def fetch_saadi_verse(session) -> dict:
    base = "https://api.ganjoor.net/api/ganjoor"
    try:
        poet_id = get_metadata("ganjoor_saadi_id", "")
        if not poet_id:
            async with session.get(f"{base}/poets", timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
                poets = await resp.json(content_type=None)
            for p in poets:
                name = (p.get("name") or "").replace("ي", "ی")
                if (p.get("fullUrl") or "").strip("/") == "saadi" or name.strip() == "سعدی":
                    poet_id = str(p["id"])
                    set_metadata("ganjoor_saadi_id", poet_id)
                    break
        if poet_id:
            for _ in range(8):
                try:
                    async with session.get(f"{base}/poem/random?poetId={poet_id}", timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
                        if resp.status != 200:
                            continue
                        poem = await resp.json(content_type=None)
                    beit = _extract_beit(poem)
                    if beit:
                        return beit
                except Exception:
                    continue
    except Exception as e:
        print(f"⚠️ دریافت شعر از گنجور ناموفق: {e}")
    m1, m2, title = random.choice(FALLBACK_VERSES)
    return {"m1": m1, "m2": m2, "title": title, "url": "https://ganjoor.net/saadi/"}

def _usd_ok(v) -> bool:
    return isinstance(v, int) and 20_000 <= v <= 3_000_000

async def _usd_tgju(session):
    for url in ("https://call5.tgju.org/ajax.json", "https://call4.tgju.org/ajax.json"):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
            raw = data["current"]["price_dollar_rl"]["p"]
            return int(to_en_digits(raw).replace(",", "")) // 10
        except Exception:
            continue
    return None

async def _usd_alanchand(session):
    try:
        async with session.get("https://alanchand.com/currencies-price/usd", timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
            if resp.status != 200:
                return None
            page = await resp.text()
        text = to_en_digits(BeautifulSoup(page, "html.parser").get_text(" ", strip=True))
        m = re.search(r"دلار[^\d]{0,120}?(\d{2,3},\d{3})", text)
        return int(m.group(1).replace(",", "")) if m else None
    except Exception:
        return None

async def _usd_navasan(session):
    if not NAVASAN_API_KEY:
        return None
    try:
        url = f"http://api.navasan.tech/latest/?api_key={NAVASAN_API_KEY}&item=usd_sell"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
            data = await resp.json(content_type=None)
        return int(float(to_en_digits(data["usd_sell"]["value"]).replace(",", "")))
    except Exception:
        return None

async def _usd_brsapi(session):
    if not BRSAPI_KEY:
        return None
    try:
        url = f"https://brsapi.ir/Api/Market/Gold_Currency.php?key={BRSAPI_KEY}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
            data = await resp.json(content_type=None)
        for item in data.get("currency", []):
            if str(item.get("symbol", "")).upper() == "USD":
                v = int(float(to_en_digits(item.get("price", 0)).replace(",", "")))
                return v // 10 if v > 3_000_000 else v
    except Exception:
        return None
    return None

async def get_usd_toman(session):
    fetchers = [("tgju.org", _usd_tgju), ("alanchand.com", _usd_alanchand),
                ("navasan.tech", _usd_navasan), ("brsapi.ir", _usd_brsapi)]
    results = await asyncio.gather(*(f(session) for _, f in fetchers), return_exceptions=True)
    got = [(name, v) for (name, _), v in zip(fetchers, results) if _usd_ok(v)]
    if not got:
        return None
    return int(statistics.median(v for _, v in got)), got

def _fa_money(value: int) -> str:
    return to_fa_digits(f"{value:,}").replace(",", "٬")

def build_usd_post(value: int, sources: list, verse: dict, dt: datetime) -> str:
    d = format_dates(dt)
    lines = [
        "💵 <b>قیمت امروز دلار آمریکا</b> | بازار آزاد",
        f"📅 <b>{d['weekday']}</b>، {d['jalali']} | {d['gregorian']}",
        "",
        f"💰 هر دلار آمریکا: <b>{_fa_money(value)} تومان</b>",
    ]
    if len(sources) >= 2:
        detail = " ، ".join(f"{html.escape(n)}: {_fa_money(v)}" for n, v in sources)
        lines.append(f"🔎 نرخ گزارش‌شده در منابع: {detail}")
        lines.append("ℹ️ عدد اعلام‌شده، میانه‌ی نرخ منابع بالاست.")
    else:
        lines.append(f"🔎 منبع: {html.escape(sources[0][0])}")
    lines.append("ℹ️ نرخ‌ها لحظه‌ای‌اند و ممکن است میان صرافی‌ها اندکی تفاوت داشته باشند.")
    lines += [
        "",
        "📜 <b>بیتی از سعدی</b>",
        f"<blockquote>{html.escape(verse['m1'])}\n{html.escape(verse['m2'])}</blockquote>",
        f"✍️ سعدی شیرازی | <a href=\"{html.escape(verse['url'])}\">{html.escape(verse['title'])}</a> (گنجور)",
        f"\n🏷 #قیمت_دلار #دلار #سعدی #شعر_فارسی{CHANNEL_SIGNATURE}",
    ]
    return "\n".join(lines)

async def publish_daily_usd_post_if_due(session):
    current_tehran = get_current_tehran_time()
    today = current_tehran.strftime("%Y-%m-%d")
    if not (USD_POST_HOUR <= current_tehran.hour < USD_WINDOW_END_HOUR):
        return
    if get_metadata("last_usd_post_date") == today:
        return
    got = await get_usd_toman(session)
    if not got:
        print("⚠️ قیمت دلار از هیچ منبعی دریافت نشد؛ در چرخه‌ی بعد دوباره تلاش می‌شود.")
        return
    value, sources = got
    verse = await fetch_saadi_verse(session)
    text = build_usd_post(value, sources, verse, current_tehran)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📜 خواندن شعر کامل در گنجور", url=verse["url"])]])
    msg = await send_post(session, text, reply_markup=markup, silent=False)
    set_metadata("last_usd_post_date", today)
    await pin_post(msg.message_id)
    print(f"✅ پست دلار منتشر شد: {value:,} تومان")

# ================= ۱۱. فیلم و موسیقی روزانه (ساعت ۱۲) بر اساس روز جهانی =================
INTERNATIONAL_DAYS = {
    "01-24": ("International Day of Education", "روز جهانی آموزش"),
    "02-11": ("International Day of Women and Girls in Science", "روز جهانی زنان و دختران در علم"),
    "02-13": ("World Radio Day", "روز جهانی رادیو"),
    "02-20": ("World Day of Social Justice", "روز جهانی عدالت اجتماعی"),
    "02-21": ("International Mother Language Day", "روز جهانی زبان مادری"),
    "03-08": ("International Women's Day", "روز جهانی زن"),
    "03-14": ("Pi Day", "روز جهانی عدد پی"),
    "03-20": ("International Day of Happiness", "روز جهانی شادی"),
    "03-21": ("World Poetry Day", "روز جهانی شعر"),
    "03-22": ("World Water Day", "روز جهانی آب"),
    "03-27": ("World Theatre Day", "روز جهانی تئاتر"),
    "04-02": ("World Autism Awareness Day", "روز جهانی آگاهی از اوتیسم"),
    "04-07": ("World Health Day", "روز جهانی بهداشت"),
    "04-12": ("International Day of Human Space Flight", "روز جهانی پرواز فضایی انسان"),
    "04-15": ("World Art Day", "روز جهانی هنر"),
    "04-22": ("Earth Day", "روز جهانی زمین"),
    "04-23": ("World Book and Copyright Day", "روز جهانی کتاب و حق مؤلف"),
    "04-30": ("International Jazz Day", "روز جهانی جاز"),
    "05-01": ("International Workers' Day", "روز جهانی کارگر"),
    "05-03": ("World Press Freedom Day", "روز جهانی آزادی مطبوعات"),
    "05-15": ("International Day of Families", "روز جهانی خانواده"),
    "05-17": ("World Telecommunication and Information Society Day", "روز جهانی ارتباطات و جامعه‌ی اطلاعاتی"),
    "05-18": ("International Museum Day", "روز جهانی موزه"),
    "05-22": ("International Day for Biological Diversity", "روز جهانی تنوع زیستی"),
    "06-05": ("World Environment Day", "روز جهانی محیط زیست"),
    "06-08": ("World Oceans Day", "روز جهانی اقیانوس‌ها"),
    "06-20": ("World Refugee Day", "روز جهانی پناهنده"),
    "06-21": ("World Music Day", "روز جهانی موسیقی"),
    "06-30": ("International Asteroid Day", "روز جهانی سیارک‌ها"),
    "07-11": ("World Population Day", "روز جهانی جمعیت"),
    "07-18": ("Nelson Mandela International Day", "روز جهانی نلسون ماندلا"),
    "07-30": ("International Day of Friendship", "روز جهانی دوستی"),
    "08-09": ("International Day of the World's Indigenous Peoples", "روز جهانی مردمان بومی"),
    "08-12": ("International Youth Day", "روز جهانی جوانان"),
    "08-19": ("World Photography Day", "روز جهانی عکاسی"),
    "09-08": ("International Literacy Day", "روز جهانی سوادآموزی"),
    "09-15": ("International Day of Democracy", "روز جهانی دموکراسی"),
    "09-21": ("International Day of Peace", "روز جهانی صلح"),
    "09-27": ("World Tourism Day", "روز جهانی گردشگری"),
    "09-29": ("World Heart Day", "روز جهانی قلب"),
    "10-01": ("International Music Day", "روز جهانی موسیقی"),
    "10-04": ("World Animal Day", "روز جهانی حیوانات"),
    "10-05": ("World Teachers' Day", "روز جهانی معلم"),
    "10-10": ("World Mental Health Day", "روز جهانی سلامت روان"),
    "10-16": ("World Food Day", "روز جهانی غذا"),
    "10-24": ("United Nations Day", "روز سازمان ملل"),
    "11-10": ("World Science Day for Peace and Development", "روز جهانی علم برای صلح و توسعه"),
    "11-13": ("World Kindness Day", "روز جهانی مهربانی"),
    "11-14": ("World Diabetes Day", "روز جهانی دیابت"),
    "11-16": ("International Day for Tolerance", "روز جهانی مدارا"),
    "11-20": ("World Children's Day", "روز جهانی کودک"),
    "11-21": ("World Television Day", "روز جهانی تلویزیون"),
    "12-01": ("World AIDS Day", "روز جهانی مبارزه با ایدز"),
    "12-03": ("International Day of Persons with Disabilities", "روز جهانی افراد دارای معلولیت"),
    "12-05": ("International Volunteer Day", "روز جهانی داوطلب"),
    "12-10": ("Human Rights Day", "روز جهانی حقوق بشر"),
    "12-11": ("International Mountain Day", "روز جهانی کوهستان"),
    "12-18": ("International Migrants Day", "روز جهانی مهاجران"),
    "12-20": ("International Human Solidarity Day", "روز جهانی همبستگی انسانی"),
}

MUSIC_GENRES = [("rock", "راک"), ("funk", "فانک"), ("soul", "سول"), ("blues", "بلوز"), ("rnb", "آر اند بی"),
                ("jazz", "جز"), ("hiphop", "هیپ‌هاپ"), ("rap", "رپ"), ("pop", "پاپ"), ("electronic", "الکترونیک")]

class MovieRec(BaseModel):
    title_en: str
    title_fa: str = ""
    year: int
    director: str = ""
    genres_persian: str = ""
    imdb_rating: float = Field(description="IMDb rating; MUST be strictly above 7.0")
    plot_hook_persian: str = Field(description="2 sentences, spoiler-free")
    why_today_persian: str = Field(description="1-2 sentences connecting the film to today's occasion")

class MusicRec(BaseModel):
    artist: str
    track: str
    album: str = ""
    year: int = 0
    why_today_persian: str = Field(description="1-2 sentences connecting the track to today's occasion")

class DailyRec(BaseModel):
    occasion_persian: str = ""
    occasion_english: str = ""
    occasion_note_persian: str = Field(default="", description="1-2 factual sentences about the occasion")
    movie: MovieRec
    music: MusicRec

async def omdb_lookup(session, title: str, year: int):
    if not OMDB_API_KEY:
        return None
    try:
        url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={quote_plus(title)}&y={year}&type=movie"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
            data = await resp.json(content_type=None)
        if data.get("Response") != "True":
            return None
        rating = float(data.get("imdbRating", "0"))
        votes = int(to_en_digits(data.get("imdbVotes", "0")).replace(",", "") or 0)
        poster = data.get("Poster") if str(data.get("Poster", "")).startswith("http") else None
        return {"rating": rating, "votes": votes, "id": data.get("imdbID"), "poster": poster}
    except Exception:
        return None

def _recent_load() -> dict:
    try:
        return json.loads(get_metadata("recent_recs", '{"movies": [], "music": []}'))
    except Exception:
        return {"movies": [], "music": []}

async def generate_daily_recommendation(session, dt: datetime):
    recent = _recent_load()
    day_key = dt.strftime("%m-%d")
    occasion = INTERNATIONAL_DAYS.get(day_key)
    genre_key, genre_fa = MUSIC_GENRES[dt.date().toordinal() % len(MUSIC_GENRES)]
    rejected = []
    for _ in range(3):
        occasion_line = (f"Known international day for this date: {occasion[0]} ({occasion[1]})." if occasion else
                         "No pre-verified international day for this date. Name one ONLY if you are certain a widely "
                         "recognised UN/UNESCO-style international day falls on exactly this month-day; otherwise leave "
                         "occasion fields empty and connect picks to the date/season instead. Never invent an occasion.")
        prompt = f"""
You are the culture editor of the Persian Telegram channel @jazebestore. Today is {dt.strftime('%A, %d %B %Y')} (Tehran).
{occasion_line}

Pick ONE feature film and ONE music track that fit today's occasion/theme.
MOVIE rules: a real theatrical/feature film (not a series), IMDb rating strictly above 7.0 (prefer well-known titles whose
rating you are sure about, 7.5+ is safer), at least 20,000 IMDb votes, any country/era. Never invent titles.
MUSIC rules: a real, existing track by a real artist, genre: {genre_key}. Never invent songs/albums.
Do NOT pick these (already used or rejected): {json.dumps(recent['movies'][-60:] + recent['music'][-60:] + rejected, ensure_ascii=False)}.
WRITING rules: all *_persian fields in fluent, natural, standard Persian (not word-for-word translation), correct
half-spaces (نیم‌فاصله), Persian punctuation (، ؛ ؟ «»), keep film/artist/track names in English. No spoilers.
"""
        rec = await ask_ai_json(prompt, DailyRec, temperature=0.6)
        if not rec:
            continue
        m = rec.movie
        key = m.title_en.strip().lower()
        if key in [x.lower() for x in recent["movies"]] or f"{rec.music.artist} - {rec.music.track}".lower() in \
                [x.lower() for x in recent["music"]]:
            rejected += [m.title_en, f"{rec.music.artist} - {rec.music.track}"]
            continue
        info = await omdb_lookup(session, m.title_en, m.year)
        if OMDB_API_KEY:
            if not info or info["rating"] <= 7.0 or info["votes"] < 20000:
                rejected.append(m.title_en)
                continue
            m.imdb_rating = info["rating"]
        elif m.imdb_rating <= 7.0:
            rejected.append(m.title_en)
            continue
        return rec, info, genre_key, genre_fa, occasion
    return None

def build_daily_rec_post(rec: DailyRec, info, genre_fa: str, occasion, dt: datetime) -> str:
    d = format_dates(dt)
    occ_fa = rec.occasion_persian or (occasion[1] if occasion else "")
    m, mu = rec.movie, rec.music
    e = html.escape
    lines = [f"🌍 <b>{e(persian_polish(occ_fa))}</b>" if occ_fa else "🗓 <b>پیشنهاد فرهنگی امروز</b>",
             f"📅 <b>{d['weekday']}</b>، {d['jalali']} | {d['gregorian']}"]
    if rec.occasion_note_persian:
        lines.append(f"<blockquote>{e(persian_polish(rec.occasion_note_persian))}</blockquote>")
    title_line = f"{e(m.title_fa)} ({e(m.title_en)}، {m.year})" if m.title_fa else f"{e(m.title_en)} ({m.year})"
    rating_note = (f"⭐ نمره IMDb: <b>{m.imdb_rating}/10</b> (تأییدشده)" if info
                   else f"⭐ نمره IMDb: حدود <b>{m.imdb_rating}/10</b> (پیش از تماشا بررسی کنید)")
    lines += ["", "🎬 <b>فیلم پیشنهادی امروز</b>", f"<b>{title_line}</b>"]
    if m.director or m.genres_persian:
        lines.append(f"🎞 کارگردان: {e(m.director)} | ژانر: {e(persian_polish(m.genres_persian))}")
    lines += [rating_note, e(persian_polish(m.plot_hook_persian)),
              f"💡 <b>چرا امروز؟</b> {e(persian_polish(m.why_today_persian))}",
              "", f"🎧 <b>موسیقی پیشنهادی امروز | سبک {genre_fa}</b>",
              f"<b>{e(mu.artist)} — «{e(mu.track)}»</b>"]
    if mu.album:
        lines.append(f"💿 آلبوم: {e(mu.album)}" + (f" ({mu.year})" if mu.year else ""))
    lines += [e(persian_polish(mu.why_today_persian)),
              f"\n🏷 #پیشنهاد_روز #فیلم #موسیقی #{genre_fa.replace(' ', '_')}{CHANNEL_SIGNATURE}"]
    return "\n".join(lines)

async def publish_daily_recommendation_if_due(session):
    current_tehran = get_current_tehran_time()
    today = current_tehran.strftime("%Y-%m-%d")
    if not (DAILY_REC_HOUR <= current_tehran.hour < DAILY_REC_WINDOW_END_HOUR):
        return
    if get_metadata("last_daily_rec_date") == today:
        return
    result = await generate_daily_recommendation(session, current_tehran)
    if not result:
        print("⚠️ تولید پیشنهاد روزانه ناموفق بود؛ چرخه‌ی بعد دوباره تلاش می‌شود.")
        return
    rec, info, genre_key, genre_fa, occasion = result
    text = build_daily_rec_post(rec, info, genre_fa, occasion, current_tehran)
    m, mu = rec.movie, rec.music
    imdb_url = f"https://www.imdb.com/title/{info['id']}/" if info and info.get("id") else \
        f"https://www.imdb.com/find/?q={quote_plus(m.title_en + ' ' + str(m.year))}"
    music_q = quote_plus(f"{mu.artist} {mu.track}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 صفحه‌ی فیلم در IMDb", url=imdb_url)],
        [InlineKeyboardButton("▶️ شنیدن موسیقی در YouTube", url=f"https://www.youtube.com/results?search_query={music_q}")],
        [InlineKeyboardButton("🎧 جستجو در Spotify", url=f"https://open.spotify.com/search/{music_q}")],
    ])
    msg = await send_post(session, text, image_url=(info or {}).get("poster"), reply_markup=markup,
                          filename="daily_rec.jpg")
    set_metadata("last_daily_rec_date", today)
    recent = _recent_load()
    recent["movies"] = (recent["movies"] + [m.title_en])[-150:]
    recent["music"] = (recent["music"] + [f"{mu.artist} - {mu.track}"])[-150:]
    set_metadata("recent_recs", json.dumps(recent, ensure_ascii=False))
    await pin_post(msg.message_id)
    print(f"✅ پیشنهاد روزانه منتشر شد: {m.title_en} | {mu.artist} - {mu.track}")

async def run_daily_jobs(session):
    for job in (unpin_expired_pins, publish_daily_usd_post_if_due, publish_daily_recommendation_if_due):
        try:
            await job(session)
        except Exception as e:
            print(f"⚠️ خطا در کار روزانه {job.__name__}: {e}")

# ================= ۱۲. تکمیل خبر با متن کامل مقاله + ویدیو + میم کاربران =================
_NOISE = re.compile(r"cookie|subscribe|newsletter|sign up|all rights reserved|advertisement", re.I)

def _youtube_watch_url(url: str) -> str:
    m = re.search(r"youtube\.com/embed/([\w-]{6,})", url)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else url

async def fetch_article_details(session, url: str):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
            if resp.status != 200 or "html" not in resp.headers.get("Content-Type", "").lower():
                return "", ""
            page = await resp.text(errors="ignore")
        soup = BeautifulSoup(page, "html.parser")
        video = ""
        for prop in ("og:video:url", "og:video", "og:video:secure_url"):
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content", "").startswith("http"):
                video = tag["content"]
                break
        if not video:
            frame = soup.find("iframe", src=re.compile(r"youtube\.com/embed|youtu\.be|player\.vimeo"))
            if frame:
                video = frame.get("src", "")
                if video.startswith("//"):
                    video = "https:" + video
        for tag in soup(["script", "style", "nav", "aside", "footer", "form", "header", "noscript"]):
            tag.decompose()
        container = soup.find("article") or soup.find("main") or soup
        paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
        paras = [p for p in paras if len(p) > 50 and not _NOISE.search(p)]
        body = " ".join(paras)[:ARTICLE_MAX_CHARS * 2]
        return body, _youtube_watch_url(video) if video else ""
    except Exception:
        return "", ""

def pick_video_url(orig_item: dict) -> str:
    if orig_item.get("video_url"):
        return orig_item["video_url"]
    link = orig_item.get("link", "") or ""
    if re.search(r"youtube\.com/watch|youtu\.be/|twitch\.tv|vimeo\.com", link):
        return link
    return ""

async def enrich_selected_items(session, selected_items, batch_map):
    try:
        sem = asyncio.Semaphore(5)

        async def one(sel):
            orig = batch_map.get(sel.selected_id)
            if not orig:
                return sel.selected_id, "", ""
            async with sem:
                body, video = await fetch_article_details(session, orig["link"])
            return sel.selected_id, body, video

        fetched = await asyncio.gather(*(one(s) for s in selected_items), return_exceptions=True)
        details = {}
        for r in fetched:
            if isinstance(r, tuple):
                details[r[0]] = (r[1], r[2])
                orig = batch_map.get(r[0])
                if orig is not None and r[2] and not orig.get("video_url"):
                    orig["video_url"] = r[2]

        work = [(s, details[s.selected_id][0]) for s in selected_items
                if len(details.get(s.selected_id, ("", ""))[0]) >= 400]
        for i in range(0, len(work), ENRICH_CHUNK):
            chunk = work[i:i + ENRICH_CHUNK]
            payload = [{
                "selected_id": s.selected_id,
                "category_id": s.category_id,
                "verification_status": s.verification_status,
                "current_headline_persian": s.headline_persian,
                "rss_text": batch_map[s.selected_id]["text"],
                "full_article_excerpt": body[:ARTICLE_MAX_CHARS],
            } for s, body in chunk]
            prompt = f"""
You are the Chief Editor of '@jazebestore'. For each item below, rewrite the Persian news copy to be COMPLETE and PRECISE
using ONLY facts present in `rss_text` and `full_article_excerpt` (never invent facts, quotes, prices or dates).
Rules:
- Avoid generalities: include every concrete name, number, date, price, platform, version, and who-said-what.
- summary_persian: 4-6 short sentences; wrap 1-4 key facts in <b>...</b>. key_points_persian: 3-5 factual bullets.
- background_persian: 1-2 sentences of context that helps the reader (only if supported by the text), else "".
- Write natural, standard Persian (not word-for-word translation): correct half-spaces (نیم‌فاصله), Persian punctuation
  (، ؛ ؟ «»), established Persian terms where common, proper nouns/game/product names kept in English.
- Return one object per input item, same selected_id, and keep every other field consistent with the input item
  (category_id, verification_status, confidence_score, is_breaking, series_name, hashtags, topic_fingerprint, related_game, hype_score).
Items:
{json.dumps(payload, ensure_ascii=False)}
"""
            result = await generate_news_with_fallback(prompt)
            if not result:
                continue
            by_id = {e.selected_id: e for e in result.selected_news}
            for s, _ in chunk:
                e = by_id.get(s.selected_id)
                if not e or len((e.summary_persian or "").strip()) < 60:
                    continue
                for field in ("headline_persian", "summary_persian", "background_persian",
                              "image_alt_persian", "av_transcript_summary_persian"):
                    val = getattr(e, field, "")
                    if val and val.strip():
                        setattr(s, field, val)
                if e.key_points_persian and len(e.key_points_persian) >= 2:
                    s.key_points_persian = e.key_points_persian
    except Exception as err:
        print(f"⚠️ مرحله‌ی تکمیل خبر نادیده گرفته شد: {err}")
    return selected_items

async def send_video_reply(video_url: str, reply_to: int, silent: bool = False):
    try:
        await bot.send_message(
            chat_id=TARGET_CHANNEL, parse_mode="HTML", disable_notification=silent,
            text=f"🎬 <b>ویدیوی مرتبط با این خبر</b>\n{html.escape(video_url)}",
            disable_web_page_preview=False, **_reply_kwargs(reply_to))
    except Exception as e:
        print(f"⚠️ ارسال ویدیو ناموفق: {e}")

def remember_news_message(item_id: int, message_id: int):
    set_metadata(f"news_msg_{item_id}", str(message_id))

class MemePick(BaseModel):
    chosen_index: int = Field(description="Index of the best candidate that is genuinely a joke about this topic, or -1")
    joke_persian: str = Field(default="", description="Natural Persian rendition of the joke's meaning, max 220 chars")
    context_persian: str = Field(default="", description="One short Persian sentence explaining the joke if needed")
    is_safe_and_funny: bool = False

def _meme_seen() -> list:
    try:
        return json.loads(get_metadata("meme_seen", "[]"))
    except Exception:
        return []

async def _reddit_candidates(session, query: str) -> list:
    seen = set(_meme_seen())
    out = []
    for period in ("day", "week"):
        url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=top&t={period}&limit=25"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), headers=REDDIT_UA) as resp:
                if resp.status != 200:
                    continue
                xml = await resp.text()
        except Exception:
            continue
        feed = await asyncio.to_thread(feedparser.parse, xml)
        for e in feed.entries:
            tags = getattr(e, "tags", []) or []
            sub = str(tags[0].get("term", "")).lower() if tags else ""
            link = getattr(e, "link", "")
            if sub not in MEME_SUBREDDITS or not link or link in seen:
                continue
            body = e.content[0].value if getattr(e, "content", None) else ""
            m = re.search(r'https://(?:i|preview)\.redd\.it/[^"\']+?\.(?:jpe?g|png|webp)[^"\']*', body)
            img = html.unescape(m.group(0)) if m else None
            if not img and getattr(e, "media_thumbnail", None):
                img = e.media_thumbnail[0].get("url")
            out.append({"index": len(out), "subreddit": sub, "title": (e.title or "")[:200], "link": link, "image": img})
            if len(out) >= 5:
                return out
        if out:
            break
    return out

async def _try_meme(session, query: str, topic_en: str, reply_to=None) -> bool:
    try:
        cands = await _reddit_candidates(session, query)
        if not cands:
            return False
        prompt = f"""
Topic of our news post: {topic_en}
Candidate Reddit posts (real user posts; titles only):
{json.dumps([{k: c[k] for k in ('index', 'subreddit', 'title')} for c in cands], ensure_ascii=False)}
Choose the ONE candidate whose title is a genuine, funny community joke/meme directly about this topic (chosen_index = -1 if none).
Render the joke's meaning in natural, witty, standard Persian (not word-for-word), correct half-spaces. Do not add facts that
are not in the title. Reject anything insulting, sexual, hateful, religious or political (is_safe_and_funny=false).
"""
        pick = await ask_ai_json(prompt, MemePick, temperature=0.5)
        if pick is None or pick.chosen_index < 0 or pick.chosen_index >= len(cands) or \
                not pick.is_safe_and_funny or len(pick.joke_persian.strip()) < 8:
            return False
        c = cands[pick.chosen_index]
        e = html.escape
        lines = ["😄 <b>شوخی کاربران فضای مجازی</b>",
                 f"<blockquote>{e(persian_polish(pick.joke_persian))}</blockquote>"]
        if pick.context_persian.strip():
            lines.append(f"💬 {e(persian_polish(pick.context_persian))}")
        lines.append(f"📎 برگرفته از پست کاربران Reddit (r/{e(c['subreddit'])}): «{e(c['title'][:120])}»")
        lines.append(f"\n🏷 #شوخی_کاربران #میم #فان{CHANNEL_SIGNATURE}")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 دیدن پست اصلی در Reddit", url=c["link"])]])
        await send_post(session, "\n".join(lines), image_url=c["image"], reply_markup=markup,
                        reply_to=reply_to, filename=f"meme_{c['index']}.jpg")
        seen = (_meme_seen() + [c["link"]])[-300:]
        set_metadata("meme_seen", json.dumps(seen))
        set_metadata("last_meme_ts", str(get_current_tehran_time().timestamp()))
        return True
    except Exception as err:
        print(f"⚠️ ارسال شوخی ناموفق: {err}")
        return False

def _meme_query_for(sel) -> str:
    if getattr(sel, "related_game", ""):
        return sel.related_game
    names = re.findall(r"[A-Z][\w:+-]+", getattr(sel, "topic_fingerprint", "") or "")
    return " ".join(names[:4])

async def post_meme_reply_for_news(session, sel, news_msg_id: int) -> bool:
    query = _meme_query_for(sel)
    if not query:
        return False
    return await _try_meme(session, query, sel.topic_fingerprint or query, reply_to=news_msg_id)

async def publish_trending_meme(session):
    try:
        current_tehran = get_current_tehran_time()
        last = float(get_metadata("last_meme_ts", "0") or 0)
        if current_tehran.timestamp() - last < MEME_STANDALONE_GAP_MIN * 60:
            return
        if 0 <= current_tehran.hour < 8:
            return
        for tr in detect_24h_trends(top_n=3):
            entity = tr["entity"]
            reply_to = None
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""SELECT id FROM news_items WHERE status='published' AND lower(related_entity)=?
                         AND published_at >= datetime('now','-24 hours') ORDER BY id DESC LIMIT 1""", (entity,))
            row = c.fetchone()
            conn.close()
            if row:
                mid = get_metadata(f"news_msg_{row[0]}", "")
                reply_to = int(mid) if mid.isdigit() else None
            if await _try_meme(session, entity, entity, reply_to=reply_to):
                return
    except Exception as err:
        print(f"⚠️ خطا در شوخی مستقل: {err}")

# ================= ۱۳. جمع‌آوری هم‌زمان فیدهای RSS =================
async def fetch_single_feed(session: aiohttp.ClientSession, sem: asyncio.Semaphore, category: str, url: str) -> list[dict]:
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers={'User-Agent': 'Mozilla/5.0'}) as resp:
                if resp.status != 200:
                    return []
                xml_data = await resp.text()

            feed = await asyncio.to_thread(feedparser.parse, xml_data)
            extracted = []
            for entry in feed.entries[:2]:
                link = getattr(entry, 'link', None)
                if not link:
                    continue

                title = clean_raw_text(getattr(entry, 'title', ''))
                summary = clean_raw_text(getattr(entry, 'summary', ''))
                cleaned_body = f"{title}\n{summary}".strip()

                if len(cleaned_body) < 45:
                    continue

                img_url, has_av = extract_rss_media_info(entry)
                low_body = cleaned_body.lower()
                is_breaking = any(kw in low_body for kw in BREAKING_TRIGGER_KEYWORDS)

                extracted.append({
                    'category': category,
                    'source': url,
                    'link': link,
                    'raw_title': title[:250],
                    'raw_text': cleaned_body[:320],
                    'image_url': img_url,
                    'has_video_or_audio': 1 if has_av else 0,
                    'is_breaking_candidate': 1 if is_breaking else 0
                })
            return extracted
        except Exception:
            return []

async def fetch_rss_sources(session: aiohttp.ClientSession):
    sem = asyncio.Semaphore(18)
    tasks = [
        fetch_single_feed(session, sem, category, url)
        for category, urls in CATEGORIZED_RSS_SOURCES.items()
        for url in urls
    ]
    results = await asyncio.gather(*tasks)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_count = 0
    for feed_items in results:
        for item in feed_items:
            c.execute("SELECT 1 FROM news_items WHERE url = ?", (item['link'],))
            if c.fetchone() is None:
                c.execute("""
                    INSERT INTO news_items
                    (url, category, source, raw_title, raw_text, image_url, has_video_or_audio, status, is_breaking_candidate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', ?)
                """, (
                    item['link'],
                    item['category'],
                    item['source'],
                    item['raw_title'],
                    item['raw_text'],
                    item['image_url'],
                    item['has_video_or_audio'],
                    item['is_breaking_candidate']
                ))
                new_count += 1
    conn.commit()
    conn.close()

    if new_count > 0:
        await run_semantic_clustering_and_deduplication()

# ================= ۱۴. قالب غنی و دسترس‌پذیر خبر و انتشار =================
_CAT_EMOJI = {"gaming": "🎮", "technology": "💻", "hardware": "⚡", "crypto": "🪙", "film_tv": "🍿",
              "internet_culture": "🌐", "fun_meme": "😄", "music": "🎵", "general_news": "📰"}
_VER_ICON = {"خبر رسمی": "✅", "گزارش رسانه معتبر": "📰", "شایعه و لیک": "🕵️", "خبر تأییدنشده": "⚠️"}

def format_rich_news_post(sel: SelectedNewsItem, orig_item: dict, main_cat_hashtag: str) -> str:
    lines = []
    if sel.is_breaking:
        lines.append("🚨 <b>خبر فوری | پوشش ویژه</b>")
    if sel.series_name and sel.series_name in SERIALIZED_SERIES_HEADERS:
        lines.append(f"<b>{SERIALIZED_SERIES_HEADERS[sel.series_name]}</b>")
    lines.append(f"{_CAT_EMOJI.get(sel.category_id, '📰')} <b>{sanitize_telegram_html(sel.headline_persian)}</b>")

    cat_fa = CATEGORY_PERSIAN_NAMES.get(sel.category_id, "اخبار")
    valid = list(_VER_ICON)
    ver = sel.verification_status if sel.verification_status in valid else "گزارش رسانه معتبر"
    conf = max(40, min(100, int(sel.confidence_score or 85)))
    src = max(1, int(orig_item.get("source_count", 1)))
    lines.append(f"🗂 دسته‌بندی: {cat_fa} | {_VER_ICON[ver]} وضعیت: <b>{ver}</b>")
    lines.append(f"📊 درجه اطمینان: {to_fa_digits(conf)}٪ | 🔗 تعداد منابع: {to_fa_digits(src)} منبع")
    lines.append("")
    summary = re.sub(r"\s*\n\s*", " ", sel.summary_persian or "")
    lines.append(f"<blockquote>{sanitize_telegram_html(summary)}</blockquote>")

    background = getattr(sel, "background_persian", "") or ""
    if background.strip():
        lines.append("")
        background = re.sub(r"\s*\n\s*", " ", background)
        lines.append(f"📌 <b>پیش‌زمینه:</b> {sanitize_telegram_html(background)}")

    if sel.key_points_persian:
        lines.append("")
        lines.append("<b>مهم‌ترین نکات:</b>")
        for pt in sel.key_points_persian[:5]:
            clean = sanitize_telegram_html(pt.lstrip("•-*▫️🔹 "))
            if clean:
                lines.append(f"🔹 {clean}")

    if orig_item.get("has_video_or_audio") or (sel.av_transcript_summary_persian or "").strip():
        av = sanitize_telegram_html((sel.av_transcript_summary_persian or "").strip() or
                                    "تمامی اطلاعات کلیدی این ویدئو/فایل صوتی به صورت متنی در نکات بالا درج شده است.")
        lines.append("")
        lines.append(f"📝 <b>متن و خلاصه محتوای ویدئویی/صوتی (ویژه ناشنوایان):</b> {av}")

    if orig_item.get("image_url"):
        alt = sanitize_telegram_html((sel.image_alt_persian or "").strip() or f"تصویر مرتبط با خبر «{sel.headline_persian}»")
        lines.append("")
        lines.append(f"🖼 <b>توضیح تصویر:</b> {alt}")

    extra = []
    for tag in sel.topic_hashtags:
        clean_tag = re.sub(r"[^\w#]", "_", tag.strip())
        if not clean_tag.startswith("#"):
            clean_tag = "#" + clean_tag
        if clean_tag != main_cat_hashtag and len(clean_tag) > 2:
            extra.append(clean_tag)
    lines.append(f"\n🏷 {' '.join([main_cat_hashtag] + extra[:3])}{CHANNEL_SIGNATURE}")
    return "\n".join(lines)

async def process_and_publish_batch(
    session: aiohttp.ClientSession,
    breaking_only: bool = False,
    max_items: int = MAX_NEWS_PER_CYCLE
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if breaking_only:
        c.execute("""
            SELECT id, url, category, source, raw_title, raw_text, image_url, has_video_or_audio, source_count, is_breaking_candidate
            FROM news_items
            WHERE status IN ('pending', 'failed') AND retry_count < 3 AND is_breaking_candidate = 1
            ORDER BY source_count DESC, id DESC LIMIT 20
        """)
    else:
        c.execute("""
            SELECT id, url, category, source, raw_title, raw_text, image_url, has_video_or_audio, source_count, is_breaking_candidate
            FROM news_items
            WHERE status IN ('pending', 'failed') AND retry_count < 3
            ORDER BY is_breaking_candidate DESC, source_count DESC, id DESC LIMIT ?
        """, (MAX_CANDIDATES_FOR_AI,))

    rows = c.fetchall()
    if not rows:
        conn.close()
        return

    c.execute("""
        SELECT topic_fingerprint
        FROM news_items
        WHERE status = 'published' AND topic_fingerprint IS NOT NULL
        ORDER BY published_at DESC LIMIT 45
    """)
    recent_topics = [r[0] for r in c.fetchall() if r[0]]
    conn.close()

    current_batch = [
        {
            'id': r[0],
            'link': r[1],
            'category': r[2],
            'source': r[3],
            'title': r[4],
            'text': r[5][:320],
            'image_url': r[6],
            'has_video_or_audio': bool(r[7]),
            'source_count': r[8],
            'is_breaking_candidate': bool(r[9])
        }
        for r in rows
    ]

    trends_24h = detect_24h_trends(top_n=5)
    candidates_for_ai = [
        {
            "id": item['id'],
            "cat": item['category'],
            "src_cnt": item['source_count'],
            "brk": item['is_breaking_candidate'],
            "img": bool(item['image_url']),
            "av": item['has_video_or_audio'],
            "text": item['text']
        }
        for item in current_batch
    ]

    mode_label = "BREAKING NEWS" if breaking_only else "30-MIN CYCLE"
    prompt = f"""
    Chief Editor for '@jazebestore' (Persian Gaming, Tech, Hardware, Crypto, Entertainment channel). Year: 2026. Mode: {mode_label}.
    24h Trends: {json.dumps(trends_24h, ensure_ascii=False)}
    Already published (DO NOT repeat): {json.dumps(recent_topics, ensure_ascii=False)}
    Candidates: {json.dumps(candidates_for_ai, ensure_ascii=False)}

    Rules:
    1. Select AT MOST {max_items} unique, high-value stories (skip purely visual items with no text). Include `fun_meme` if funny candidates exist.
    2. `verification_status`: one of ["خبر رسمی", "گزارش رسانه معتبر", "شایعه و لیک", "خبر تأییدنشده"]. Set `confidence_score` (40-100).
    3. `series_name`: optional from ["Game of the Week", "Movie of the Week", "Tech Breakdown", "Weekly Gaming News", "Best Hardware Deals", "This Week in Gaming"], else "".
    4. Accessible Persian (WCAG):
       - `headline_persian`: clear Persian headline (no emojis/HTML).
       - `summary_persian`: 4-6 short factual sentences in fluent Persian with proper half-spaces (نیم‌فاصله) & punctuation (، ؛ ؟ «»), keeping English proper nouns; wrap 1-4 key facts in <b>...</b>.
       - `key_points_persian`: 3-5 factual Persian bullets; `background_persian`: 1-2 context sentences if supported, else "".
       - `image_alt_persian`: if `img` is true, 1-sentence Persian visual description for blind users.
       - `av_transcript_summary_persian`: if `av` is true, concise Persian text summary of video/audio for deaf users.
    5. `related_game`: canonical English title (e.g. "GTA VI", "PlayStation Plus", "PS5 Pro"), else "". Prefer `av`=true when newsworthy.
    """

    validated_result = await generate_news_with_fallback(prompt)

    if not validated_result:
        print("❌ تمامی سرویس‌های AI در این نوبت با خطا مواجه شدند. وضعیت خبرها روی pending باقی ماند تا از دست نروند.")
        return

    selected_items = validated_result.selected_news[:max_items]
    batch_map = {item['id']: item for item in current_batch}
    selected_ids = {sel.selected_id for sel in selected_items if sel.selected_id in batch_map}
    non_selected_ids = [item['id'] for item in current_batch if item['id'] not in selected_ids]

    if selected_ids:
        update_news_status(list(selected_ids), 'selected')
    if not breaking_only and non_selected_ids:
        update_news_status(non_selected_ids, 'rejected')

    selected_items = await enrich_selected_items(session, selected_items, batch_map)

    tehran_hour = get_current_tehran_time().hour
    silent_mode = (0 <= tehran_hour < 8) and not breaking_only
    memes_posted = 0

    for sel in selected_items:
        orig_item = batch_map.get(sel.selected_id)
        if not orig_item:
            continue

        polish_selected(sel)
        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
        main_cat_hashtag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")
        final_caption = format_rich_news_post(sel, orig_item, main_cat_hashtag)

        news_link = orig_item.get('link', STORE_BASE_URL)
        video_url = pick_video_url(orig_item)
        keyboard = [
            [InlineKeyboardButton("❤️ پسندیدن این خبر (0)", callback_data=f"like_{orig_item['id']}")],
            [InlineKeyboardButton("🔗 مطالعه گزارش کامل در منبع اصلی", url=news_link)]
        ]
        if video_url:
            keyboard.append([InlineKeyboardButton("▶️ تماشای ویدیوی خبر", url=video_url)])

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            news_msg = await send_post(
                session, final_caption, image_url=orig_item.get('image_url'),
                reply_markup=reply_markup, silent=silent_mode, filename=f"img_{orig_item['id']}.jpg"
            )
            save_published_news_details(
                item_id=orig_item['id'],
                fingerprint=sel.topic_fingerprint,
                pub_cat=cat_id,
                pub_headline=sel.headline_persian,
                related_entity=sel.related_game,
                ai_payload=sel.model_dump()
            )
            remember_news_message(orig_item['id'], news_msg.message_id)
            if sel.related_game:
                record_hype_event(sel.related_game, cat_id, float(sel.hype_score))

            if video_url:
                await send_video_reply(video_url, news_msg.message_id, silent_mode)
            if (not silent_mode and memes_posted < MEME_MAX_PER_CYCLE
                    and (sel.hype_score >= MEME_MIN_HYPE or cat_id == "fun_meme")):
                if await post_meme_reply_for_news(session, sel, news_msg.message_id):
                    memes_posted += 1

            await asyncio.sleep(4)

        except Exception as send_err:
            print(f"⚠️ خطا در ارسال خبر #{orig_item['id']} به تلگرام: {send_err}")
            update_news_status([orig_item['id']], 'failed', increment_retry=True)

# ================= ۱۵. گزارش خلاصه روزانه (Daily Digest ساعت ۰۰:۰۰ به وقت تهران) =================
async def publish_daily_digest_if_due():
    current_tehran = get_current_tehran_time()
    today_str = current_tehran.strftime("%Y-%m-%d")

    if current_tehran.hour != 0 or current_tehran.minute > 20:
        return
    if get_metadata("last_daily_digest_date") == today_str:
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT published_category, published_headline, url
        FROM news_items
        WHERE status = 'published'
          AND published_at >= datetime('now', '-24 hours')
          AND published_headline IS NOT NULL
        ORDER BY id DESC
    """)
    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return

    by_cat = {"gaming": [], "technology": [], "hardware": [], "ent": []}
    for cat, headline, url in rows:
        clean_h = sanitize_telegram_html(headline)
        entry_line = f"• <a href=\"{html.escape(url)}\">{clean_h}</a>"
        if cat == "gaming" and len(by_cat["gaming"]) < 5:
            by_cat["gaming"].append(entry_line)
        elif cat == "technology" and len(by_cat["technology"]) < 3:
            by_cat["technology"].append(entry_line)
        elif cat == "hardware" and len(by_cat["hardware"]) < 3:
            by_cat["hardware"].append(entry_line)
        elif cat in ("film_tv", "music") and len(by_cat["ent"]) < 3:
            by_cat["ent"].append(entry_line)

    trends_24h = detect_24h_trends(top_n=4)
    trend_names = [t["entity"].upper() for t in trends_24h] if trends_24h else ["GTA VI", "PlayStation 5", "AI"]

    digest_lines = [
        f"📅 <b>گزارش جامع روزانه (Daily Digest) | جمع‌بندی ۲۴ ساعت گذشته</b>",
        f"تاریخ: {today_str} | ساعت ۰۰:۰۰ به وقت تهران",
        ""
    ]

    if by_cat["gaming"]:
        digest_lines.append("🎮 <b>۵ خبر مهم گیمینگ:</b>")
        digest_lines.extend(by_cat["gaming"])
        digest_lines.append("")

    if by_cat["technology"]:
        digest_lines.append("💻 <b>۳ خبر مهم تکنولوژی:</b>")
        digest_lines.extend(by_cat["technology"])
        digest_lines.append("")

    if by_cat["hardware"]:
        digest_lines.append("⚡ <b>مهم‌ترین اخبار سخت‌افزار:</b>")
        digest_lines.extend(by_cat["hardware"])
        digest_lines.append("")

    if by_cat["ent"]:
        digest_lines.append("🍿 <b>اتفاقات مهم سینما و موسیقی:</b>")
        digest_lines.extend(by_cat["ent"])
        digest_lines.append("")

    digest_lines.append("🚀 <b>داغ‌ترین ترندهای امروز و محورهای خبری فردا:</b>")
    digest_lines.append(f"• بیشترین رشد خبری ۲۴ ساعت اخیر: <b>{' | '.join(trend_names)}</b>")
    digest_lines.append("• فردا در جاذبه استور: پوشش ادامه رویدادهای مرتبط با این عناوین و مهم‌ترین تحولات دنیای گیمینگ و تکنولوژی.")
    digest_lines.append(f"\n🏷 #خلاصه_روزانه #Daily_Digest #گیمینگ #تکنولوژی{CHANNEL_SIGNATURE}")

    try:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text="\n".join(digest_lines),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        set_metadata("last_daily_digest_date", today_str)
        print(f"✅ گزارش Daily Digest برای تاریخ {today_str} منتشر شد.")
    except Exception as e:
        print(f"⚠️ خطا در ارسال Daily Digest: {e}")

# ================= ۱۶. مدیریت دکمه لایک پست‌ها =================
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer("رای شما ثبت شد ❤️")

    data = query.data or ""
    if data.startswith("like_"):
        try:
            existing_rows = [list(r) for r in query.message.reply_markup.inline_keyboard]
            first_btn_text = existing_rows[0][0].text
            match = re.search(r'\((\d+)\)', first_btn_text)
            count = (int(match.group(1)) + 1) if match else 1
        except Exception:
            count = 1
            existing_rows = [list(r) for r in query.message.reply_markup.inline_keyboard]

        existing_rows[0][0] = InlineKeyboardButton(f"❤️ پسندیدن این خبر ({count})", callback_data=data)
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(existing_rows))
        except Exception as e:
            print(f"Error updating like button UI: {e}")

# ================= ۱۷. حلقه اصلی ۲۴ ساعته =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید (نسخه قبلی در حال بسته شدن است)...")
    else:
        print(f"Telegram network/update warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    print("🚀 24/7 Accessible News, Breaking Queue, Daily USD/Recs & Trend Bot is running...")

    await asyncio.sleep(15)

    last_regular_cycle_ts = 0.0

    while True:
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            tehran_now = get_current_tehran_time()

            connector = aiohttp.TCPConnector(limit=25, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as shared_session:
                await publish_daily_digest_if_due()
                await run_daily_jobs(shared_session)
                await fetch_rss_sources(shared_session)

                if (now_ts - last_regular_cycle_ts) >= REGULAR_CYCLE_SECONDS:
                    print(f"\n--- [چرخه ۳۰ دقیقه‌ای | {tehran_now.strftime('%Y-%m-%d %H:%M')} تهران] ---")
                    await process_and_publish_batch(
                        session=shared_session,
                        breaking_only=False,
                        max_items=MAX_NEWS_PER_CYCLE
                    )
                    await publish_trending_meme(shared_session)
                    last_regular_cycle_ts = now_ts
                else:
                    await process_and_publish_batch(
                        session=shared_session,
                        breaking_only=True,
                        max_items=MAX_BREAKING_PER_CYCLE
                    )

        except Exception as e:
            print(f"Error in 24/7 background loop: {e}")

        await asyncio.sleep(BREAKING_CHECK_INTERVAL_SECONDS)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(button_click_handler))
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started (24/7 Unified Mode)...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
