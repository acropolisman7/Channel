import asyncio
import sqlite3
import re
import os
import json
import math
import html
import random
import aiohttp
import feedparser
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

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

TARGET_CHANNEL = '@jazebestore'
STORE_BASE_URL = 'https://jazebestore.com'
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
DB_PATH = 'rss_news_history.db'

# تنظیمات زمانی: بررسی اخبار فوری هر ۳ دقیقه | چرخه کامل هر ۳۰ دقیقه | ۱۵ خبر در هر چرخه
BREAKING_CHECK_INTERVAL_SECONDS = 180
REGULAR_CYCLE_SECONDS = 1800
MAX_NEWS_PER_CYCLE = 15
MAX_BREAKING_PER_CYCLE = 3
MAX_CANDIDATES_FOR_AI = 80
PRODUCTS_PER_CYCLE = 3
SEMANTIC_SIMILARITY_THRESHOLD = 0.78
CLUSTER_SIMILARITY_THRESHOLD = 0.72
HYPE_HALF_LIFE_HOURS = 18.0

GEMINI_MODELS = ['gemini-3.8-flash', 'gemini-3.5-flash-lite']
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

# نگاشت نام‌های مستعار (Alias Mapping) برای تطبیق دقیق اخبار با محصولات دیجیتالی سایت
PRODUCT_ALIAS_MAP = {
    "playstation plus": {
        "triggers": ["playstation plus", "ps plus", "ps+", "پلی استیشن پلاس", "پلی‌استیشن پلاس", "پلاس", "plus essential", "plus extra", "plus premium"],
        "product_keywords": ["پلاس", "playstation plus", "ps plus", "اشتراک پلاس"],
        "button_label": "💎 مشاهده و خرید اشتراک PlayStation Plus"
    },
    "gta vi": {
        "triggers": ["gta vi", "gta 6", "grand theft auto vi", "grand theft auto 6", "جی تی ای ۶", "جی تی ای vi"],
        "product_keywords": ["gta vi", "gta 6", "grand theft auto vi", "جی تی ای 6", "جی تی ای ۶", "gta v", "grand theft auto"],
        "button_label": "🎮 مشاهده و خرید بازی GTA در فروشگاه"
    },
    "ps5 pro": {
        "triggers": ["ps5 pro", "playstation 5 pro", "پلی استیشن ۵ پرو", "پلی‌استیشن ۵ پرو", "ps5", "playstation 5"],
        "product_keywords": ["ps5", "پلی استیشن 5", "پلی استیشن ۵", "پلاس", "playstation plus", "اکانت", "ظرفیت"],
        "button_label": "🎮 مشاهده بازی‌ها و اشتراک‌های سازگار با PlayStation 5"
    },
    "ea sports fc": {
        "triggers": ["fc 27", "ea sports fc 27", "fc 26", "ea sports fc 26", "fc 25", "fifa 27", "اف سی ۲۷", "اف سی ۲۶", "اف سی 27", "اف سی 26"],
        "product_keywords": ["fc 27", "fc 26", "fc 25", "ea sports fc", "اف سی", "فیفا"],
        "button_label": "⚽ مشاهده و خرید اکانت و ظرفیت EA SPORTS FC"
    },
    "call of duty": {
        "triggers": ["call of duty", "black ops", "modern warfare", "warzone", "کالاف دیوتی", "کال آو دیوتی"],
        "product_keywords": ["call of duty", "black ops", "modern warfare", "کالاف", "کال آو دیوتی"],
        "button_label": "🎮 مشاهده و خرید اکانت Call of Duty"
    },
    "resident evil": {
        "triggers": ["resident evil", "رزیدنت اویل", "resident evil 9"],
        "product_keywords": ["resident evil", "رزیدنت اویل"],
        "button_label": "🎮 مشاهده و خرید اکانت Resident Evil"
    },
    "ghost of yotei": {
        "triggers": ["ghost of yotei", "ghost of tsushima", "گوست آو یوتی", "گوست آو سوشیما"],
        "product_keywords": ["ghost of yotei", "ghost of tsushima", "گوست"],
        "button_label": "🎮 مشاهده و خرید اکانت سری Ghost"
    },
    "elden ring": {
        "triggers": ["elden ring", "nightreign", "الدن رینگ"],
        "product_keywords": ["elden ring", "الدن رینگ"],
        "button_label": "🎮 مشاهده و خرید اکانت Elden Ring"
    },
    "god of war": {
        "triggers": ["god of war", "ragnarok", "گاد آو وار", "خدای جنگ"],
        "product_keywords": ["god of war", "گاد آف وار", "گاد آو وار"],
        "button_label": "🎮 مشاهده و خرید اکانت God of War"
    },
    "spider-man": {
        "triggers": ["spider-man", "spiderman", "marvel's spider-man", "اسپایدرمن", "مرد عنکبوتی"],
        "product_keywords": ["spider-man", "spiderman", "اسپایدرمن"],
        "button_label": "🎮 مشاهده و خرید اکانت Spider-Man"
    },
    "astro bot": {
        "triggers": ["astro bot", "استرو بات", "آسترو بات"],
        "product_keywords": ["astro bot", "استرو بات", "آسترو بات"],
        "button_label": "🎮 مشاهده و خرید اکانت Astro Bot"
    },
    "death stranding": {
        "triggers": ["death stranding", "دث استرندینگ"],
        "product_keywords": ["death stranding", "دث استرندینگ"],
        "button_label": "🎮 مشاهده و خرید اکانت Death Stranding"
    }
}

DIGITAL_POSITIVE_KEYWORDS = [
    "اکانت", "ظرفیت", "پلاس", "plus", "playstation plus", "ps plus",
    "بازی", "game", "گیفت کارت", "gift card", "شتاب", "اشتراک", "پیش خرید", "پیش‌خرید",
    "fc 27", "fc 26", "fc 25", "gta", "call of duty", "assassin", "god of war",
    "spider-man", "elden ring", "resident evil", "black myth", "astro bot",
    "silent hill", "ghost of", "last of us", "cyberpunk", "red dead",
    "mortal kombat", "tekken", "forza", "halo", "minecraft", "witcher",
    "battlefield", "death stranding", "final fantasy", "persona"
]

PHYSICAL_EXCLUDE_KEYWORDS = [
    "کنسول", "تبلت", "آیپد", "ipad", "آیفون", "iphone", "گوشی", "موبایل",
    "لپ تاپ", "لپ‌تاپ", "macbook", "مک بوک", "مانیتور", "تلویزیون",
    "دسته بازی", "dualsense", "دوآل سنس", "هدست", "هدفون", "ایرپاد", "airpods",
    "پایه شارژر", "دیسک‌خور", "دیسک خور", "ریجن اروپا سری", "کارت گرافیک",
    "ساعت هوشمند", "apple watch", "اپل واچ", "کیبورد", "ماوس", "موس", "اسپیکر",
    "هارد", "ssd", "فلش", "پاوربانک", "شارژر", "کابل"
]

BREAKING_TRIGGER_KEYWORDS = [
    "breaking", "officially announced", "official trailer", "release date announced",
    "delayed", "canceled", "cancelled", "state of play", "playstation showcase",
    "xbox games showcase", "gta vi", "gta 6", "ps5 pro", "nintendo switch 2",
    "rtx 5090", "rtx 5080", "فوری", "به‌طور رسمی معرفی شد", "تاریخ انتشار", "تریلر رسمی"
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

# ================= ۲. راه‌اندازی دیتابیس و مدیریت چرخه حیات خبر =================
bot = Bot(token=TELEGRAM_BOT_TOKEN)
os.makedirs('temp_media', exist_ok=True)
provider_rotation_index = 0

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # جدول مدیریت چرخه حیات خبرها با وضعیت‌های: discovered, pending, selected, published, rejected, failed
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
    # جدول رویدادهای هایپ برای محاسبه Decay زمانی و تشخیص ترند ۲۴ ساعته
    c.execute('''CREATE TABLE IF NOT EXISTS hype_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_name TEXT,
                    category TEXT,
                    score REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    # جدول کش کامل محصولات دیجیتالی سایت به همراه ویژگی‌های واقعی استخراج‌شده از صفحه
    c.execute('''CREATE TABLE IF NOT EXISTS digital_products_cache (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    image_url TEXT,
                    price TEXT,
                    in_stock INTEGER DEFAULT 1,
                    is_purchasable INTEGER DEFAULT 1,
                    real_features_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS posted_products (
                    product_url TEXT PRIMARY KEY,
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# ================= ۳. موتور Embedding و محاسبه Cosine Similarity =================
def compute_local_ngram_embedding(text: str, dim: int = 256) -> list[float]:
    """بردار ویژگی نرمال‌شده مبتنی بر کلیدواژه و ان-گرم (پشتیبان سریع و بدون توقف برای مقایسه معنایی)"""
    clean = re.sub(r'[^\w\s]', ' ', text.lower())
    tokens = [t for t in clean.split() if len(t) > 2]
    vec = [0.0] * dim
    if not tokens:
        return vec
    counts = Counter(tokens)
    # اضافه کردن دوگانه‌های کلمات (Bigrams) برای حفظ مفهوم عبارات
    for i in range(len(tokens) - 1):
        counts[f"{tokens[i]}_{tokens[i+1]}"] += 1.5
    for token, weight in counts.items():
        h = hash(token)
        idx = abs(h) % dim
        sign = 1.0 if (h & 1) == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log1p(weight))
    norm = math.sqrt(sum(x * x for x in vec))
    return [round(x / norm, 5) for x in vec] if norm > 0 else vec

async def get_text_embedding(text: str) -> list[float]:
    """دریافت Embedding معنایی از Gemini با fallback خودکار به بردار محلی در صورت محدودیت"""
    for api_key in GEMINI_API_KEYS[:1]:
        try:
            client = genai.Client(api_key=api_key)
            res = await asyncio.to_thread(
                client.models.embed_content,
                model=GEMINI_EMBEDDING_MODEL,
                contents=text[:600]
            )
            if res and res.embeddings and len(res.embeddings) > 0:
                vals = list(res.embeddings[0].values)
                norm = math.sqrt(sum(x * x for x in vals))
                return [round(x / norm, 5) for x in vals] if norm > 0 else vals
        except Exception:
            break
    return compute_local_ngram_embedding(text)

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
    """
    مقایسه معنایی خبرهای discovered با اخبار منتشرشده قبلی و خوشه‌بندی اخبار مشابه از منابع مختلف
    برای شمارش دقیق تعداد منابع (source_count) و تشخیص اخبار فوری.
    """
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

    # محاسبه بردار معنایی برای خبرهای تازه کشف‌شده
    discovered_items = []
    for row_id, r_title, r_text, src, is_brk in discovered_rows:
        # استفاده از بردار محلی یکسان برای مقایسه سریع درون‌چرخه و ذخیره در دیتابیس
        emb = compute_local_ngram_embedding(f"{r_title} {r_text}")
        discovered_items.append({
            'id': row_id,
            'title': r_title,
            'text': r_text,
            'source': src,
            'is_breaking': is_brk,
            'emb': emb,
            'duplicate_of_published': False
        })

    # ۱. حذف معنایی خبرهایی که قبلاً منتشر شده‌اند
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

    # ۲. خوشه‌بندی معنایی خبرهای جدید برای شمارش تعداد منابع مستقل و ارتقای خبر فوری
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
        # اگر یک خبر هم‌زمان در ۳ منبع یا بیشتر کار شده باشد، کاندیدای خبر فوری می‌شود
        is_breaking = 1 if (any(x['is_breaking'] for x in cluster) or unique_sources >= 3) else 0
        c.execute("""
            UPDATE news_items
            SET status = 'pending',
                source_count = ?,
                is_breaking_candidate = ?,
                embedding_json = ?
            WHERE id = ?
        """, (unique_sources, is_breaking, json.dumps(primary['emb']), primary['id']))
        # بقیه اعضای تکراری همان خوشه در وضعیت rejected قرار می‌گیرند تا دوباره ارسال نشوند
        for extra in cluster[1:]:
            c.execute("UPDATE news_items SET status = 'rejected' WHERE id = ?", (extra['id'],))

    conn.commit()
    conn.close()

# ================= ۴. الگوریتم هایپ زمان‌دار (Decay) و شناسایی ترند ۲۴ ساعته =================
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

def get_decayed_hype_scores() -> dict[str, float]:
    """
    محاسبه امتیاز هایپ با کاهش نمایی بر اساس زمان (Time-Decay):
    هر ۱۸ ساعت وزن رویدادهای قدیمی‌تر نصف می‌شود تا بازی‌های قدیمی غالب نشوند.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT entity_name, score, (julianday('now') - julianday(created_at)) * 24.0 AS age_hours
        FROM hype_events
        WHERE created_at >= datetime('now', '-7 days')
    """)
    rows = c.fetchall()
    conn.close()

    scores = Counter()
    for name, base_score, age_hours in rows:
        age = max(0.0, float(age_hours or 0.0))
        decay_factor = math.pow(0.5, age / HYPE_HALF_LIFE_HOURS)
        scores[name] += float(base_score) * decay_factor

    return dict(scores.most_common(50))

def detect_24h_trends(top_n: int = 8) -> list[dict]:
    """
    شناسایی بازی‌ها، محصولات و موضوعاتی که در ۲۴ ساعت گذشته بیشترین رشد خبری را داشته‌اند.
    """
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

# ================= ۵. توابع پاک‌سازی، Sanitization HTML و دانلود رسانه =================
def clean_raw_text(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def sanitize_telegram_html(text: str) -> str:
    """
    ایمن‌سازی کامل خروجی HTML هوش مصنوعی قبل از ارسال به تلگرام:
    حذف تگ‌های غیرمجاز، بستن تگ‌های بازمانده و تبدیل کاراکترهای خاص برای جلوگیری از شکست انتشار.
    """
    if not text:
        return ""
    # تبدیل تگ‌های strong/em به معادل استاندارد b/i
    text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*em\s*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*em\s*>', '</i>', text, flags=re.IGNORECASE)

    allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre']
    placeholders = {}
    counter = 0

    # نگه‌داری تگ‌های مجاز که به‌درستی جفت شده‌اند
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

    # حذف هرگونه تگ ناقص یا غیرمجاز باقی‌مانده
    text = re.sub(r'<[^>]+>', '', text)
    # Escape کردن کاراکترهای حساس HTML
    text = html.escape(text)

    # بازگردانی تگ‌های سالم و متوازن
    for tok, real_tag in placeholders.items():
        text = text.replace(tok, real_tag)

    return text.strip()

def extract_rss_media_info(entry) -> tuple[str | None, bool]:
    """استخراج تصویر شاخص و تشخیص وجود محتوای ویدئویی یا صوتی برای دسترس‌پذیری ناشنوایان"""
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
        async with session.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
            if resp.status == 200:
                filepath = os.path.join('temp_media', filename)
                with open(filepath, 'wb') as f:
                    f.write(await resp.read())
                return filepath
    except Exception as e:
        print(f"Error downloading image {url}: {e}")
    return None

# ================= ۶. ساختار خروجی هوش مصنوعی (Schema یکپارچه برای هر ۳ سرویس) =================
class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="ID of the selected news candidate")
    category_id: str = Field(description="One of: gaming, technology, hardware, crypto, film_tv, internet_culture, fun_meme, music, general_news")
    verification_status: str = Field(description="Must be one of: 'خبر رسمی', 'گزارش رسانه معتبر', 'شایعه و لیک', 'خبر تأییدنشده'")
    confidence_score: int = Field(default=85, description="Confidence percentage between 40 and 100 based on source reliability and confirmation")
    is_breaking: bool = Field(default=False, description="True if this is major breaking news requiring immediate attention")
    is_new_game_release: bool = Field(default=False, description="True if the news is about a new game release or pre-order announcement")
    series_name: str = Field(default="", description="Optional recurring series name if applicable: 'Game of the Week', 'Movie of the Week', 'Tech Breakdown', 'Weekly Gaming News', 'Best Hardware Deals', 'This Week in Gaming', or empty string")
    headline_persian: str = Field(description="Descriptive, clear Persian headline without HTML tags or emojis")
    summary_persian: str = Field(description="Short, accessible, well-edited Persian summary (2-3 short sentences) with 1 to 3 key terms wrapped in <b>...</b>")
    key_points_persian: list[str] = Field(description="2 to 3 short, structured bullet points in Persian summarizing the key facts (e.g., 'تاریخ انتشار: ...', 'پلتفرم‌ها: ...')")
    image_alt_persian: str = Field(default="", description="Clear Persian visual description of the news context/image for blind/screen-reader users")
    av_transcript_summary_persian: str = Field(default="", description="If the source contains video/trailer/audio, provide a clear Persian text transcript/summary of what happens or is said in the video for deaf users")
    topic_hashtags: list[str] = Field(description="2 to 3 specific Persian hashtags starting with # using underscores")
    topic_fingerprint: str = Field(description="1-sentence English summary for deduplication")
    related_game: str = Field(default="", description="Exact English canonical name of the related game, service, or console (e.g., 'PlayStation Plus', 'GTA VI', 'PS5 Pro', 'EA SPORTS FC 27'), otherwise empty string")
    hype_score: int = Field(default=5, description="Hype and viral importance score from 1 to 10")

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۷. موتور پردازش ۳ گانه AI با اعتبارسنجی Pydantic و Retry =================
JSON_SCHEMA_INSTRUCTION = """
Respond ONLY with a valid JSON object matching this exact schema:
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
        "وضعیت توسعه: ورود به مرحله پولیش نهایی"
      ],
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
                    raw_dict = json.loads(response.text)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت و اعتبارسنجی Schema با Gemini (کلید #{key_idx} | {model_name})")
                    return validated
                except (ValidationError, json.JSONDecodeError) as ve:
                    print(f"⚠️ خطای اعتبارسنجی Schema در Gemini: {ve}")
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"⚠️ خطا در ارتباط با Gemini (کلید #{key_idx} | {model_name}): {e}")
                    await asyncio.sleep(2)
                    break
    return None

async def call_groq_provider(prompt: str) -> BatchProcessResult | None:
    for key_idx, groq_key in enumerate(GROQ_API_KEYS, start=1):
        groq_client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        for attempt in range(1, 3):
            try:
                print(f"تلاش با Groq (کلید #{key_idx} | نوبت {attempt})...")
                completion = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are a Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.25
                )
                raw_dict = json.loads(completion.choices[0].message.content)
                validated = BatchProcessResult.model_validate(raw_dict)
                print(f"✅ موفقیت و اعتبارسنجی Schema با Groq (کلید #{key_idx})")
                return validated
            except (ValidationError, json.JSONDecodeError) as ve:
                print(f"⚠️ خطای اعتبارسنجی Schema در Groq (تلاش مجدد): {ve}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ خطا در Groq (کلید #{key_idx}): {e}")
                await asyncio.sleep(2)
                break
    return None

async def call_openrouter_provider(prompt: str) -> BatchProcessResult | None:
    for key_idx, or_key in enumerate(OPENROUTER_API_KEYS, start=1):
        or_client = AsyncOpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        for attempt in range(1, 3):
            try:
                print(f"تلاش با OpenRouter (کلید #{key_idx} | نوبت {attempt})...")
                completion = await or_client.chat.completions.create(
                    model="meta-llama/llama-3.3-70b-instruct:free",
                    messages=[
                        {"role": "system", "content": "You are a Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.25
                )
                raw_dict = json.loads(completion.choices[0].message.content)
                validated = BatchProcessResult.model_validate(raw_dict)
                print(f"✅ موفقیت و اعتبارسنجی Schema با OpenRouter (کلید #{key_idx})")
                return validated
            except (ValidationError, json.JSONDecodeError) as ve:
                print(f"⚠️ خطای اعتبارسنجی Schema در OpenRouter (تلاش مجدد): {ve}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ خطا در OpenRouter (کلید #{key_idx}): {e}")
                await asyncio.sleep(2)
                break
    return None

async def generate_news_with_fallback(prompt: str) -> BatchProcessResult | None:
    """چرخش هوشمند بین ۳ سرویس API به همراه اعتبارسنجی اجباری BatchProcessResult"""
    global provider_rotation_index
    providers = [call_gemini_provider, call_groq_provider, call_openrouter_provider]
    ordered_providers = providers[provider_rotation_index % 3:] + providers[:provider_rotation_index % 3]
    provider_rotation_index += 1

    for provider_fn in ordered_providers:
        validated_result = await provider_fn(prompt)
        if validated_result and validated_result.selected_news:
            return validated_result
    return None

# ================= ۸. ایندکس کامل محصولات دیجیتالی سایت و استخراج واقعی ویژگی‌ها =================
def is_digital_game_or_plus_product(title: str, url: str = "") -> bool:
    combined = f"{title} {unquote(url)}".lower()
    for bad_kw in PHYSICAL_EXCLUDE_KEYWORDS:
        if bad_kw.lower() in combined:
            return False
    for good_kw in DIGITAL_POSITIVE_KEYWORDS:
        if good_kw.lower() in combined:
            return True
    return False

def extract_real_product_features(page_text: str, short_desc: str = "") -> dict:
    """
    استخراج اطلاعات واقعی محصول (شرایط تحویل، گارانتی، خرید اقساطی، ظرفیت‌ها و پیش‌خرید)
    مستقیماً از متن صفحه همان محصول بدون استفاده از عبارات ثابت غیرواقعی.
    """
    combined = f"{short_desc} {page_text}"
    features = {
        "delivery": "",
        "warranty": "",
        "installment": "",
        "capacities": "",
        "is_preorder": False
    }

    # ۱. بررسی واقعی نحوه تحویل
    delivery_match = re.search(r'(تحویل\s*(?:فوری|آنی|در\s*\d+\s*ساعت|خودکار|ایمیلی|تلگرام))', combined)
    if delivery_match:
        features["delivery"] = delivery_match.group(1).strip()

    # ۲. بررسی واقعی گارانتی در صفحه محصول
    warranty_match = re.search(r'(گارانتی\s*(?:دائمی|مادام‌العمر|مادام العمر|تعویض|معتبر|رسمی|\d+\s*ماهه)|ضمانت\s*(?:دائمی|بازگشت\s*وجه|اصالت))', combined)
    if warranty_match:
        features["warranty"] = warranty_match.group(1).strip()

    # ۳. بررسی واقعی امکان خرید اقساطی در صفحه محصول
    if any(k in combined for k in ["اقساط", "قسطی", "اسنپ پی", "اسنپ‌پی", "ترب پی", "دیجی پی", "ازکی وام"]):
        features["installment"] = "امکان خرید نقد و اقساط (طبق شرایط درج‌شده در صفحه محصول)"

    # ۴. بررسی ظرفیت‌های موجود
    caps = []
    if "ظرفیت ۱" in combined or "ظرفیت 1" in combined:
        caps.append("ظرفیت ۱")
    if "ظرفیت ۲" in combined or "ظرفیت 2" in combined:
        caps.append("ظرفیت ۲")
    if "ظرفیت ۳" in combined or "ظرفیت 3" in combined:
        caps.append("ظرفیت ۳")
    if caps:
        features["capacities"] = "، ".join(caps)

    # ۵. تشخیص پیش‌خرید
    if "پیش خرید" in combined or "پیش‌خرید" in combined or "pre-order" in combined.lower():
        features["is_preorder"] = True

    return features

def save_digital_products_to_db(products: list[dict]):
    if not products:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for p in products:
        c.execute("""
            INSERT OR REPLACE INTO digital_products_cache
            (url, title, image_url, price, in_stock, is_purchasable, real_features_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            p['url'],
            p['title'],
            p.get('image_url'),
            p.get('price', 'مشاهده قیمت در صفحه محصول'),
            1 if p.get('in_stock', True) else 0,
            1 if p.get('is_purchasable', True) else 0,
            json.dumps(p.get('real_features', {}), ensure_ascii=False)
        ))
    conn.commit()
    conn.close()

def get_all_available_digital_products() -> list[dict]:
    """خواندن تمام محصولات دیجیتالی واقعاً موجود و قابل خرید از کش دیتابیس"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT url, title, image_url, price, in_stock, is_purchasable, real_features_json
        FROM digital_products_cache
        WHERE in_stock = 1 AND is_purchasable = 1
    """)
    rows = c.fetchall()
    conn.close()
    products = []
    for r in rows:
        try:
            feats = json.loads(r[6]) if r[6] else {}
        except Exception:
            feats = {}
        products.append({
            'url': r[0],
            'title': r[1],
            'image_url': r[2],
            'price': r[3],
            'in_stock': bool(r[4]),
            'is_purchasable': bool(r[5]),
            'real_features': feats
        })
    return products

async def discover_all_product_urls_from_site(session: aiohttp.ClientSession) -> list[str]:
    discovered_urls = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    sitemap_candidates = [
        f"{STORE_BASE_URL}/product-sitemap.xml",
        f"{STORE_BASE_URL}/sitemap_index.xml",
        f"{STORE_BASE_URL}/sitemap.xml",
    ]

    for sm_url in sitemap_candidates:
        try:
            async with session.get(sm_url, timeout=15, headers=headers) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    locs = re.findall(r'<loc>(https?://[^<]+)</loc>', xml_text)
                    sub_sitemaps = [u for u in locs if 'product' in u and u.endswith('.xml')]
                    # بررسی تمام زیرنقشه‌های محصول بدون محدودیت
                    for sub_sm in sub_sitemaps:
                        async with session.get(sub_sm, timeout=15, headers=headers) as sub_resp:
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
                async with session.get(page_url, timeout=15, headers=headers) as resp:
                    if resp.status == 200:
                        html_text = await resp.text()
                        soup = BeautifulSoup(html_text, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            full_url = urljoin(STORE_BASE_URL, a['href'])
                            if full_url.startswith(STORE_BASE_URL) and any(p in full_url for p in ['/product/', '/products/', '/p/']):
                                discovered_urls.add(full_url)
            except Exception:
                continue

    return [
        u for u in discovered_urls
        if not any(bad in unquote(u).lower() for bad in PHYSICAL_EXCLUDE_KEYWORDS)
    ]

async def scrape_single_digital_product(session: aiohttp.ClientSession, url: str) -> dict | None:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        async with session.get(url, timeout=15, headers=headers) as resp:
            if resp.status != 200:
                return None
            html_text = await resp.text()

        soup = BeautifulSoup(html_text, 'html.parser')

        title = None
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content'].split('|')[0].split('- جاذبه')[0].strip()
        if not title and soup.find('h1'):
            title = soup.find('h1').get_text(strip=True)
        if not title or not is_digital_game_or_plus_product(title, url):
            return None

        page_text = soup.get_text(" ", strip=True)
        avail_meta = soup.find('meta', property='og:availability') or soup.find('meta', property='product:availability')
        in_stock = True
        if avail_meta and 'outofstock' in str(avail_meta.get('content', '')).lower():
            in_stock = False
        if ('ناموجود' in page_text or 'اتمام موجودی' in page_text) and 'افزودن به سبد' not in page_text:
            in_stock = False

        image_url = None
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            image_url = og_img['content']

        price_str = ""
        price_meta = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
        if price_meta and price_meta.get('content'):
            try:
                raw_price = int(float(str(price_meta['content']).replace(',', '').strip()))
                if raw_price > 0:
                    price_str = f"{raw_price:,} تومان"
            except Exception:
                pass
        if not price_str:
            price_match = re.search(r'(\d{1,3}(?:,\d{3})+)\s*تومان', page_text)
            if price_match:
                price_str = f"{price_match.group(1)} تومان"

        is_purchasable = bool(in_stock and price_str)
        desc_meta = soup.find('meta', property='og:description')
        short_desc = desc_meta['content'] if desc_meta and desc_meta.get('content') else ""
        real_features = extract_real_product_features(page_text, short_desc)

        return {
            'title': title,
            'url': url,
            'image_url': image_url,
            'price': price_str or "مشاهده قیمت در صفحه محصول",
            'in_stock': in_stock,
            'is_purchasable': is_purchasable,
            'real_features': real_features
        }
    except Exception:
        return None

async def refresh_digital_products_catalog(session: aiohttp.ClientSession):
    """
    بروزرسانی کامل کاتالوگ محصولات دیجیتالی سایت (بدون محدودیت ۴۵ تایی):
    ۱. دریافت صفحه‌بندی‌شده از WooCommerce Store API در صورت فعال بودن
    ۲. پیمایش کامل لینک‌های Sitemap با اولویت لینک‌های جدید یا قدیمی‌تر در کش
    """
    collected = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # مرحله اول: بررسی WooCommerce Store API برای دریافت سریع کل محصولات
    for page_num in range(1, 5):
        api_url = f"{STORE_BASE_URL}/wp-json/wc/store/v1/products?per_page=100&page={page_num}"
        try:
            async with session.get(api_url, timeout=15, headers=headers) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not isinstance(data, list) or not data:
                    break
                for p in data:
                    title = clean_raw_text(p.get('name', ''))
                    permalink = p.get('permalink', '')
                    if not title or not permalink or not is_digital_game_or_plus_product(title, permalink):
                        continue
                    in_stock = bool(p.get('is_in_stock', False))
                    is_purchasable = bool(p.get('is_purchasable', True) and in_stock)
                    prices = p.get('prices', {})
                    raw_price = str(prices.get('price', ''))
                    minor_unit = int(prices.get('currency_minor_unit', 0))
                    currency_code = str(prices.get('currency_code', '')).upper()
                    price_str = ""
                    if raw_price.isdigit():
                        val = int(raw_price) // (10 ** minor_unit)
                        if currency_code in ['IRR', 'RIAL']:
                            val = val // 10
                        if val > 0:
                            price_str = f"{val:,} تومان"
                    images = p.get('images', [])
                    img_url = images[0].get('src') if images else None
                    short_desc = clean_raw_text(p.get('short_description', ''))
                    full_desc = clean_raw_text(p.get('description', ''))
                    real_features = extract_real_product_features(full_desc, short_desc)
                    collected.append({
                        'title': title,
                        'url': permalink,
                        'image_url': img_url,
                        'price': price_str or "مشاهده قیمت در صفحه محصول",
                        'in_stock': in_stock,
                        'is_purchasable': is_purchasable and bool(price_str),
                        'real_features': real_features
                    })
        except Exception:
            break

    if collected:
        save_digital_products_to_db(collected)
        print(f"✅ کاتالوگ کامل ({len(collected)} محصول دیجیتالی) از طریق API سایت همگام‌سازی شد.")
        return

    # مرحله دوم: در صورت بسته بودن API، پیمایش سیستماتیک کل لینک‌های Sitemap
    all_urls = await discover_all_product_urls_from_site(session)
    if not all_urls:
        print("⚠️ لینکی از نقشه سایت دریافت نشد.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT url FROM digital_products_cache WHERE updated_at >= datetime('now', '-6 hours')")
    recently_updated = {r[0] for r in c.fetchall()}
    conn.close()

    # اولویت با محصولاتی که هنوز در کش نیستند یا بیش از ۶ ساعت از آپدیت آن‌ها گذشته است
    priority_urls = [u for u in all_urls if u not in recently_updated]
    if len(priority_urls) < 100:
        remaining = [u for u in all_urls if u in recently_updated]
        priority_urls.extend(remaining[:100 - len(priority_urls)])

    batch_to_scrape = priority_urls[:120]
    sem = asyncio.Semaphore(10)

    async def fetch_with_sem(u):
        async with sem:
            return await scrape_single_digital_product(session, u)

    results = await asyncio.gather(*(fetch_with_sem(u) for u in batch_to_scrape))
    valid_digital = [r for r in results if r is not None]
    if valid_digital:
        save_digital_products_to_db(valid_digital)
        total_available = len(get_all_available_digital_products())
        print(f"✅ تعداد {len(valid_digital)} صفحه محصول بررسی شد. مجموع محصولات دیجیتالی موجود در کش: {total_available}")

# ================= ۹. سیستم پیشنهاد محصول مرتبط با هر خبر (با Alias Mapping) =================
def resolve_canonical_entity(text: str) -> str:
    """تبدیل نام‌های مختلف فارسی، انگلیسی و مخفف به کلید استاندارد در PRODUCT_ALIAS_MAP"""
    if not text:
        return ""
    low = text.strip().lower()
    for canonical_key, data in PRODUCT_ALIAS_MAP.items():
        if canonical_key in low:
            return canonical_key
        for trig in data["triggers"]:
            if trig.lower() in low:
                return canonical_key
    return low

def find_matching_store_product_for_news(
    related_game: str,
    headline: str = "",
    summary: str = "",
    is_new_release: bool = False
) -> tuple[dict | None, str]:
    """
    پیدا کردن محصول دیجیتالی مرتبط که واقعاً در سایت موجود و قابل خرید باشد:
    - Plus -> اشتراک PlayStation Plus
    - خبر GTA VI -> بازی GTA VI
    - خبر PS5 Pro -> محصولات و خدمات سازگار با PlayStation 5
    - خبر FC 27 -> اکانت و ظرفیت FC
    - خبر عرضه بازی جدید -> پیش‌خرید یا محصولات مرتبط همان بازی
    """
    available_products = get_all_available_digital_products()
    if not available_products:
        return None, ""

    combined_news_context = f"{related_game} {headline} {summary}".lower()
    canonical_key = resolve_canonical_entity(related_game) or resolve_canonical_entity(combined_news_context)

    # ۱. جست‌وجو بر اساس نقشه Alias استاندارد (Plus, GTA VI, PS5 Pro, FC 27 و ...)
    if canonical_key in PRODUCT_ALIAS_MAP:
        rule = PRODUCT_ALIAS_MAP[canonical_key]
        candidates = []
        for prod in available_products:
            p_text = f"{prod['title']} {unquote(prod['url'])}".lower()
            if any(kw.lower() in p_text for kw in rule["product_keywords"]):
                candidates.append(prod)
        if candidates:
            # برای بازی جدید، اولویت با پیش‌خرید است
            if is_new_release:
                preorders = [c for c in candidates if c.get('real_features', {}).get('is_preorder')]
                if preorders:
                    return preorders[0], f"🛒 پیش‌خرید و مشاهده {preorders[0]['title'][:30]}"
            return candidates[0], rule["button_label"]

    # ۲. جست‌وجوی تطبیق توکن برای سایر بازی‌های مشخص‌شده در related_game
    if related_game and len(related_game.strip()) >= 3:
        rg_clean = related_game.strip().lower()
        rg_tokens = [t for t in re.split(r'\W+', rg_clean) if len(t) > 2]
        for prod in available_products:
            p_text = f"{prod['title']} {unquote(prod['url'])}".lower()
            if rg_clean in p_text or (len(rg_tokens) >= 2 and all(t in p_text for t in rg_tokens)):
                if is_new_release and prod.get('real_features', {}).get('is_preorder'):
                    return prod, f"🛒 پیش‌خرید {prod['title'][:32]}"
                return prod, f"🎮 مشاهده و خرید {prod['title'][:32]}"

    return None, ""

def calculate_product_hype_weight(product: dict, decayed_hype_map: dict[str, float], trends_24h: list[dict]) -> float:
    base_weight = 1.0
    p_text = f"{product['title']} {unquote(product['url'])}".lower()

    if "پلاس" in p_text or "plus" in p_text:
        base_weight += 2.0

    # اعمال امتیاز زمان‌دار (Time-Decayed Hype) با پشتیبانی از Alias Mapping
    for hyped_entity, decayed_score in decayed_hype_map.items():
        canonical = resolve_canonical_entity(hyped_entity)
        if canonical in PRODUCT_ALIAS_MAP:
            kws = PRODUCT_ALIAS_MAP[canonical]["product_keywords"]
            if any(k.lower() in p_text for k in kws):
                base_weight += (decayed_score * 2.5)
        elif len(hyped_entity) >= 3 and hyped_entity in p_text:
            base_weight += (decayed_score * 2.5)

    # ضریب ویژه برای ترندهای برتر ۲۴ ساعت گذشته
    for tr in trends_24h:
        ent = tr["entity"]
        if len(ent) >= 3 and ent in p_text:
            base_weight += 4.0

    return round(base_weight, 2)

def was_product_recently_posted(product_url: str, hours: int = 12) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM posted_products WHERE posted_at < datetime('now', ?)", (f'-{hours} hours',))
    conn.commit()
    c.execute("SELECT 1 FROM posted_products WHERE product_url = ?", (product_url,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_product_posted(product_url: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO posted_products (product_url, posted_at) VALUES (?, CURRENT_TIMESTAMP)", (product_url,))
    conn.commit()
    conn.close()

async def publish_weighted_digital_products(session: aiohttp.ClientSession):
    """
    انتشار محصولات دیجیتالی موجود با اطلاعات واقعی استخراج‌شده از صفحه محصول و رعایت کامل دسترس‌پذیری.
    """
    available_products = get_all_available_digital_products()
    if len(available_products) < PRODUCTS_PER_CYCLE:
        await refresh_digital_products_catalog(session)
        available_products = get_all_available_digital_products()

    if not available_products:
        print("هیچ محصول دیجیتالی موجود و قابل خریدی برای ارسال یافت نشد.")
        return

    unposted_pool = [p for p in available_products if not was_product_recently_posted(p['url'], hours=12)]
    candidate_pool = unposted_pool if len(unposted_pool) >= PRODUCTS_PER_CYCLE else available_products

    decayed_hype_map = get_decayed_hype_scores()
    trends_24h = detect_24h_trends(top_n=6)

    selected_products = []
    temp_pool = candidate_pool.copy()

    for _ in range(min(PRODUCTS_PER_CYCLE, len(temp_pool))):
        weights = [calculate_product_hype_weight(p, decayed_hype_map, trends_24h) for p in temp_pool]
        chosen = random.choices(temp_pool, weights=weights, k=1)[0]
        chosen['_weight'] = calculate_product_hype_weight(chosen, decayed_hype_map, trends_24h)
        selected_products.append(chosen)
        temp_pool.remove(chosen)

    for idx, prod in enumerate(selected_products, start=1):
        is_plus = "پلاس" in prod['title'].lower() or "plus" in prod['title'].lower()
        badge_emoji = "💎" if is_plus else "🎮"
        product_type_text = "اشتراک پلی‌استیشن پلاس" if is_plus else "اکانت دیجیتالی بازی"
        real_feats = prod.get('real_features', {})

        # ساخت متن دسترس‌پذیر و شفاف فقط بر اساس اطلاعات واقعی موجود در صفحه محصول
        lines = [
            f"{badge_emoji} <b>{html.escape(prod['title'])}</b>",
            f"دسته‌بندی: فروشگاه دیجیتالی | وضعیت موجودی: <b>موجود و قابل خرید</b>",
            "",
            "<b>مشخصات و شرایط واقعی محصول:</b>",
            f"• نوع محصول: {product_type_text}",
            f"• قیمت فعلی: <b>{html.escape(prod['price'])}</b>"
        ]

        if real_feats.get("capacities"):
            lines.append(f"• ظرفیت‌های ذکرشده: {html.escape(real_feats['capacities'])}")
        if real_feats.get("delivery"):
            lines.append(f"• نحوه تحویل: <b>{html.escape(real_feats['delivery'])}</b>")
        if real_feats.get("warranty"):
            lines.append(f"• شرایط گارانتی: <b>{html.escape(real_feats['warranty'])}</b>")
        if real_feats.get("installment"):
            lines.append(f"• شرایط پرداخت: <b>{html.escape(real_feats['installment'])}</b>")

        if prod.get('image_url'):
            lines.append(f"\n🖼 <b>توضیح تصویر:</b> کاور رسمی محصول {html.escape(prod['title'])} در فروشگاه جاذبه استور.")

        lines.append("\n🏷 #اکانت_ظرفیتی #پلی_استیشن_پلاس #فروشگاه_دیجیتالی")
        caption = "\n".join(lines) + CHANNEL_SIGNATURE

        # دکمه تمام‌عرض، واضح و بدون ابهام (مناسب برای کاربران دارای محدودیت حرکتی و نابینایان)
        btn_label = "🛒 مشاهده جزئیات و خرید آنلاین محصول در سایت"
        if real_feats.get("installment"):
            btn_label = "💳 مشاهده جزئیات و خرید محصول (نقد و اقساط)"

        keyboard = [
            [InlineKeyboardButton(btn_label, url=prod['url'])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if prod.get('image_url'):
                img_path = await download_image_from_url(session, prod['image_url'], f"prod_{idx}.jpg")
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
            print(f"🛒 محصول دیجیتالی ارسال شد: {prod['title']} (وزن هایپ زمان‌دار: {prod.get('_weight', 1.0)})")
            await asyncio.sleep(8)
        except Exception as e:
            print(f"Error sending digital product '{prod['title']}': {e}")

# ================= ۱۰. جمع‌آوری هم‌زمان فیدهای RSS با یک Session مشترک =================
async def fetch_single_feed(session: aiohttp.ClientSession, sem: asyncio.Semaphore, category: str, url: str) -> list[dict]:
    async with sem:
        try:
            async with session.get(url, timeout=12, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
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

                # پرهیز از انتشار خبرهایی که متن کافی ندارند و اطلاعاتشان صرفاً داخل تصویر است (استاندارد ۴.۱ نابینایان)
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
                    'raw_text': cleaned_body[:600],
                    'image_url': img_url,
                    'has_video_or_audio': 1 if has_av else 0,
                    'is_breaking_candidate': 1 if is_breaking else 0
                })
            return extracted
        except Exception:
            return []

async def fetch_rss_sources(session: aiohttp.ClientSession):
    """دریافت تمام فیدها با یک Session مشترک و ثبت اولیه با وضعیت discovered در دیتابیس"""
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

# ================= ۱۱. پردازش، قالب‌بندی دسترس‌پذیر و انتشار اخبار (عادی و فوری) =================
def format_accessible_news_post(sel: SelectedNewsItem, orig_item: dict, main_cat_hashtag: str) -> str:
    """
    ساختار استاندارد دسترس‌پذیر (WCAG & Screen-Reader Friendly) برای تمام پیام‌ها:
    - مجموعه سریالی یا نشان خبر فوری (در صورت وجود)
    - تیتر توصیفی و مشخص
    - دسته‌بندی | وضعیت اعتبارسنجی | درجه اطمینان و تعداد منابع
    - خلاصه کوتاه و روان با بولد کردن نکات کلیدی
    - مهم‌ترین نکات (بولت‌پوینت‌های ساختاری)
    - خلاصه محتوای صوتی/تصویری (برای ناشنوایان در صورت وجود ویدئو/صدا)
    - توضیح تصویر (برای نابینایان در صورت وجود عکس)
    """
    lines = []

    # ۱. هدر مجموعه سریالی یا خبر فوری
    if sel.is_breaking:
        lines.append("🚨 <b>خبر فوری | پوشش ویژه</b>")
    if sel.series_name and sel.series_name in SERIALIZED_SERIES_HEADERS:
        lines.append(f"<b>{SERIALIZED_SERIES_HEADERS[sel.series_name]}</b>")

    # ۲. تیتر واضح با یک ایموجی هدفمند
    cat_emoji_map = {
        "gaming": "🎮",
        "technology": "💻",
        "hardware": "⚡",
        "crypto": "🪙",
        "film_tv": "🍿",
        "internet_culture": "🌐",
        "fun_meme": "😄",
        "music": "🎵",
        "general_news": "📰"
    }
    lead_emoji = cat_emoji_map.get(sel.category_id, "📰")
    safe_headline = sanitize_telegram_html(sel.headline_persian)
    lines.append(f"{lead_emoji} <b>{safe_headline}</b>")

    # ۳. خط شناسنامه و اعتبارسنجی خبر
    cat_persian = CATEGORY_PERSIAN_NAMES.get(sel.category_id, "اخبار")
    valid_statuses = ["خبر رسمی", "گزارش رسانه معتبر", "شایعه و لیک", "خبر تأییدنشده"]
    ver_status = sel.verification_status if sel.verification_status in valid_statuses else "گزارش رسانه معتبر"
    conf_score = max(40, min(100, int(sel.confidence_score or 85)))
    src_count = max(1, int(orig_item.get('source_count', 1)))

    lines.append(f"دسته‌بندی: {cat_persian} | وضعیت: <b>{ver_status}</b>")
    lines.append(f"درجه اطمینان: {conf_score}٪ | تعداد منابع: {src_count} منبع")
    lines.append("")

    # ۴. متن خلاصه خبر (ویراستاری‌شده و ایمن‌سازی‌شده)
    safe_summary = sanitize_telegram_html(sel.summary_persian)
    lines.append(safe_summary)

    # ۵. بخش ساختاری «مهم‌ترین نکات:»
    if sel.key_points_persian:
        lines.append("")
        lines.append("<b>مهم‌ترین نکات:</b>")
        for pt in sel.key_points_persian[:3]:
            clean_pt = sanitize_telegram_html(pt.lstrip("•-*▫️🔹 "))
            if clean_pt:
                lines.append(f"• {clean_pt}")

    # ۶. دسترس‌پذیری ناشنوایان و کم‌شنوایان (در صورت وجود ویدئو/تریلر/صوت)
    if orig_item.get('has_video_or_audio') or sel.av_transcript_summary_persian.strip():
        av_text = sanitize_telegram_html(
            sel.av_transcript_summary_persian.strip()
            or "تمامی اطلاعات کلیدی این ویدئو/فایل صوتی به صورت متنی در نکات بالا درج شده است."
        )
        lines.append("")
        lines.append(f"📝 <b>متن و خلاصه محتوای ویدئویی/صوتی (ویژه ناشنوایان):</b> {av_text}")

    # ۷. دسترس‌پذیری نابینایان و کم‌بینایان (توضیح تصویر مستقل در متن برای پست‌های عکس‌دار)
    if orig_item.get('image_url'):
        alt_text = sanitize_telegram_html(
            sel.image_alt_persian.strip()
            or f"تصویر مرتبط با خبر «{sel.headline_persian}»"
        )
        lines.append("")
        lines.append(f"🖼 <b>توضیح تصویر:</b> {alt_text}")

    # ۸. هشتگ‌ها
    extra_tags = []
    for tag in sel.topic_hashtags:
        clean_tag = re.sub(r'[^\w#]', '_', tag.strip())
        if not clean_tag.startswith("#"):
            clean_tag = "#" + clean_tag
        if clean_tag != main_cat_hashtag and len(clean_tag) > 2:
            extra_tags.append(clean_tag)

    hashtags_line = " ".join([main_cat_hashtag] + extra_tags[:3])
    lines.append(f"\n🏷 {hashtags_line}{CHANNEL_SIGNATURE}")
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
            ORDER BY source_count DESC, id DESC LIMIT 25
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
        ORDER BY published_at DESC LIMIT 80
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
            'text': r[5],
            'image_url': r[6],
            'has_video_or_audio': bool(r[7]),
            'source_count': r[8],
            'is_breaking_candidate': bool(r[9])
        }
        for r in rows
    ]

    trends_24h = detect_24h_trends(top_n=6)
    candidates_for_ai = [
        {
            "id": item['id'],
            "default_category": item['category'],
            "source_domain": item['source'].split('/')[2] if '//' in item['source'] else item['source'],
            "source_count": item['source_count'],
            "is_breaking_candidate": item['is_breaking_candidate'],
            "has_image": bool(item['image_url']),
            "has_video_or_audio": item['has_video_or_audio'],
            "text": item['text']
        }
        for item in current_batch
    ]

    mode_label = "BREAKING NEWS IMMEDIATE DISPATCH" if breaking_only else "REGULAR 30-MIN EDITORIAL CYCLE"
    prompt = f"""
    You are the Chief Editor for '@jazebestore', a premier Accessible Persian Gaming, Tech, Hardware, Crypto, Entertainment, and Internet Culture Telegram channel.
    Current Year Context: 2026. Dispatch Mode: {mode_label}.

    24-Hour Trending Topics in our ecosystem:
    {json.dumps(trends_24h, ensure_ascii=False)}

    Already published topics in the last 48 hours (DO NOT repeat these topics conceptually):
    {json.dumps(recent_topics, ensure_ascii=False)}

    Incoming news candidates:
    {json.dumps(candidates_for_ai, ensure_ascii=False)}

    STRICT EDITORIAL, ACCESSIBILITY (WCAG), AND VERIFICATION GUIDELINES:
    1. SELECTION & DEDUPLICATION:
       - Select AT MOST {max_items} unique, high-value stories.
       - Never select items whose information is purely visual with no substantive text context.
       - Include fun community jokes/gaming memes (`category_id`: "fun_meme") when entertaining candidates exist.
    2. NEWS VERIFICATION SYSTEM (`verification_status` & `confidence_score`):
       - Classify `verification_status` strictly into one of:
         * "خبر رسمی" (Official statement from PlayStation, Xbox, Rockstar, Apple, etc.)
         * "گزارش رسانه معتبر" (Confirmed report by IGN, Bloomberg, Reuters, Eurogamer, etc.)
         * "شایعه و لیک" (Insider leaks, datamines, unconfirmed industry rumors)
         * "خبر تأییدنشده" (Early unverified reports)
       - Set `confidence_score` (40 to 100) based on source authority and `source_count`.
    3. SERIALIZED CONTENT (`series_name`):
       - When an article strongly fits one of our recurring series, assign `series_name` from:
         ["Game of the Week", "Movie of the Week", "Tech Breakdown", "Weekly Gaming News", "Best Hardware Deals", "This Week in Gaming"].
       - Otherwise leave `series_name` as "".
    4. ACCESSIBILITY FOR ALL 4 GROUPS (CRITICAL):
       - `headline_persian`: Clear, descriptive Persian headline (no clickbait, no emojis, no HTML tags).
       - `summary_persian`: Short, clear sentences (2-3 sentences max) in polished Persian with proper half-spaces (نیم‌فاصله). Wrap 1 to 3 key facts/dates/numbers in `<b>...</b>`.
       - `key_points_persian`: 2 to 3 structured Persian bullet items (e.g., "تاریخ انتشار: ...", "پلتفرم‌ها: ...", "وضعیت: ...").
       - `image_alt_persian`: If `has_image` is true, write a 1-sentence descriptive Persian explanation of what the image/artwork represents for blind screen-reader users.
       - `av_transcript_summary_persian`: If `has_video_or_audio` is true (or news is about a trailer/podcast/showcase), write a concise Persian text transcript/summary of the video/audio content for deaf users.
    5. PRODUCT & HYPE LINKING (`related_game` & `is_new_game_release`):
       - Keep proper nouns in English.
       - If the news is about PlayStation Plus, set `related_game` = "PlayStation Plus".
       - If about GTA VI, set `related_game` = "GTA VI".
       - If about PS5 Pro or PlayStation 5 hardware, set `related_game` = "PS5 Pro".
       - If about EA SPORTS FC 27 / FC 26, set `related_game` = "EA SPORTS FC 27".
       - For any other specific video game, put its exact canonical English title in `related_game`.
       - Set `is_new_game_release` = true if the news announces a new game release or pre-order.
    """

    validated_result = await generate_news_with_fallback(prompt)

    if not validated_result:
        print("❌ تمامی سرویس‌های AI در این نوبت با خطا مواجه شدند. وضعیت خبرها روی pending باقی ماند تا از دست نروند.")
        return

    selected_items = validated_result.selected_news[:max_items]
    batch_map = {item['id']: item for item in current_batch}
    selected_ids = {sel.selected_id for sel in selected_items if sel.selected_id in batch_map}
    non_selected_ids = [item['id'] for item in current_batch if item['id'] not in selected_ids]

    # تغییر وضعیت در دیتابیس قبل از شروع ارسال
    if selected_ids:
        update_news_status(list(selected_ids), 'selected')
    if not breaking_only and non_selected_ids:
        update_news_status(non_selected_ids, 'rejected')

    tehran_hour = datetime.now(ZoneInfo("Asia/Tehran")).hour
    silent_mode = (0 <= tehran_hour < 8) and not breaking_only

    for sel in selected_items:
        orig_item = batch_map.get(sel.selected_id)
        if not orig_item:
            continue

        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
        main_cat_hashtag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")
        final_caption = format_accessible_news_post(sel, orig_item, main_cat_hashtag)

        news_link = orig_item.get('link', STORE_BASE_URL)
        # طراحی دکمه‌های بزرگ، تمام‌عرض و با نام کاملاً واضح برای دسترس‌پذیری حرکتی و نابینایان
        keyboard = [
            [InlineKeyboardButton("❤️ پسندیدن این خبر (0)", callback_data=f"like_{orig_item['id']}")],
            [InlineKeyboardButton("🔗 مطالعه گزارش کامل در منبع اصلی", url=news_link)]
        ]

        # پیشنهاد محصول مرتبط (فقط در صورت موجود بودن، قابل خرید بودن و ارتباط واقعی)
        matched_product, custom_btn_label = find_matching_store_product_for_news(
            related_game=sel.related_game,
            headline=sel.headline_persian,
            summary=sel.summary_persian,
            is_new_release=sel.is_new_game_release
        )
        if matched_product:
            keyboard.append([
                InlineKeyboardButton(custom_btn_label, url=matched_product['url'])
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if orig_item.get('image_url'):
                img_path = await download_image_from_url(session, orig_item['image_url'], f"img_{orig_item['id']}.jpg")
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as photo_file:
                        await bot.send_photo(
                            chat_id=TARGET_CHANNEL,
                            photo=photo_file,
                            caption=final_caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                            disable_notification=silent_mode
                        )
                    os.remove(img_path)
                else:
                    await bot.send_message(
                        chat_id=TARGET_CHANNEL,
                        text=final_caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        disable_notification=silent_mode
                    )
            else:
                await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=final_caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_notification=silent_mode
                )

            # تنها پس از ارسال موفق، خبر وضعیت published می‌گیرد
            save_published_news_details(
                item_id=orig_item['id'],
                fingerprint=sel.topic_fingerprint,
                pub_cat=cat_id,
                pub_headline=sel.headline_persian,
                related_entity=sel.related_game,
                ai_payload=sel.model_dump()
            )

            # ثبت در جدول رویدادهای هایپ زمان‌دار
            if sel.related_game:
                record_hype_event(sel.related_game, cat_id, float(sel.hype_score))

            await asyncio.sleep(4)

        except Exception as send_err:
            print(f"⚠️ خطا در ارسال خبر #{orig_item['id']} به تلگرام: {send_err}")
            update_news_status([orig_item['id']], 'failed', increment_retry=True)

# ================= ۱۲. گزارش خلاصه روزانه (Daily Digest ساعت ۰۰:۰۰ به وقت تهران) =================
async def publish_daily_digest_if_due():
    tehran_tz = ZoneInfo("Asia/Tehran")
    now_tehran = datetime.now(tehran_tz)
    today_str = now_tehran.strftime("%Y-%m-%d")

    # اجرا در بازه ساعت ۰۰:۰۰ تا ۰۰:۲۰ بامداد به وقت تهران (یک‌بار در هر شبانه‌روز)
    if now_tehran.hour != 0 or now_tehran.minute > 20:
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
    digest_lines.append("• فردا در جاذبه استور: پوشش ادامه رویدادهای مرتبط با این عناوین و بررسی تغییرات قیمت اکانت‌ها و اشتراک‌ها.")
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

# ================= ۱۳. مدیریت دکمه لایک پست‌ها (با حفظ ساختار دسترس‌پذیر) =================
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

# ================= ۱۴. حلقه اصلی ۲۴ ساعته (پایش ۳ دقیقه‌ای اخبار فوری + چرخه ۳۰ دقیقه‌ای) =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید (نسخه قبلی در حال بسته شدن است)...")
    else:
        print(f"Telegram network/update warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    print("🚀 24/7 Accessible News, Breaking Queue, Trend Engine & Digital Store Bot is running...")
    tehran_tz = ZoneInfo("Asia/Tehran")

    await asyncio.sleep(15)

    last_regular_cycle_ts = 0.0
    last_catalog_refresh_ts = 0.0

    # استفاده از یک ClientSession بهینه در هر نوبت کاری
    while True:
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            now_tehran = datetime.now(tehran_tz)

            connector = aiohttp.TCPConnector(limit=25, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as shared_session:
                # ۱. بررسی و انتشار گزارش روزانه (Daily Digest) در ساعت ۰۰:۰۰ تهران
                await publish_daily_digest_if_due()

                # ۲. بروزرسانی کامل کاتالوگ محصولات دیجیتالی سایت در بدو شروع و هر ۲ ساعت یک‌بار
                if (now_ts - last_catalog_refresh_ts) >= 7200:
                    await refresh_digital_products_catalog(shared_session)
                    last_catalog_refresh_ts = now_ts

                # ۳. دریافت فیدهای RSS و خوشه‌بندی معنایی (Semantic Deduplication)
                await fetch_rss_sources(shared_session)

                # ۴. آیا زمان چرخه کامل ۳۰ دقیقه‌ای (۱۸۰۰ ثانیه) رسیده است؟
                if (now_ts - last_regular_cycle_ts) >= REGULAR_CYCLE_SECONDS:
                    print(f"\n--- [چرخه ۳۰ دقیقه‌ای | {now_tehran.strftime('%Y-%m-%d %H:%M')} تهران] ---")
                    await process_and_publish_batch(
                        session=shared_session,
                        breaking_only=False,
                        max_items=MAX_NEWS_PER_CYCLE
                    )
                    await publish_weighted_digital_products(shared_session)
                    last_regular_cycle_ts = now_ts
                else:
                    # در فواصل ۳ دقیقه‌ای بین دو چرخه، اگر خبر فوری (Breaking News) کشف شد، بلافاصله منتشر شود
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

    print("Telegram Bot application started (24/7 Accessible & Breaking Mode)...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
