import asyncio
import sqlite3
import hashlib
import ipaddress
import re
import os
import json
import math
import html
import time
import random
import aiohttp
import httpx
import feedparser
from email.utils import parsedate_to_datetime
from collections import Counter
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus, urlparse, urlunparse, parse_qsl, urlencode
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageReactionHandler, ContextTypes

try:
    from telegram import ReplyParameters
except ImportError:
    ReplyParameters = None

# ================= ۱. تنظیمات اصلی، کلیدها و سهمیه داخلی =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0") or 0)

GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]

CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()

GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "").strip()

TARGET_CHANNEL = '@jazebestore'
CHANNEL_USERNAME_CLEAN = TARGET_CHANNEL.lstrip('@')
STORE_BASE_URL = 'https://jazebestore.com'
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
DB_PATH = 'rss_news_history.db'

# تنظیمات بهینه‌سازی‌شده (کاهش مصرف سهمیه و افزایش دقت)
BREAKING_CHECK_INTERVAL_SECONDS = 180
REGULAR_CYCLE_SECONDS = 1800
MAX_NEWS_PER_CYCLE = 6
MAX_STANDALONE_POSTS_PER_CYCLE = 2
MAX_BREAKING_PER_CYCLE = 1
MAX_CANDIDATES_FOR_AI = 6
ARTICLE_MAX_CHARS = 2400
MAX_HTTP_RESPONSE_BYTES = 2_500_000
MAX_IMAGE_BYTES = 8_000_000
LEASE_TIMEOUT_MINUTES = 15

SEMANTIC_SIMILARITY_THRESHOLD = 0.78
CLUSTER_SIMILARITY_THRESHOLD = 0.72

# سهمیه داخلی سرویس‌های هوش مصنوعی (Token & Quota Controller)
GEMINI_DAILY_INTERNAL_CALL_LIMIT = int(os.environ.get("GEMINI_DAILY_INTERNAL_CALL_LIMIT", "45"))
CLOUDFLARE_DAILY_INTERNAL_CALL_LIMIT = int(os.environ.get("CLOUDFLARE_DAILY_INTERNAL_CALL_LIMIT", "40"))
GROQ_MAX_CONCURRENT_REQUESTS = 1
GROQ_MIN_INTERVAL_SECONDS = 60
GROQ_MAX_INPUT_TOKENS = 4000
GROQ_MAX_OUTPUT_TOKENS = 1200
GROQ_DAILY_INTERNAL_CALL_LIMIT = 15
GROQ_DAILY_INTERNAL_TOKEN_LIMIT = 100000
OPENROUTER_DAILY_INTERNAL_CALL_LIMIT = 5

# مدل‌های رایگان معتبر
GEMINI_MAIN_MODEL = 'gemini-3.8-flash'
GEMINI_LITE_MODEL = 'gemini-3.5-flash-lite'
GEMINI_MODELS = [GEMINI_MAIN_MODEL, GEMINI_LITE_MODEL]
CLOUDFLARE_MODELS = [
    '@cf/meta/llama-3.3-70b-instruct-fp8-fast',
    '@cf/qwen/qwen2.5-72b-instruct'
]
GROQ_VERIFY_MODEL = 'openai/gpt-oss-120b'
GROQ_MODELS = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b']
OPENROUTER_MODELS = ['openrouter/free']

TEHRAN = ZoneInfo("Asia/Tehran")
DAILY_POEM_POST_HOUR = 11
DAILY_POEM_WINDOW_END_HOUR = 24
DAILY_REC_HOUR = 12
DAILY_REC_WINDOW_END_HOUR = 24
POLL_MIN_HYPE = 8
MEME_MAX_PER_CYCLE = 1
MEME_MIN_HYPE = 6
MEME_STANDALONE_GAP_MIN = 90

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REDDIT_UA = {"User-Agent": "jazebe-news-bot/2.0"}
MEME_SUBREDDITS = {
    "gaming", "memes", "pcmasterrace", "playstation", "ps5", "xbox", "nintendo", "nintendoswitch",
    "gamingmemes", "gamingcirclejerk", "dankmemes", "funny", "me_irl", "technology", "technicallythetruth",
    "movies", "television", "music", "bitcoin", "cryptocurrency", "apple", "iphone", "android", "gamephysics",
}

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

IMPORTANT_ENTITIES_KEYWORDS = [
    "gta vi", "gta 6", "rockstar", "ps5 pro", "ps6", "playstation", "xbox",
    "nintendo switch 2", "switch 2", "steam", "valve", "nvidia", "rtx 5090", "rtx 5080",
    "amd", "ryzen", "intel", "apple", "iphone", "openai", "gpt-5", "gemini", "claude",
    "bitcoin", "ethereum", "game pass", "playstation plus", "state of play", "showcase"
]

BREAKING_EVENT_VERBS = [
    "officially announced", "confirmed", "revealed", "launches", "released",
    "release date announced", "official trailer", "delayed", "cancelled", "canceled",
    "acquired", "acquisition", "به‌طور رسمی معرفی شد", "به‌طور رسمی معرفی کرد",
    "تأیید شد", "تأیید کرد", "منتشر شد", "به تعویق افتاد", "لغو شد", "تریلر رسمی"
]

SENSITIVE_CLAIM_KEYWORDS = [
    "price", "$", "dollar", "release date", "delayed", "specs", "teraflops", "gb", "vram",
    "rumor", "leak", "report", "قیمت", "دلار", "تاریخ انتشار", "تأخیر", "شایعه", "مشخصات"
]

OFFICIAL_PUBLISHER_DOMAINS = {
    "blog.playstation.com", "news.xbox.com", "nintendo.com", "rockstargames.com",
    "nvidia.com", "amd.com", "apple.com", "openai.com", "blog.google"
}

TIER1_HIGH_PRIORITY_DOMAINS = {
    "blog.playstation.com", "news.xbox.com", "videogameschronicle.com", "gematsu.com",
    "eurogamer.net", "ign.com", "gamespot.com", "pcgamer.com", "theverge.com",
    "techmeme.com", "tomshardware.com", "reuters.com", "apnews.com", "bbci.co.uk",
    "coindesk.com", "variety.com", "hollywoodreporter.com", "deadline.com"
}

TIER3_LOW_URGENCY_CATEGORIES = {"internet_culture", "music"}

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

# ================= ۲. امنیت شبکه، محافظت SSRF، پاک‌سازی URL و لاگ‌ها =================
os.makedirs('temp_media', exist_ok=True)
bot: Bot | None = None
_groq_semaphore = asyncio.Semaphore(GROQ_MAX_CONCURRENT_REQUESTS)
_last_groq_call_ts = 0.0
_provider_cooldown_until: dict[str, float] = {
    "gemini": 0.0,
    "cloudflare": 0.0,
    "groq": 0.0,
    "openrouter": 0.0
}
_disabled_keys: set[str] = set()

def redact_secrets(text: str) -> str:
    """حذف کامل کلیدهای API و توکن تلگرام از متن خطاها و لاگ‌ها"""
    if not text:
        return ""
    out = str(text)
    all_secrets = [
        TELEGRAM_BOT_TOKEN, OMDB_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN
    ] + GEMINI_API_KEYS + GROQ_API_KEYS + OPENROUTER_API_KEYS
    for secret in all_secrets:
        if secret and len(secret) > 6:
            out = out.replace(secret, "***REDACTED***")
    out = re.sub(r'(AIza[0-9A-Za-z\-_]{20,}|gsk_[0-9A-Za-z]{20,}|sk-or-[0-9A-Za-z\-_]{20,})', '***REDACTED***', out)
    return out

def sanitize_plain_url(url: str | None) -> str:
    if not url:
        return ""
    u = str(url).strip()
    md_match = re.match(r'^\[[^\]]*\]\((https?://[^)]+)\)', u)
    if md_match:
        u = md_match.group(1)
    return u.strip("[]()<> \"'")

def normalize_canonical_url(url: str | None) -> str:
    clean = sanitize_plain_url(url)
    if not clean:
        return ""
    try:
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return clean
        strip_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "fbclid", "gclid", "ref", "source", "ncid", "sr_share"
        }
        filtered_q = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in strip_params]
        norm_netloc = parsed.netloc.lower()
        if norm_netloc.startswith("www."):
            norm_netloc = norm_netloc[4:]
        norm_path = parsed.path.rstrip("/") or "/"
        return urlunparse((parsed.scheme.lower(), norm_netloc, norm_path, "", urlencode(filtered_q), ""))
    except Exception:
        return clean

def extract_publisher_domain(url: str | None) -> str:
    clean = sanitize_plain_url(url)
    if not clean:
        return "unknown"
    try:
        host = (urlparse(clean).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("feeds."):
            host = host[6:]
        return host or "unknown"
    except Exception:
        return "unknown"

def validate_safe_external_url(url: str | None) -> str | None:
    clean = sanitize_plain_url(url)
    if not clean:
        return None
    try:
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https"):
            return None
        host = (parsed.hostname or "").lower().strip()
        if not host or host in ("localhost", "0.0.0.0", "::1") or host.endswith(".local") or host.endswith(".internal"):
            return None
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return None
        except ValueError:
            pass
        return clean
    except Exception:
        return None

async def safe_http_get_text(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict | None = None,
    timeout_sec: int = 12,
    require_html_or_xml: bool = False
) -> tuple[int, str, dict]:
    safe_url = validate_safe_external_url(url)
    if not safe_url:
        return 0, "", {}
    req_headers = dict(UA)
    if headers:
        req_headers.update(headers)
    try:
        async with session.get(
            safe_url,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
            headers=req_headers,
            allow_redirects=True,
            max_redirects=4
        ) as resp:
            final_url = str(resp.url)
            if not validate_safe_external_url(final_url):
                return 0, "", {}
            if resp.status == 304:
                return 304, "", dict(resp.headers)
            if resp.status != 200:
                return resp.status, "", dict(resp.headers)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if require_html_or_xml and not any(x in ctype for x in ("html", "xml", "rss", "atom", "text", "json")):
                return resp.status, "", dict(resp.headers)
            raw_bytes = await resp.content.read(MAX_HTTP_RESPONSE_BYTES)
            text = raw_bytes.decode(resp.charset or "utf-8", errors="ignore")
            return 200, text, dict(resp.headers)
    except Exception:
        return 0, "", {}

# ================= ۳. دیتابیس SQLite با WAL، شاخص‌ها، Outbox و جداول شواهد =================
def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    canonical_url TEXT,
                    title_hash TEXT,
                    category TEXT,
                    source TEXT,
                    publisher_domain TEXT,
                    raw_title TEXT,
                    raw_text TEXT,
                    full_article_text TEXT,
                    image_url TEXT,
                    video_url TEXT,
                    has_video_or_audio INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'discovered',
                    status_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_breaking_candidate INTEGER DEFAULT 0,
                    source_count INTEGER DEFAULT 1,
                    retry_count INTEGER DEFAULT 0,
                    embedding_json TEXT,
                    ai_payload_json TEXT,
                    multiplatform_pack_json TEXT,
                    topic_fingerprint TEXT,
                    published_category TEXT,
                    published_headline TEXT,
                    related_entity TEXT,
                    verification_label TEXT,
                    computed_confidence INTEGER DEFAULT 70,
                    telegram_message_id INTEGER,
                    likes_count INTEGER DEFAULT 0,
                    reaction_count INTEGER DEFAULT 0,
                    source_published_at TIMESTAMP,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP
                )''')

    extra_cols = [
        "canonical_url TEXT", "title_hash TEXT", "publisher_domain TEXT",
        "full_article_text TEXT", "video_url TEXT", "status_updated_at TIMESTAMP",
        "multiplatform_pack_json TEXT", "verification_label TEXT",
        "computed_confidence INTEGER DEFAULT 70", "telegram_message_id INTEGER",
        "likes_count INTEGER DEFAULT 0", "reaction_count INTEGER DEFAULT 0",
        "source_published_at TIMESTAMP", "first_seen_at TIMESTAMP"
    ]
    for col_def in extra_cols:
        try:
            c.execute(f"ALTER TABLE news_items ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass

    c.execute('''CREATE TABLE IF NOT EXISTS source_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_item_id INTEGER NOT NULL,
                    publisher_domain TEXT NOT NULL,
                    feed_url TEXT,
                    article_url TEXT,
                    observed_at TEXT NOT NULL,
                    published_at TEXT,
                    UNIQUE(news_item_id, publisher_domain, article_url),
                    FOREIGN KEY(news_item_id) REFERENCES news_items(id)
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS rss_feed_health (
                    feed_url TEXT PRIMARY KEY,
                    publisher_domain TEXT,
                    tier INTEGER DEFAULT 2,
                    last_success_at TIMESTAMP,
                    last_failure_at TIMESTAMP,
                    consecutive_failures INTEGER DEFAULT 0,
                    average_response_time REAL DEFAULT 0.0,
                    last_http_status INTEGER DEFAULT 0,
                    etag TEXT DEFAULT '',
                    last_modified TEXT DEFAULT '',
                    next_fetch_at TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS fact_evidence_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_item_id INTEGER NOT NULL,
                    publisher_domain TEXT,
                    source_url TEXT,
                    extracted_quotes TEXT,
                    extracted_numbers TEXT,
                    verification_passed INTEGER DEFAULT 1,
                    verification_notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(news_item_id) REFERENCES news_items(id)
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS correction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_item_id INTEGER NOT NULL,
                    telegram_message_id INTEGER,
                    correction_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS publish_outbox (
                    news_item_id INTEGER PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    status TEXT DEFAULT 'sending',
                    telegram_message_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS post_votes (
                    news_item_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (news_item_id, user_id)
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ai_usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_date TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    request_status TEXT NOT NULL,
                    error_type TEXT DEFAULT '',
                    retry_count INTEGER DEFAULT 0,
                    elapsed_ms INTEGER DEFAULT 0,
                    news_batch_id TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS hype_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_name TEXT,
                    category TEXT,
                    score REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS category_engagement (
                    category TEXT PRIMARY KEY,
                    published_posts INTEGER DEFAULT 0,
                    total_likes INTEGER DEFAULT 0
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bot_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )''')

    c.execute("CREATE INDEX IF NOT EXISTS idx_news_status_discovered ON news_items(status, discovered_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_category ON news_items(category);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_entity ON news_items(related_entity);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_canonical ON news_items(canonical_url);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_title_hash ON news_items(title_hash);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_obs_news_id ON source_observations(news_item_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_date ON ai_usage_logs(request_date, provider);")

    conn.commit()
    conn.close()

def get_metadata(key: str, default: str = "") -> str:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM bot_metadata WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_metadata(key: str, value: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_metadata (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def increment_metadata_counter(key: str, delta: int = 1):
    cur = int(get_metadata(key, "0") or 0)
    set_metadata(key, str(cur + delta))

def recover_stale_leases():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE news_items
        SET status = 'pending',
            status_updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('processing', 'selected', 'publishing')
          AND (status_updated_at IS NULL OR status_updated_at <= datetime('now', ?))
          AND id NOT IN (SELECT news_item_id FROM publish_outbox WHERE status = 'sent')
    """, (f"-{LEASE_TIMEOUT_MINUTES} minutes",))
    recovered = c.rowcount
    conn.commit()
    conn.close()
    if recovered > 0:
        print(f"🔄 تعداد {recovered} خبر گیرکرده در وضعیت میانی به صف pending بازگردانده شد.")

def update_news_status(item_ids: list[int], new_status: str, increment_retry: bool = False):
    if not item_ids:
        return
    conn = get_db_connection()
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(item_ids))
    if new_status == 'published':
        c.execute(
            f"UPDATE news_items SET status = ?, status_updated_at = CURRENT_TIMESTAMP, published_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            [new_status] + item_ids
        )
    elif increment_retry:
        c.execute(
            f"UPDATE news_items SET status = ?, status_updated_at = CURRENT_TIMESTAMP, retry_count = retry_count + 1 WHERE id IN ({placeholders})",
            [new_status] + item_ids
        )
    else:
        c.execute(
            f"UPDATE news_items SET status = ?, status_updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            [new_status] + item_ids
        )
    conn.commit()
    conn.close()

def mark_outbox_sending(item_id: int) -> int | None:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT status, telegram_message_id FROM publish_outbox WHERE news_item_id = ?", (item_id,))
    row = c.fetchone()
    if row and row[0] == 'sent' and row[1]:
        conn.close()
        return int(row[1])
    c.execute("""
        INSERT OR REPLACE INTO publish_outbox (news_item_id, idempotency_key, status, updated_at)
        VALUES (?, ?, 'sending', CURRENT_TIMESTAMP)
    """, (item_id, f"item_{item_id}"))
    conn.commit()
    conn.close()
    return None

def mark_outbox_sent(item_id: int, telegram_msg_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO publish_outbox (news_item_id, idempotency_key, status, telegram_message_id, updated_at)
        VALUES (?, ?, 'sent', ?, CURRENT_TIMESTAMP)
    """, (item_id, f"item_{item_id}", telegram_msg_id))
    conn.commit()
    conn.close()

def save_published_news_details(
    item_id: int,
    fingerprint: str,
    pub_cat: str,
    pub_headline: str,
    related_entity: str,
    verification_label: str,
    computed_confidence: int,
    ai_payload: dict,
    multiplatform_pack: dict,
    telegram_msg_id: int = 0
):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE news_items
        SET status = 'published',
            status_updated_at = CURRENT_TIMESTAMP,
            published_at = CURRENT_TIMESTAMP,
            topic_fingerprint = ?,
            published_category = ?,
            published_headline = ?,
            related_entity = ?,
            verification_label = ?,
            computed_confidence = ?,
            ai_payload_json = ?,
            multiplatform_pack_json = ?,
            telegram_message_id = ?
        WHERE id = ?
    """, (
        fingerprint,
        pub_cat,
        pub_headline,
        related_entity,
        verification_label,
        computed_confidence,
        json.dumps(ai_payload, ensure_ascii=False),
        json.dumps(multiplatform_pack, ensure_ascii=False),
        telegram_msg_id or None,
        item_id
    ))
    c.execute("""
        INSERT INTO category_engagement (category, published_posts, total_likes)
        VALUES (?, 1, 0)
        ON CONFLICT(category) DO UPDATE SET published_posts = published_posts + 1
    """, (pub_cat,))
    conn.commit()
    conn.close()

def register_unique_user_vote(item_id: int, user_id: int) -> tuple[bool, int]:
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO post_votes (news_item_id, user_id) VALUES (?, ?)", (item_id, user_id))
    except sqlite3.IntegrityError:
        c.execute("SELECT likes_count FROM news_items WHERE id = ?", (item_id,))
        r = c.fetchone()
        conn.close()
        return False, (r[0] if r and r[0] else 0)

    c.execute("UPDATE news_items SET likes_count = COALESCE(likes_count, 0) + 1 WHERE id = ?", (item_id,))
    c.execute("SELECT published_category, likes_count FROM news_items WHERE id = ?", (item_id,))
    row = c.fetchone()
    new_likes = 1
    if row:
        pub_cat, new_likes = row[0], (row[1] or 1)
        if pub_cat:
            c.execute("""
                INSERT INTO category_engagement (category, published_posts, total_likes)
                VALUES (?, 1, 1)
                ON CONFLICT(category) DO UPDATE SET total_likes = total_likes + 1
            """, (pub_cat,))
    conn.commit()
    conn.close()
    return True, new_likes

def get_category_engagement_weights() -> dict[str, float]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT category, published_posts, total_likes FROM category_engagement")
    rows = c.fetchall()
    conn.close()
    weights = {}
    for cat, posts, likes in rows:
        if posts and posts > 0:
            ratio = likes / posts
            weights[cat] = min(2.0, round(ratio * 1.2, 2))
    return weights

def get_related_channel_archive_links(related_entity: str, exclude_item_id: int, limit: int = 2) -> list[tuple[str, str]]:
    if not related_entity or len(related_entity.strip()) < 3:
        return []
    clean_ent = related_entity.strip().lower()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT published_headline, telegram_message_id
        FROM news_items
        WHERE status = 'published'
          AND lower(related_entity) = ?
          AND id != ?
          AND telegram_message_id IS NOT NULL
          AND published_at >= datetime('now', '-14 days')
        ORDER BY id DESC LIMIT ?
    """, (clean_ent, exclude_item_id, limit))
    rows = c.fetchall()
    conn.close()
    return [(h, f"https://t.me/{CHANNEL_USERNAME_CLEAN}/{mid}") for h, mid in rows if h and mid]

# ================= ۴. زبان فارسی، تاریخ شمسی (چندشنبه) و تطبیق دقیق کلمات کلیدی =================
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_PERSIAN = "\u0600-\u06FF"
JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
GREG_MONTHS_FA = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
                  "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
WEEKDAY_ORDER_FA = {
    "شنبه": "اولین روز هفته",
    "یکشنبه": "دومین روز هفته",
    "دوشنبه": "سومین روز هفته",
    "سه‌شنبه": "چهارمین روز هفته",
    "چهارشنبه": "پنجمین روز هفته",
    "پنج‌شنبه": "ششمین روز هفته",
    "جمعه": "هفتمین روز هفته (تعطیل رسمی)",
}

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
        "weekday_order": WEEKDAY_ORDER_FA.get(weekday, ""),
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

def contains_keyword(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    norm_text = to_en_digits(text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).casefold()
    norm_kw = to_en_digits(keyword.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).casefold()
    if norm_kw.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(norm_kw)}(?![a-z0-9])"
        return re.search(pattern, norm_text) is not None
    pattern_fa = rf"(?<![\w{_PERSIAN}]){re.escape(norm_kw)}(?![\w{_PERSIAN}])"
    return re.search(pattern_fa, norm_text) is not None

# ================= ۵. الگوریتم پایدار حذف تکراری، خوشه‌بندی و امتیازدهی ترکیبی =================
def normalize_title_hash(title: str) -> str:
    clean = re.sub(r'[^\w\s]', '', to_en_digits(title).casefold())
    tokens = [t for t in clean.split() if len(t) > 2]
    return hashlib.blake2b(" ".join(tokens).encode("utf-8"), digest_size=12).hexdigest()

def deterministic_token_hash(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)

def compute_deterministic_ngram_embedding(text: str, dim: int = 256) -> list[float]:
    clean = re.sub(r'[^\w\s]', ' ', to_en_digits(text).casefold())
    tokens = [t for t in clean.split() if len(t) > 2]
    vec = [0.0] * dim
    if not tokens:
        return vec
    counts = Counter(tokens)
    for i in range(len(tokens) - 1):
        counts[f"{tokens[i]}_{tokens[i+1]}"] += 1.5
    for token, weight in counts.items():
        h = deterministic_token_hash(token)
        idx = h % dim
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

def extract_proper_entities(text: str) -> set[str]:
    found = set()
    for ent in IMPORTANT_ENTITIES_KEYWORDS:
        if contains_keyword(text, ent):
            found.add(ent.casefold())
    cap_words = re.findall(r'\b[A-Z][A-Za-z0-9+-]{2,}(?:\s+[A-Z0-9][A-Za-z0-9+-]+)?\b', text or "")
    for cw in cap_words[:8]:
        if cw.lower() not in {"the", "and", "for", "with", "new", "how", "why", "what"}:
            found.add(cw.lower())
    return found

def evaluate_breaking_candidate(title: str, text: str, pub_domain: str, independent_sources: int = 1) -> bool:
    combined = f"{title} {text}"
    has_entity = any(contains_keyword(combined, ent) for ent in IMPORTANT_ENTITIES_KEYWORDS)
    has_verb = any(contains_keyword(combined, verb) for verb in BREAKING_EVENT_VERBS)
    has_authority = (pub_domain in OFFICIAL_PUBLISHER_DOMAINS) or (independent_sources >= 2) or (pub_domain in TIER1_HIGH_PRIORITY_DOMAINS)
    return bool(has_entity and has_verb and has_authority)

def compute_composite_candidate_score(item: dict, cat_weights: dict[str, float]) -> float:
    pub_dom = item.get("publisher_domain") or extract_publisher_domain(item.get("source"))
    if pub_dom in OFFICIAL_PUBLISHER_DOMAINS:
        auth_score = 25.0
    elif pub_dom in TIER1_HIGH_PRIORITY_DOMAINS:
        auth_score = 20.0
    else:
        auth_score = 12.0

    combined_text = f"{item.get('title', '')} {item.get('text', '')}"
    kw_hits = sum(1 for kw in IMPORTANT_ENTITIES_KEYWORDS if contains_keyword(combined_text, kw))
    verb_hits = sum(1 for vb in BREAKING_EVENT_VERBS if contains_keyword(combined_text, vb))
    cat_bonus = cat_weights.get(item.get("category", "general_news"), 0.5) * 2.0
    relevance_score = min(20.0, (kw_hits * 5.0) + (verb_hits * 4.0) + cat_bonus)

    freshness_score = 14.0
    pub_ts_str = item.get("source_published_at")
    if pub_ts_str:
        try:
            pub_dt = datetime.fromisoformat(pub_ts_str.replace("Z", "+00:00"))
            age_hours = max(0.0, (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600.0)
            if age_hours <= 1.0:
                freshness_score = 20.0
            elif age_hours <= 6.0:
                freshness_score = 16.0
            elif age_hours <= 24.0:
                freshness_score = 10.0
            else:
                freshness_score = max(0.0, 6.0 - (age_hours - 24.0) * 0.2)
        except Exception:
            pass

    ind_sources = max(1, int(item.get("source_count", 1)))
    if ind_sources >= 3:
        corroboration_score = 20.0
    elif ind_sources == 2:
        corroboration_score = 14.0
    else:
        corroboration_score = 5.0

    text_len = len(item.get("text", ""))
    has_numbers = bool(re.search(r'\d+', combined_text))
    completeness_score = min(10.0, (min(text_len, 320) / 45.0) + (3.0 if has_numbers else 0.0))

    media_score = 0.0
    if item.get("image_url"):
        media_score += 2.5
    if item.get("has_video_or_audio"):
        media_score += 2.5

    return round(auth_score + relevance_score + freshness_score + corroboration_score + completeness_score + media_score, 2)

def compute_evidence_based_verification(pub_domain: str, independent_sources: int, second_model_verified: bool | None) -> tuple[str, int]:
    if second_model_verified is False:
        return "شایعه یا تأییدنشده", 45
    if pub_domain in OFFICIAL_PUBLISHER_DOMAINS:
        conf = 96 if second_model_verified else 92
        return "خبر رسمی", conf
    if independent_sources >= 2:
        conf = min(94, 80 + (independent_sources * 4))
        return "گزارش تأییدشده از چند منبع", conf
    if pub_domain in TIER1_HIGH_PRIORITY_DOMAINS:
        return "گزارش یک رسانه معتبر", (84 if second_model_verified else 78)
    return "خبر تأییدنشده", 60

async def run_semantic_clustering_and_deduplication():
    while True:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT id, url, canonical_url, title_hash, raw_title, raw_text, source,
                   publisher_domain, is_breaking_candidate, source_published_at
            FROM news_items
            WHERE status = 'discovered'
            ORDER BY id ASC LIMIT 120
        """)
        discovered_rows = c.fetchall()
        if not discovered_rows:
            conn.close()
            break

        c.execute("""
            SELECT id, canonical_url, title_hash, embedding_json, raw_title, publisher_domain
            FROM news_items
            WHERE status IN ('pending', 'published')
              AND discovered_at >= datetime('now', '-72 hours')
            ORDER BY id DESC LIMIT 250
        """)
        existing_rows = c.fetchall()
        conn.close()

        existing_items = []
        for ex_id, ex_can, ex_th, emb_str, ex_title, ex_dom in existing_rows:
            emb = []
            if emb_str:
                try:
                    emb = json.loads(emb_str)
                except Exception:
                    emb = []
            existing_items.append({
                "id": ex_id,
                "canonical_url": ex_can,
                "title_hash": ex_th,
                "emb": emb,
                "entities": extract_proper_entities(ex_title or ""),
                "domain": ex_dom
            })

        discovered_items = []
        for r in discovered_rows:
            row_id, url, can_url, t_hash, r_title, r_text, src, pub_dom, is_brk, src_pub = r
            emb = compute_deterministic_ngram_embedding(f"{r_title} {r_text}")
            discovered_items.append({
                "id": row_id,
                "url": url,
                "canonical_url": can_url or normalize_canonical_url(url),
                "title_hash": t_hash or normalize_title_hash(r_title or ""),
                "title": r_title or "",
                "text": r_text or "",
                "source": src or "",
                "publisher_domain": pub_dom or extract_publisher_domain(url or src),
                "is_breaking": bool(is_brk),
                "source_published_at": src_pub,
                "emb": emb,
                "entities": extract_proper_entities(f"{r_title} {r_text}")
            })

        rejected_ids = []
        new_observations = []
        valid_items = []

        for item in discovered_items:
            matched_existing_id = None
            for ex in existing_items:
                if item["canonical_url"] and item["canonical_url"] == ex["canonical_url"]:
                    matched_existing_id = ex["id"]
                    break
                if item["title_hash"] and item["title_hash"] == ex["title_hash"]:
                    matched_existing_id = ex["id"]
                    break
                if ex["emb"] and len(ex["emb"]) == len(item["emb"]):
                    sim = cosine_similarity(item["emb"], ex["emb"])
                    if sim >= SEMANTIC_SIMILARITY_THRESHOLD:
                        matched_existing_id = ex["id"]
                        break
                    if sim >= 0.62 and item["entities"] and len(item["entities"] & ex["entities"]) >= 2:
                        matched_existing_id = ex["id"]
                        break
            if matched_existing_id:
                rejected_ids.append(item["id"])
                new_observations.append((
                    matched_existing_id,
                    item["publisher_domain"],
                    item["source"],
                    item["url"],
                    item["source_published_at"] or datetime.now(timezone.utc).isoformat()
                ))
            else:
                valid_items.append(item)

        clusters: list[list[dict]] = []
        for item in valid_items:
            placed = False
            for cluster in clusters:
                rep = cluster[0]
                sim = cosine_similarity(item["emb"], rep["emb"])
                ent_overlap = len(item["entities"] & rep["entities"]) >= 2 if (item["entities"] and rep["entities"]) else False
                if item["title_hash"] == rep["title_hash"] or sim >= CLUSTER_SIMILARITY_THRESHOLD or (sim >= 0.58 and ent_overlap):
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])

        def _rep_rank(cand: dict) -> float:
            dom = cand["publisher_domain"]
            r_score = 30.0 if dom in OFFICIAL_PUBLISHER_DOMAINS else (20.0 if dom in TIER1_HIGH_PRIORITY_DOMAINS else 10.0)
            r_score += min(15.0, len(cand["text"]) / 25.0)
            return r_score

        conn = get_db_connection()
        c = conn.cursor()
        if rejected_ids:
            placeholders = ",".join(["?"] * len(rejected_ids))
            c.execute(f"UPDATE news_items SET status = 'rejected', status_updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})", rejected_ids)

        now_iso = datetime.now(timezone.utc).isoformat()
        for ex_id, dom, f_url, a_url, pub_at in new_observations:
            c.execute("""
                INSERT OR IGNORE INTO source_observations (news_item_id, publisher_domain, feed_url, article_url, observed_at, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ex_id, dom, f_url, a_url, now_iso, pub_at))
            c.execute("""
                UPDATE news_items
                SET source_count = (SELECT COUNT(DISTINCT publisher_domain) FROM source_observations WHERE news_item_id = ?)
                WHERE id = ?
            """, (ex_id, ex_id))

        for cluster in clusters:
            cluster.sort(key=_rep_rank, reverse=True)
            primary = cluster[0]
            for member in cluster:
                c.execute("""
                    INSERT OR IGNORE INTO source_observations (news_item_id, publisher_domain, feed_url, article_url, observed_at, published_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (primary["id"], member["publisher_domain"], member["source"], member["url"], now_iso, member["source_published_at"] or now_iso))

            c.execute("SELECT COUNT(DISTINCT publisher_domain) FROM source_observations WHERE news_item_id = ?", (primary["id"],))
            ind_cnt_row = c.fetchone()
            ind_sources = max(1, (ind_cnt_row[0] if ind_cnt_row else 1))

            is_brk = 1 if evaluate_breaking_candidate(primary["title"], primary["text"], primary["publisher_domain"], ind_sources) else 0
            c.execute("""
                UPDATE news_items
                SET status = 'pending',
                    status_updated_at = CURRENT_TIMESTAMP,
                    source_count = ?,
                    is_breaking_candidate = ?,
                    embedding_json = ?,
                    canonical_url = ?,
                    title_hash = ?,
                    publisher_domain = ?
                WHERE id = ?
            """, (
                ind_sources,
                is_brk,
                json.dumps(primary["emb"]),
                primary["canonical_url"],
                primary["title_hash"],
                primary["publisher_domain"],
                primary["id"]
            ))
            for extra in cluster[1:]:
                c.execute("UPDATE news_items SET status = 'rejected', status_updated_at = CURRENT_TIMESTAMP WHERE id = ?", (extra["id"],))

        conn.commit()
        conn.close()

# ================= ۶. الگوریتم هایپ زمان‌دار و شناسایی ترند ۲۴ ساعته =================
def record_hype_event(entity_name: str, category: str, score: float):
    if not entity_name or len(entity_name.strip()) < 2:
        return
    clean_name = entity_name.strip().lower()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO hype_events (entity_name, category, score, created_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (clean_name, category, float(max(1.0, min(score, 10.0)))))
    c.execute("DELETE FROM hype_events WHERE created_at < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

def detect_24h_trends(top_n: int = 8) -> list[dict]:
    conn = get_db_connection()
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

# ================= ۷. جمع‌آوری RSS سه سطحی با کش ETag / Last-Modified و سلامت فید =================
def clean_raw_text(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+|www\S+|https\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def get_feed_tier_and_interval(category: str, url: str) -> tuple[int, int]:
    dom = extract_publisher_domain(url)
    if dom in OFFICIAL_PUBLISHER_DOMAINS or dom in TIER1_HIGH_PRIORITY_DOMAINS:
        return 1, 180
    if category in TIER3_LOW_URGENCY_CATEGORIES:
        return 3, 3600
    return 2, 900

def parse_entry_published_iso(entry) -> str | None:
    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    for attr_p in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr_p, None)
        if st:
            try:
                dt = datetime(*st[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return None

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
    return validate_safe_external_url(img_url) if img_url else None, has_av

async def fetch_single_feed(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    category: str,
    url: str,
    etag: str,
    last_mod: str,
    tier: int,
    base_interval: int
) -> tuple[str, int, float, str, str, list[dict]]:
    clean_feed_url = validate_safe_external_url(url)
    if not clean_feed_url:
        return url, 0, 0.0, etag, last_mod, []
    cond_headers = {}
    if etag:
        cond_headers["If-None-Match"] = etag
    if last_mod:
        cond_headers["If-Modified-Since"] = last_mod

    async with sem:
        t0 = time.monotonic()
        status, xml_data, resp_headers = await safe_http_get_text(
            session, clean_feed_url, headers=cond_headers, timeout_sec=12, require_html_or_xml=True
        )
        elapsed = round(time.monotonic() - t0, 3)
        if status == 304:
            return clean_feed_url, 304, elapsed, etag, last_mod, []
        if status != 200 or not xml_data:
            return clean_feed_url, status, elapsed, etag, last_mod, []

        new_etag = resp_headers.get("ETag", etag) or ""
        new_last_mod = resp_headers.get("Last-Modified", last_mod) or ""

        feed = await asyncio.to_thread(feedparser.parse, xml_data)
        extracted = []
        now_utc = datetime.now(timezone.utc)

        for entry in feed.entries[:4]:
            link = validate_safe_external_url(getattr(entry, 'link', None))
            if not link:
                continue
            pub_iso = parse_entry_published_iso(entry)
            if pub_iso:
                try:
                    pub_dt = datetime.fromisoformat(pub_iso)
                    if (now_utc - pub_dt).total_seconds() > 48 * 3600:
                        continue
                except Exception:
                    pass

            title = clean_raw_text(getattr(entry, 'title', ''))
            summary = clean_raw_text(getattr(entry, 'summary', ''))
            cleaned_body = f"{title}\n{summary}".strip()
            if len(cleaned_body) < 45:
                continue

            img_url, has_av = extract_rss_media_info(entry)
            pub_dom = extract_publisher_domain(link)
            is_breaking = evaluate_breaking_candidate(title, cleaned_body, pub_dom, 1)

            extracted.append({
                'category': category,
                'source': clean_feed_url,
                'publisher_domain': pub_dom,
                'link': link,
                'canonical_url': normalize_canonical_url(link),
                'title_hash': normalize_title_hash(title),
                'raw_title': title[:250],
                'raw_text': cleaned_body[:380],
                'image_url': img_url,
                'has_video_or_audio': 1 if has_av else 0,
                'is_breaking_candidate': 1 if is_breaking else 0,
                'source_published_at': pub_iso or now_utc.isoformat()
            })
        return clean_feed_url, 200, elapsed, new_etag, new_last_mod, extracted

async def fetch_rss_sources(session: aiohttp.ClientSession):
    now_utc = datetime.now(timezone.utc)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT feed_url, etag, last_modified, consecutive_failures, average_response_time, next_fetch_at FROM rss_feed_health")
    health_map = {r[0]: r[1:] for r in c.fetchall()}
    conn.close()

    due_tasks = []
    sem = asyncio.Semaphore(16)

    for category, urls in CATEGORIZED_RSS_SOURCES.items():
        for raw_url in urls:
            clean_u = sanitize_plain_url(raw_url)
            tier, base_interval = get_feed_tier_and_interval(category, clean_u)
            h_info = health_map.get(clean_u)
            etag, last_mod = "", ""
            if h_info:
                etag, last_mod, _, _, next_fetch_str = h_info
                if next_fetch_str:
                    try:
                        next_dt = datetime.fromisoformat(next_fetch_str)
                        if now_utc < next_dt:
                            continue
                    except Exception:
                        pass
            due_tasks.append((
                clean_u,
                tier,
                base_interval,
                fetch_single_feed(session, sem, category, clean_u, etag or "", last_mod or "", tier, base_interval)
            ))

    if not due_tasks:
        await run_semantic_clustering_and_deduplication()
        return

    results = await asyncio.gather(*(t[3] for t in due_tasks), return_exceptions=True)

    conn = get_db_connection()
    c = conn.cursor()
    now_iso = now_utc.isoformat()

    for (feed_u, tier, base_interval, _), res in zip(due_tasks, results):
        dom = extract_publisher_domain(feed_u)
        prev = health_map.get(feed_u)
        prev_fails = prev[2] if prev else 0
        prev_avg = prev[3] if prev else 0.0

        if isinstance(res, Exception) or res[1] == 0:
            new_fails = prev_fails + 1
            backoff_mult = min(8, 2 ** max(0, new_fails - 2)) if new_fails >= 3 else 1
            next_dt = (now_utc + timedelta(seconds=base_interval * backoff_mult)).isoformat()
            c.execute("""
                INSERT INTO rss_feed_health (feed_url, publisher_domain, tier, last_failure_at, consecutive_failures, last_http_status, next_fetch_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    last_failure_at = excluded.last_failure_at,
                    consecutive_failures = excluded.consecutive_failures,
                    last_http_status = 0,
                    next_fetch_at = excluded.next_fetch_at
            """, (feed_u, dom, tier, now_iso, new_fails, next_dt))
            continue

        _, http_status, elapsed, new_etag, new_last_mod, feed_items = res
        if http_status in (200, 304):
            avg_rt = round((prev_avg * 0.7 + elapsed * 0.3) if prev_avg > 0 else elapsed, 3)
            next_dt = (now_utc + timedelta(seconds=base_interval)).isoformat()
            c.execute("""
                INSERT INTO rss_feed_health (feed_url, publisher_domain, tier, last_success_at, consecutive_failures, average_response_time, last_http_status, etag, last_modified, next_fetch_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    last_success_at = excluded.last_success_at,
                    consecutive_failures = 0,
                    average_response_time = excluded.average_response_time,
                    last_http_status = excluded.last_http_status,
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    next_fetch_at = excluded.next_fetch_at
            """, (feed_u, dom, tier, now_iso, avg_rt, http_status, new_etag, new_last_mod, next_dt))

            for item in feed_items:
                c.execute("SELECT id FROM news_items WHERE url = ? OR canonical_url = ?", (item['link'], item['canonical_url']))
                existing_row = c.fetchone()
                if existing_row is None:
                    c.execute("""
                        INSERT INTO news_items
                        (url, canonical_url, title_hash, category, source, publisher_domain, raw_title, raw_text,
                         image_url, has_video_or_audio, status, status_updated_at, is_breaking_candidate,
                         source_published_at, first_seen_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        item['link'], item['canonical_url'], item['title_hash'], item['category'],
                        item['source'], item['publisher_domain'], item['raw_title'], item['raw_text'],
                        item['image_url'], item['has_video_or_audio'], item['is_breaking_candidate'],
                        item['source_published_at']
                    ))
                else:
                    ex_id = existing_row[0]
                    c.execute("""
                        INSERT OR IGNORE INTO source_observations (news_item_id, publisher_domain, feed_url, article_url, observed_at, published_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (ex_id, item['publisher_domain'], item['source'], item['link'], now_iso, item['source_published_at']))
        else:
            new_fails = prev_fails + 1
            backoff_mult = min(8, 2 ** max(0, new_fails - 2)) if new_fails >= 3 else 1
            next_dt = (now_utc + timedelta(seconds=base_interval * backoff_mult)).isoformat()
            c.execute("""
                INSERT INTO rss_feed_health (feed_url, publisher_domain, tier, last_failure_at, consecutive_failures, last_http_status, next_fetch_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    last_failure_at = excluded.last_failure_at,
                    consecutive_failures = excluded.consecutive_failures,
                    last_http_status = excluded.last_http_status,
                    next_fetch_at = excluded.next_fetch_at
            """, (feed_u, dom, tier, now_iso, new_fails, http_status, next_dt))

    conn.commit()
    conn.close()
    await run_semantic_clustering_and_deduplication()

# ================= ۸. جمع‌آوری شواهد مقاله پیش از فراخوانی هوش مصنوعی =================
_NOISE = re.compile(r"cookie|subscribe|newsletter|sign up|all rights reserved|advertisement", re.I)

def _youtube_watch_url(url: str) -> str:
    m = re.search(r"youtube\.com/embed/([\w-]{6,})", url)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else url

def extract_evidence_from_text(text: str) -> tuple[list[str], list[str]]:
    if not text:
        return [], []
    quotes = [q.strip() for q in re.findall(r'"([^"]{20,180})"', text)[:4]]
    numbers = list(dict.fromkeys(re.findall(r'(?:\$\d+(?:[.,]\d+)?(?:\s*(?:million|billion|M|B))?|\b\d{4}\b|\b\d+(?:\.\d+)?%\b|\b\d{1,3}(?:,\d{3})+\b)', text)))[:8]
    return quotes, numbers

async def fetch_article_evidence_for_candidates(session: aiohttp.ClientSession, candidates: list[dict]):
    sem = asyncio.Semaphore(4)

    async def _fetch_one(cand: dict):
        async with sem:
            status, page, _ = await safe_http_get_text(session, cand["link"], timeout_sec=12, require_html_or_xml=True)
            if status != 200 or not page:
                return cand["id"], "", ""
            soup = BeautifulSoup(page, "html.parser")
            video = ""
            for prop in ("og:video:url", "og:video", "og:video:secure_url"):
                tag = soup.find("meta", property=prop)
                if tag and str(tag.get("content", "")).startswith("http"):
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
            paras = [p for p in paras if len(p) > 45 and not _NOISE.search(p)]
            body = " ".join(paras)[:ARTICLE_MAX_CHARS]
            safe_vid = validate_safe_external_url(_youtube_watch_url(video)) if video else ""
            return cand["id"], body, (safe_vid or "")

    results = await asyncio.gather(*(_fetch_one(c) for c in candidates), return_exceptions=True)
    by_id = {r[0]: (r[1], r[2]) for r in results if isinstance(r, tuple)}

    conn = get_db_connection()
    c = conn.cursor()
    for cand in candidates:
        body, video = by_id.get(cand["id"], ("", ""))
        cand["full_article_excerpt"] = body
        if video:
            cand["video_url"] = video
        combined_ev = f"{cand['text']} {body}".strip()
        quotes, nums = extract_evidence_from_text(combined_ev)
        cand["extracted_quotes"] = quotes
        cand["extracted_numbers"] = nums
        c.execute("UPDATE news_items SET full_article_text = ?, video_url = ? WHERE id = ?", (body, video, cand["id"]))
        c.execute("""
            INSERT INTO fact_evidence_ledger (news_item_id, publisher_domain, source_url, extracted_quotes, extracted_numbers)
            VALUES (?, ?, ?, ?, ?)
        """, (
            cand["id"],
            cand["publisher_domain"],
            cand["link"],
            json.dumps(quotes, ensure_ascii=False),
            json.dumps(nums, ensure_ascii=False)
        ))
    conn.commit()
    conn.close()

# ================= ۹. ساختارهای داده، کنترلر سهمیه و موتور هوش مصنوعی (با Cloudflare) =================
class MultiPlatformPack(BaseModel):
    instagram_carousel_slides: list[str] = Field(default_factory=list, description="3 to 5 concise Persian slides for Instagram Carousel")
    short_video_script_persian: str = Field(default="", description="25-second punchy Persian script (Hook + Body + CTA) for YouTube Shorts / TikTok / Reels")
    story_hook_persian: str = Field(default="", description="1-line engaging Persian hook for Telegram/Instagram Story")

class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="ID of the selected news candidate")
    category_id: str = Field(description="One of: gaming, technology, hardware, crypto, film_tv, internet_culture, music, general_news")
    is_breaking: bool = Field(default=False, description="True ONLY if major official event")
    series_name: str = Field(default="", description="Optional: 'Game of the Week', 'Movie of the Week', 'Tech Breakdown', 'Weekly Gaming News', 'Best Hardware Deals', 'This Week in Gaming', or ''")
    headline_persian: str = Field(description="Accurate Persian headline without emojis/HTML")
    summary_persian: str = Field(description="3-5 factual Persian sentences strictly grounded in the provided evidence; wrap 1-3 key facts in <b>...</b>")
    key_points_persian: list[str] = Field(description="2 to 4 factual bullet points in Persian")
    background_persian: str = Field(default="", description="1-2 sentence Persian context strictly from the source text, else ''")
    before_after_persian: str = Field(default="", description="'قبل: ... | اکنون: ...' if news involves a delay, price change, or spec upgrade, else ''")
    poll_question: str = Field(default="", description="Engaging Persian poll question if hype_score >= 8, else ''")
    poll_options: list[str] = Field(default_factory=list, description="2 to 3 short Persian poll options if poll_question is provided")
    topic_hashtags: list[str] = Field(description="2 to 3 specific Persian hashtags starting with #")
    topic_fingerprint: str = Field(description="1-sentence English summary for deduplication")
    related_game: str = Field(default="", description="Canonical English title of the game/product/company, else ''")
    hype_score: int = Field(default=5, description="Hype score from 1 to 10")
    multiplatform: MultiPlatformPack = Field(default_factory=MultiPlatformPack, description="Multi-platform content pack for top standalone stories")

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

GROQ_VERIFICATION_STRICT_SCHEMA = {
    "name": "claim_verification_result",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "is_supported": {"type": "boolean"},
            "has_contradiction": {"type": "boolean"},
            "corrected_summary_persian": {"type": "string"},
            "verification_notes": {"type": "string"}
        },
        "required": ["is_supported", "has_contradiction", "corrected_summary_persian", "verification_notes"],
        "additionalProperties": False
    }
}

def get_today_ai_usage(provider: str) -> tuple[int, int]:
    today_str = get_current_tehran_time().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*), COALESCE(SUM(total_tokens), 0)
        FROM ai_usage_logs
        WHERE request_date = ? AND provider = ?
    """, (today_str, provider))
    row = c.fetchone()
    conn.close()
    return (row[0] or 0), (row[1] or 0)

def can_use_provider(provider: str) -> tuple[bool, str]:
    now_ts = time.time()
    if now_ts < _provider_cooldown_until.get(provider, 0.0):
        rem = int(_provider_cooldown_until[provider] - now_ts)
        return False, f"در وضعیت استراحت (Cooldown) تا {rem} ثانیه دیگر"

    calls, tokens = get_today_ai_usage(provider)
    if provider == "gemini":
        if not GEMINI_API_KEYS:
            return False, "بدون کلید"
        if calls >= GEMINI_DAILY_INTERNAL_CALL_LIMIT:
            return False, f"سقف روزانه داخلی ({GEMINI_DAILY_INTERNAL_CALL_LIMIT} درخواست) پر شده"
    elif provider == "cloudflare":
        if not (CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN):
            return False, "بدون کلید"
        if CLOUDFLARE_API_TOKEN in _disabled_keys:
            return False, "توکن غیرفعال شده"
        if calls >= CLOUDFLARE_DAILY_INTERNAL_CALL_LIMIT:
            return False, f"سقف روزانه داخلی Cloudflare ({CLOUDFLARE_DAILY_INTERNAL_CALL_LIMIT} درخواست) پر شده"
    elif provider == "groq":
        if not GROQ_API_KEYS:
            return False, "بدون کلید"
        if calls >= GROQ_DAILY_INTERNAL_CALL_LIMIT or tokens >= GROQ_DAILY_INTERNAL_TOKEN_LIMIT:
            return False, f"سقف روزانه داخلی Groq ({calls}/{GROQ_DAILY_INTERNAL_CALL_LIMIT} درخواست | {tokens} توکن) پر شده"
    elif provider == "openrouter":
        if not OPENROUTER_API_KEYS:
            return False, "بدون کلید"
        if calls >= OPENROUTER_DAILY_INTERNAL_CALL_LIMIT:
            return False, f"سقف اضطراری روزانه OpenRouter ({OPENROUTER_DAILY_INTERNAL_CALL_LIMIT}) پر شده"
    return True, "آماده"

def log_ai_request_usage(
    provider: str,
    model: str,
    in_tok: int,
    out_tok: int,
    status: str,
    error_type: str = "",
    retry_cnt: int = 0,
    elapsed_ms: int = 0,
    batch_id: str = ""
):
    today_str = get_current_tehran_time().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ai_usage_logs
        (provider, model, request_date, input_tokens, output_tokens, total_tokens,
         request_status, error_type, retry_count, elapsed_ms, news_batch_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        provider, model, today_str, int(in_tok), int(out_tok), int(in_tok + out_tok),
        status, redact_secrets(error_type)[:80], int(retry_cnt), int(elapsed_ms), batch_id
    ))
    conn.commit()
    conn.close()
    ts = get_current_tehran_time().strftime("%H:%M")
    if status == "success":
        set_metadata(f"api_health_{provider}", f"✅ سالم ({model.split('/')[-1]} | {ts})")
    else:
        set_metadata(f"api_health_{provider}", f"⚠️ {redact_secrets(error_type)[:35]} ({ts})")
        set_metadata("last_api_error", f"{provider}/{model.split('/')[-1]}: {redact_secrets(error_type)[:60]} ({ts})")

def _extract_json_from_llm_content(raw_content: str | None) -> dict:
    if not raw_content or not isinstance(raw_content, str):
        raise ValueError("Empty content returned from LLM")
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)

def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(35.0, connect=15.0),
        http2=False,
        follow_redirects=True
    )

async def call_gemini_editorial(prompt: str, schema_cls, model_prefer: str = GEMINI_MAIN_MODEL, batch_id: str = ""):
    ok, reason = can_use_provider("gemini")
    if not ok:
        print(f"ℹ️ عبور از Gemini: {reason}")
        return None

    active_keys = [k for k in GEMINI_API_KEYS if k not in _disabled_keys]
    if not active_keys:
        return None

    models_order = [model_prefer] + [m for m in GEMINI_MODELS if m != model_prefer]
    api_key = active_keys[0]
    client = genai.Client(api_key=api_key)

    for model_name in models_order:
        for retry in range(2):
            t0 = time.monotonic()
            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema_cls,
                        temperature=0.2
                    )
                )
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                um = getattr(resp, "usage_metadata", None)
                in_t = int(getattr(um, "prompt_token_count", 0) or 0)
                out_t = int(getattr(um, "candidates_token_count", 0) or 0)
                raw_dict = _extract_json_from_llm_content(resp.text)
                validated = schema_cls.model_validate(raw_dict)
                log_ai_request_usage("gemini", model_name, in_t, out_t, "success", retry_cnt=retry, elapsed_ms=elapsed_ms, batch_id=batch_id)
                return validated
            except (ValidationError, json.JSONDecodeError, ValueError) as ve:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                log_ai_request_usage("gemini", model_name, 0, 0, "error", f"SchemaError: {ve}", retry_cnt=retry, elapsed_ms=elapsed_ms, batch_id=batch_id)
                break
            except Exception as e:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                err_str = redact_secrets(str(e))
                log_ai_request_usage("gemini", model_name, 0, 0, "error", err_str, retry_cnt=retry, elapsed_ms=elapsed_ms, batch_id=batch_id)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    _provider_cooldown_until["gemini"] = time.time() + 900
                    print("⚠️ سهمیه Gemini به سقف رسیده است (Cooldown به مدت ۱۵ دقیقه).")
                    return None
                if "401" in err_str or "403" in err_str or "API_KEY_INVALID" in err_str:
                    _disabled_keys.add(api_key)
                    return None
                if "400" in err_str:
                    return None
                if retry == 0:
                    await asyncio.sleep(2.5)
                else:
                    break
    return None

async def call_cloudflare_workers_ai(prompt: str, schema_cls, batch_id: str = ""):
    """فراخوانی سرویس Cloudflare Workers AI از طریق آدرس استاندارد OpenAI-Compatible"""
    ok, reason = can_use_provider("cloudflare")
    if not ok:
        if reason != "بدون کلید":
            print(f"ℹ️ عبور از Cloudflare: {reason}")
        return None

    cf_base_url = f"[https://api.cloudflare.com/client/v4/accounts/](https://api.cloudflare.com/client/v4/accounts/){CLOUDFLARE_ACCOUNT_ID}/ai/v1"
    schema_json = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
    sys_instruction = (
        "You are a Chief Editor JSON API. Respond ONLY with one valid JSON object (no markdown fences, no commentary) "
        f"matching this JSON schema:\n{schema_json}"
    )

    async with _build_http_client() as http_client:
        cf_client = AsyncOpenAI(
            api_key=CLOUDFLARE_API_TOKEN,
            base_url=cf_base_url,
            http_client=http_client,
            max_retries=0
        )
        for model_name in CLOUDFLARE_MODELS:
            t0 = time.monotonic()
            try:
                comp = await cf_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": sys_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    max_tokens=2000
                )
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                in_t = int(getattr(comp.usage, "prompt_tokens", 0) or 0) if comp.usage else 0
                out_t = int(getattr(comp.usage, "completion_tokens", 0) or 0) if comp.usage else 0
                content = comp.choices[0].message.content if comp.choices else None
                raw_dict = _extract_json_from_llm_content(content)
                validated = schema_cls.model_validate(raw_dict)
                log_ai_request_usage("cloudflare", model_name, in_t, out_t, "success", elapsed_ms=elapsed_ms, batch_id=batch_id)
                print(f"✅ موفقیت با Cloudflare Workers AI ({model_name.split('/')[-1]})")
                return validated
            except Exception as e:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                err_str = redact_secrets(str(e))
                log_ai_request_usage("cloudflare", model_name, 0, 0, "error", err_str, elapsed_ms=elapsed_ms, batch_id=batch_id)
                if "429" in err_str:
                    _provider_cooldown_until["cloudflare"] = time.time() + 900
                    return None
                if "401" in err_str or "403" in err_str or "Authentication" in err_str:
                    _disabled_keys.add(CLOUDFLARE_API_TOKEN)
                    return None
                continue
    return None

async def call_groq_editorial_or_verify(prompt: str, schema_cls=None, strict_schema: dict | None = None, batch_id: str = ""):
    global _last_groq_call_ts
    ok, reason = can_use_provider("groq")
    if not ok:
        print(f"ℹ️ عبور از Groq: {reason}")
        return None

    active_keys = [k for k in GROQ_API_KEYS if k not in _disabled_keys]
    if not active_keys:
        return None

    async with _groq_semaphore:
        wait_needed = GROQ_MIN_INTERVAL_SECONDS - (time.time() - _last_groq_call_ts)
        if 0 < wait_needed <= 15:
            await asyncio.sleep(wait_needed)

        api_key = active_keys[0]
        async with _build_http_client() as http_client:
            groq_client = AsyncOpenAI(
                api_key=api_key,
                base_url="[https://api.groq.com/openai/v1](https://api.groq.com/openai/v1)",
                http_client=http_client,
                max_retries=0
            )
            for model_name in GROQ_MODELS[:2]:
                t0 = time.monotonic()
                try:
                    _last_groq_call_ts = time.time()
                    if strict_schema and model_name in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
                        resp_format = {"type": "json_schema", "json_schema": strict_schema}
                        sys_instruction = "You are an Evidence Verification Engine. Output valid JSON matching the strict schema."
                    else:
                        schema_json = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False) if schema_cls else "{}"
                        resp_format = {"type": "json_object"}
                        sys_instruction = f"You are a Chief Editor JSON API. Respond ONLY with valid JSON matching this schema:\n{schema_json}"

                    comp = await groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": sys_instruction},
                            {"role": "user", "content": prompt[:GROQ_MAX_INPUT_TOKENS * 3]}
                        ],
                        response_format=resp_format,
                        max_tokens=GROQ_MAX_OUTPUT_TOKENS,
                        temperature=0.2
                    )
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    in_t = int(getattr(comp.usage, "prompt_tokens", 0) or 0) if comp.usage else 0
                    out_t = int(getattr(comp.usage, "completion_tokens", 0) or 0) if comp.usage else 0
                    content = comp.choices[0].message.content if comp.choices else None
                    raw_dict = _extract_json_from_llm_content(content)
                    log_ai_request_usage("groq", model_name, in_t, out_t, "success", elapsed_ms=elapsed_ms, batch_id=batch_id)
                    return schema_cls.model_validate(raw_dict) if schema_cls else raw_dict
                except Exception as e:
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    err_str = redact_secrets(str(e))
                    log_ai_request_usage("groq", model_name, 0, 0, "error", err_str, elapsed_ms=elapsed_ms, batch_id=batch_id)
                    if "429" in err_str:
                        _provider_cooldown_until["groq"] = time.time() + 600
                        return None
                    if "401" in err_str or "403" in err_str:
                        _disabled_keys.add(api_key)
                        return None
                    continue
    return None

async def call_openrouter_emergency(prompt: str, schema_cls, batch_id: str = ""):
    ok, reason = can_use_provider("openrouter")
    if not ok:
        return None
    active_keys = [k for k in OPENROUTER_API_KEYS if k not in _disabled_keys]
    if not active_keys:
        return None

    api_key = active_keys[0]
    model_name = OPENROUTER_MODELS[0]
    schema_json = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
    async with _build_http_client() as http_client:
        or_client = AsyncOpenAI(
            api_key=api_key,
            base_url="[https://openrouter.ai/api/v1](https://openrouter.ai/api/v1)",
            http_client=http_client,
            max_retries=0
        )
        t0 = time.monotonic()
        try:
            comp = await or_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": f"Respond ONLY with valid JSON matching this schema:\n{schema_json}"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.25
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            in_t = int(getattr(comp.usage, "prompt_tokens", 0) or 0) if comp.usage else 0
            out_t = int(getattr(comp.usage, "completion_tokens", 0) or 0) if comp.usage else 0
            content = comp.choices[0].message.content if comp.choices else None
            raw_dict = _extract_json_from_llm_content(content)
            validated = schema_cls.model_validate(raw_dict)
            log_ai_request_usage("openrouter", model_name, in_t, out_t, "success", elapsed_ms=elapsed_ms, batch_id=batch_id)
            return validated
        except Exception as e:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            err_str = redact_secrets(str(e))
            log_ai_request_usage("openrouter", model_name, 0, 0, "error", err_str, elapsed_ms=elapsed_ms, batch_id=batch_id)
            if "429" in err_str:
                _provider_cooldown_until["openrouter"] = time.time() + 1800
            return None

async def generate_editorial_batch(prompt: str, batch_id: str = "") -> BatchProcessResult | None:
    """ترتیب پیشنهادی: ۱. Gemini 3.8 Flash -> ۲. Cloudflare Workers AI -> ۳. Groq -> ۴. OpenRouter اضطراری"""
    res = await call_gemini_editorial(prompt, BatchProcessResult, model_prefer=GEMINI_MAIN_MODEL, batch_id=batch_id)
    if res and res.selected_news:
        return res
    res = await call_cloudflare_workers_ai(prompt, BatchProcessResult, batch_id=batch_id)
    if res and res.selected_news:
        return res
    res = await call_groq_editorial_or_verify(prompt, schema_cls=BatchProcessResult, batch_id=batch_id)
    if res and res.selected_news:
        return res
    res = await call_openrouter_emergency(prompt, BatchProcessResult, batch_id=batch_id)
    if res and res.selected_news:
        return res
    return None

async def verify_sensitive_story_with_groq(sel: SelectedNewsItem, orig_item: dict, batch_id: str = "") -> tuple[bool | None, str]:
    combined_src = f"{orig_item.get('title', '')} {orig_item.get('text', '')} {orig_item.get('full_article_excerpt', '')}"
    is_sensitive = sel.is_breaking or any(contains_keyword(combined_src, kw) for kw in SENSITIVE_CLAIM_KEYWORDS)
    if not is_sensitive:
        return None, ""

    ok, _ = can_use_provider("groq")
    if not ok:
        return None, ""

    verify_prompt = f"""
Verify the following Persian news draft against the English source evidence.
Check every number, date, price, platform, and official claim.
If the Persian draft invents facts or contradicts the evidence, set is_supported=false, has_contradiction=true, and provide a corrected Persian summary in corrected_summary_persian that only states verified facts from the evidence.

Source Evidence:
- Publisher: {orig_item.get('publisher_domain')} (Independent sources count: {orig_item.get('source_count')})
- Title: {orig_item.get('title')}
- Text & Excerpt: {combined_src[:2000]}
- Extracted Numbers: {json.dumps(orig_item.get('extracted_numbers', []))}

Persian Draft:
- Headline: {sel.headline_persian}
- Summary: {sel.summary_persian}
- Key Points: {json.dumps(sel.key_points_persian, ensure_ascii=False)}
"""
    ver_res = await call_groq_editorial_or_verify(
        verify_prompt, schema_cls=None, strict_schema=GROQ_VERIFICATION_STRICT_SCHEMA, batch_id=f"verify_{batch_id}"
    )
    if not isinstance(ver_res, dict):
        return None, ""

    is_sup = bool(ver_res.get("is_supported", True))
    has_contra = bool(ver_res.get("has_contradiction", False))
    notes = str(ver_res.get("verification_notes", ""))
    corrected = str(ver_res.get("corrected_summary_persian", "")).strip()

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE fact_evidence_ledger
        SET verification_passed = ?, verification_notes = ?
        WHERE news_item_id = ?
    """, (1 if (is_sup and not has_contra) else 0, notes[:300], orig_item["id"]))
    conn.commit()
    conn.close()

    if has_contra and len(corrected) >= 45:
        sel.summary_persian = persian_polish(corrected)
        return True, notes
    return (is_sup and not has_contra), notes

async def ask_lightweight_ai_json(prompt: str, model_cls, temperature: float = 0.4):
    res = await call_gemini_editorial(prompt, model_cls, model_prefer=GEMINI_LITE_MODEL, batch_id="aux")
    if res:
        return res
    res = await call_cloudflare_workers_ai(prompt, model_cls, batch_id="aux")
    if res:
        return res
    return await call_groq_editorial_or_verify(prompt, schema_cls=model_cls, batch_id="aux")

# ================= ۱۰. ارسال امن تلگرام، پین کردن و نظرسنجی =================
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

async def download_image_from_url(session: aiohttp.ClientSession, url: str, filename: str) -> str | None:
    safe_u = validate_safe_external_url(url)
    if not safe_u:
        return None
    try:
        async with session.get(safe_u, timeout=aiohttp.ClientTimeout(total=15), headers=UA, max_redirects=3) as resp:
            if resp.status != 200 or not validate_safe_external_url(str(resp.url)):
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/"):
                return None
            data = await resp.content.read(MAX_IMAGE_BYTES)
            if len(data) < 512:
                return None
            filepath = os.path.join('temp_media', filename)
            with open(filepath, 'wb') as f:
                f.write(data)
            return filepath
    except Exception as e:
        print(f"Error downloading image {redact_secrets(safe_u)}: {redact_secrets(str(e))}")
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

def _reply_kwargs(message_id):
    if not message_id:
        return {}
    if ReplyParameters is not None:
        return {"reply_parameters": ReplyParameters(message_id=message_id, allow_sending_without_reply=True)}
    return {"reply_to_message_id": message_id, "allow_sending_without_reply": True}

async def send_post(session, text, image_url=None, reply_markup=None, silent=False,
                    reply_to=None, filename="post.jpg", link_preview=False):
    text = _fit_lines(text, 4000)
    clean_img_url = validate_safe_external_url(image_url) if image_url else None

    async def send_text_single(body, parse_mode, markup, reply_id, media_url=None):
        preview_opts = None
        if media_url:
            preview_opts = LinkPreviewOptions(
                is_disabled=False,
                url=media_url,
                prefer_large_media=True,
                show_above_text=True
            )
        return await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=body,
            parse_mode=parse_mode,
            reply_markup=markup,
            disable_notification=silent,
            disable_web_page_preview=(not link_preview and not media_url),
            link_preview_options=preview_opts,
            **_reply_kwargs(reply_id)
        )

    async def send_photo_single(path, caption, parse_mode, markup, reply_id):
        with open(path, "rb") as fh:
            return await bot.send_photo(
                chat_id=TARGET_CHANNEL,
                photo=fh,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=markup,
                disable_notification=silent,
                **_reply_kwargs(reply_id)
            )

    if clean_img_url and _visible_len(text) <= 1000:
        img_path = await download_image_from_url(session, clean_img_url, filename)
        try:
            if img_path and os.path.exists(img_path):
                try:
                    return await send_photo_single(img_path, text, "HTML", reply_markup, reply_to)
                except Exception as photo_err:
                    if "entities" in str(photo_err).lower() or "parse" in str(photo_err).lower():
                        return await send_photo_single(img_path, _strip_tags(text), None, reply_markup, reply_to)
        finally:
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except OSError:
                    pass

    try:
        return await send_text_single(text, "HTML", reply_markup, reply_to, media_url=clean_img_url)
    except Exception as err:
        err_low = str(err).lower()
        if "entities" in err_low or "parse" in err_low:
            return await send_text_single(_strip_tags(text), None, reply_markup, reply_to, media_url=clean_img_url)
        return await send_text_single(text, "HTML", reply_markup, reply_to, media_url=None)

async def send_interactive_poll_reply(sel: SelectedNewsItem, reply_to_msg_id: int, silent: bool = False):
    if not sel.poll_question or not sel.poll_options or len(sel.poll_options) < 2:
        return
    clean_q = _strip_tags(sel.poll_question)[:280]
    clean_opts = [_strip_tags(opt)[:95] for opt in sel.poll_options[:3] if opt.strip()]
    if len(clean_opts) < 2:
        return
    try:
        await bot.send_poll(
            chat_id=TARGET_CHANNEL,
            question=f"📊 نظر شما چیست؟ {clean_q}",
            options=clean_opts,
            is_anonymous=True,
            disable_notification=silent,
            **_reply_kwargs(reply_to_msg_id)
        )
    except Exception as e:
        print(f"⚠️ خطا در ارسال نظرسنجی: {redact_secrets(str(e))}")

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
    except Exception as e:
        print(f"⚠️ پین ناموفق: {redact_secrets(str(e))}")

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
            except Exception as e:
                msg = str(e).lower()
                if "not found" in msg or "not modified" in msg or "message to unpin" in msg:
                    continue
                remaining.append(pin)
        else:
            remaining.append(pin)
    set_metadata("pinned_posts", json.dumps(remaining))

# ================= ۱۱. پست روزانه تقویم و شعر سعدی (ساعت ۱۱) و فیلم/موسیقی (ساعت ۱۲) =================
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
    return {
        "m1": persian_polish(m1),
        "m2": persian_polish(m2),
        "title": poem.get("fullTitle") or "دیوان سعدی",
        "url": sanitize_plain_url("[https://ganjoor.net](https://ganjoor.net)" + full_url)
    }

async def fetch_saadi_verse(session) -> dict:
    base = "[https://api.ganjoor.net/api/ganjoor](https://api.ganjoor.net/api/ganjoor)"
    try:
        poet_id = get_metadata("ganjoor_saadi_id", "")
        if not poet_id:
            status, body, _ = await safe_http_get_text(session, f"{base}/poets", timeout_sec=15, require_html_or_xml=True)
            if status == 200 and body:
                for p in json.loads(body):
                    name = (p.get("name") or "").replace("ي", "ی")
                    if (p.get("fullUrl") or "").strip("/") == "saadi" or name.strip() == "سعدی":
                        poet_id = str(p["id"])
                        set_metadata("ganjoor_saadi_id", poet_id)
                        break
        if poet_id:
            for _ in range(6):
                status, body, _ = await safe_http_get_text(session, f"{base}/poem/random?poetId={poet_id}", timeout_sec=15, require_html_or_xml=True)
                if status == 200 and body:
                    beit = _extract_beit(json.loads(body))
                    if beit:
                        return beit
    except Exception as e:
        print(f"⚠️ دریافت شعر از گنجور ناموفق: {redact_secrets(str(e))}")
    m1, m2, title = random.choice(FALLBACK_VERSES)
    return {"m1": m1, "m2": m2, "title": title, "url": "[https://ganjoor.net/saadi/](https://ganjoor.net/saadi/)"}

def build_daily_poem_post(verse: dict, dt: datetime) -> str:
    d = format_dates(dt)
    poem_url = sanitize_plain_url(verse["url"])
    lines = [
        "🗓 <b>تقویم امروز و بیتی از سعدی</b>",
        f"📅 امروز: <b>{d['weekday']}</b> ({d['weekday_order']})",
        f"☀️ تاریخ شمسی: <b>{d['jalali']}</b>",
        f"🌍 تاریخ میلادی: <b>{d['gregorian']}</b>",
        "",
        "📜 <b>بیتی از سعدی</b>",
        f"<blockquote>{html.escape(verse['m1'])}\n{html.escape(verse['m2'])}</blockquote>",
        f"✍️ سعدی شیرازی | <a href=\"{html.escape(poem_url)}\">{html.escape(verse['title'])}</a> (گنجور)",
        f"\n🏷 #تقویم_روز #سعدی #شعر_فارسی #ادبیات{CHANNEL_SIGNATURE}",
    ]
    return "\n".join(lines)

async def publish_daily_poem_post_if_due(session):
    current_tehran = get_current_tehran_time()
    today = current_tehran.strftime("%Y-%m-%d")
    if not (DAILY_POEM_POST_HOUR <= current_tehran.hour < DAILY_POEM_WINDOW_END_HOUR):
        return
    if get_metadata("last_daily_poem_date") == today:
        return
    verse = await fetch_saadi_verse(session)
    poem_url = sanitize_plain_url(verse["url"])
    text = build_daily_poem_post(verse, current_tehran)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📜 خواندن شعر کامل در گنجور", url=poem_url)]])
    msg = await send_post(session, text, reply_markup=markup, silent=False)
    set_metadata("last_daily_poem_date", today)
    await pin_post(msg.message_id)

INTERNATIONAL_DAYS = {
    "01-24": ("International Day of Education", "روز جهانی آموزش"),
    "02-11": ("International Day of Women and Girls in Science", "روز جهانی زنان و دختران در علم"),
    "02-13": ("World Radio Day", "روز جهانی رادیو"),
    "02-21": ("International Mother Language Day", "روز جهانی زبان مادری"),
    "03-08": ("International Women's Day", "روز جهانی زن"),
    "03-20": ("International Day of Happiness", "روز جهانی شادی"),
    "03-21": ("World Poetry Day", "روز جهانی شعر"),
    "03-27": ("World Theatre Day", "روز جهانی تئاتر"),
    "04-07": ("World Health Day", "روز جهانی بهداشت"),
    "04-12": ("International Day of Human Space Flight", "روز جهانی پرواز فضایی انسان"),
    "04-15": ("World Art Day", "روز جهانی هنر"),
    "04-22": ("Earth Day", "روز جهانی زمین"),
    "04-23": ("World Book and Copyright Day", "روز جهانی کتاب و حق مؤلف"),
    "04-30": ("International Jazz Day", "روز جهانی جاز"),
    "05-01": ("International Workers' Day", "روز جهانی کارگر"),
    "05-18": ("International Museum Day", "روز جهانی موزه"),
    "06-05": ("World Environment Day", "روز جهانی محیط زیست"),
    "06-21": ("World Music Day", "روز جهانی موسیقی"),
    "07-30": ("International Day of Friendship", "روز جهانی دوستی"),
    "08-12": ("International Youth Day", "روز جهانی جوانان"),
    "08-19": ("World Photography Day", "روز جهانی عکاسی"),
    "09-21": ("International Day of Peace", "روز جهانی صلح"),
    "09-27": ("World Tourism Day", "روز جهانی گردشگری"),
    "10-01": ("International Music Day", "روز جهانی موسیقی"),
    "10-05": ("World Teachers' Day", "روز جهانی معلم"),
    "10-10": ("World Mental Health Day", "روز جهانی سلامت روان"),
    "10-16": ("World Food Day", "روز جهانی غذا"),
    "11-10": ("World Science Day for Peace and Development", "روز جهانی علم برای صلح و توسعه"),
    "11-13": ("World Kindness Day", "روز جهانی مهربانی"),
    "11-20": ("World Children's Day", "روز جهانی کودک"),
    "11-21": ("World Television Day", "روز جهانی تلویزیون"),
    "12-03": ("International Day of Persons with Disabilities", "روز جهانی افراد دارای معلولیت"),
    "12-10": ("Human Rights Day", "روز جهانی حقوق بشر"),
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
    occasion_note_persian: str = ""
    movie: MovieRec
    music: MusicRec

async def omdb_lookup(session, title: str, year: int):
    if not OMDB_API_KEY:
        return None
    url = f"[https://www.omdbapi.com/?apikey=](https://www.omdbapi.com/?apikey=){OMDB_API_KEY}&t={quote_plus(title)}&y={year}&type=movie"
    status, body, _ = await safe_http_get_text(session, url, timeout_sec=12, require_html_or_xml=True)
    if status != 200 or not body:
        return None
    try:
        data = json.loads(body)
        if data.get("Response") != "True":
            return None
        rating = float(data.get("imdbRating", "0"))
        votes = int(to_en_digits(data.get("imdbVotes", "0")).replace(",", "") or 0)
        raw_poster = str(data.get("Poster", ""))
        poster = validate_safe_external_url(raw_poster) if raw_poster.startswith("http") else None
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
    for _ in range(2):
        occasion_line = (f"Known international day: {occasion[0]} ({occasion[1]})." if occasion else
                         "Connect picks to today's season/date.")
        prompt = f"""
You are the culture editor of @jazebestore. Today is {dt.strftime('%A, %d %B %Y')}.
{occasion_line}
Pick ONE real feature film (IMDb strictly > 7.0, >=20,000 votes) and ONE real music track (genre: {genre_key}).
Do NOT pick: {json.dumps(recent['movies'][-50:] + recent['music'][-50:] + rejected, ensure_ascii=False)}.
Write all *_persian fields in fluent Persian with proper half-spaces (نیم‌فاصله).
"""
        rec = await ask_lightweight_ai_json(prompt, DailyRec, temperature=0.5)
        if not rec:
            continue
        m = rec.movie
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
             f"📅 امروز: <b>{d['weekday']}</b> ({d['weekday_order']}) | {d['jalali']} | {d['gregorian']}"]
    if rec.occasion_note_persian:
        lines.append(f"<blockquote>{e(persian_polish(rec.occasion_note_persian))}</blockquote>")
    title_line = f"{e(m.title_fa)} ({e(m.title_en)}، {m.year})" if m.title_fa else f"{e(m.title_en)} ({m.year})"
    rating_note = (f"⭐ نمره IMDb: <b>{m.imdb_rating}/10</b> (تأییدشده)" if info
                   else f"⭐ نمره IMDb: حدود <b>{m.imdb_rating}/10</b>")
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
        return
    rec, info, genre_key, genre_fa, occasion = result
    text = build_daily_rec_post(rec, info, genre_fa, occasion, current_tehran)
    m, mu = rec.movie, rec.music
    imdb_url = sanitize_plain_url(
        f"[https://www.imdb.com/title/](https://www.imdb.com/title/){info['id']}/" if info and info.get("id")
        else f"[https://www.imdb.com/find/?q=](https://www.imdb.com/find/?q=){quote_plus(m.title_en + ' ' + str(m.year))}"
    )
    music_q = quote_plus(f"{mu.artist} {mu.track}")
    yt_url = sanitize_plain_url(f"[https://www.youtube.com/results?search_query=](https://www.youtube.com/results?search_query=){music_q}")
    sp_url = sanitize_plain_url(f"[https://open.spotify.com/search/](https://open.spotify.com/search/){music_q}")

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 صفحه‌ی فیلم در IMDb", url=imdb_url)],
        [InlineKeyboardButton("▶️ شنیدن موسیقی در YouTube", url=yt_url)],
        [InlineKeyboardButton("🎧 جستجو در Spotify", url=sp_url)],
    ])
    msg = await send_post(session, text, image_url=(info or {}).get("poster"), reply_markup=markup, filename="daily_rec.jpg")
    set_metadata("last_daily_rec_date", today)
    recent = _recent_load()
    recent["movies"] = (recent["movies"] + [m.title_en])[-150:]
    recent["music"] = (recent["music"] + [f"{mu.artist} - {mu.track}"])[-150:]
    set_metadata("recent_recs", json.dumps(recent, ensure_ascii=False))
    await pin_post(msg.message_id)

async def run_daily_jobs(session):
    for job in (unpin_expired_pins, publish_daily_poem_post_if_due, publish_daily_recommendation_if_due):
        try:
            await job(session)
        except Exception as e:
            print(f"⚠️ خطا در کار روزانه {job.__name__}: {redact_secrets(str(e))}")

# ================= ۱۲. پایپ‌لاین مجزای میم کاربران Reddit =================
class MemePick(BaseModel):
    chosen_index: int
    joke_persian: str = ""
    context_persian: str = ""
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
        url = f"[https://www.reddit.com/search.rss?q=](https://www.reddit.com/search.rss?q=){quote_plus(query)}&sort=top&t={period}&limit=20"
        status, xml, _ = await safe_http_get_text(session, url, headers=REDDIT_UA, timeout_sec=12, require_html_or_xml=True)
        if status != 200 or not xml:
            continue
        feed = await asyncio.to_thread(feedparser.parse, xml)
        for e in feed.entries:
            tags = getattr(e, "tags", []) or []
            sub = str(tags[0].get("term", "")).lower() if tags else ""
            link = validate_safe_external_url(getattr(e, "link", ""))
            if sub not in MEME_SUBREDDITS or not link or link in seen:
                continue
            body = e.content[0].value if getattr(e, "content", None) else ""
            m = re.search(r'https://(?:i|preview)\.redd\.it/[^"\']+?\.(?:jpe?g|png|webp)[^"\']*', body)
            img = validate_safe_external_url(html.unescape(m.group(0))) if m else None
            out.append({"index": len(out), "subreddit": sub, "title": (e.title or "")[:200], "link": link, "image": img})
            if len(out) >= 4:
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
Topic: {topic_en}
Reddit posts: {json.dumps([{k: c[k] for k in ('index', 'subreddit', 'title')} for c in cands], ensure_ascii=False)}
Pick the ONE genuinely funny, safe community joke about this topic (chosen_index = -1 if none).
Translate the joke into natural, witty Persian.
"""
        pick = await ask_lightweight_ai_json(prompt, MemePick, temperature=0.4)
        if pick is None or pick.chosen_index < 0 or pick.chosen_index >= len(cands) or not pick.is_safe_and_funny or len(pick.joke_persian.strip()) < 8:
            return False
        c = cands[pick.chosen_index]
        e = html.escape
        lines = ["😄 <b>شوخی کاربران فضای مجازی</b>", f"<blockquote>{e(persian_polish(pick.joke_persian))}</blockquote>"]
        if pick.context_persian.strip():
            lines.append(f"💬 {e(persian_polish(pick.context_persian))}")
        lines.append(f"📎 برگرفته از Reddit (r/{e(c['subreddit'])}): «{e(c['title'][:120])}»")
        lines.append(f"\n🏷 #شوخی_کاربران #میم #فان{CHANNEL_SIGNATURE}")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 دیدن پست اصلی در Reddit", url=c["link"])]])
        await send_post(session, "\n".join(lines), image_url=c["image"], reply_markup=markup, reply_to=reply_to, filename=f"meme_{c['index']}.jpg")
        set_metadata("meme_seen", json.dumps((_meme_seen() + [c["link"]])[-300:]))
        set_metadata("last_meme_ts", str(get_current_tehran_time().timestamp()))
        return True
    except Exception:
        return False

# ================= ۱۳. قالب‌بندی خبر، Fact Pack چندپلتفرمی و انتشار امن =================
_CAT_EMOJI = {"gaming": "🎮", "technology": "💻", "hardware": "⚡", "crypto": "🪙", "film_tv": "🍿",
              "internet_culture": "🌐", "fun_meme": "😄", "music": "🎵", "general_news": "📰"}
_VER_ICON = {
    "خبر رسمی": "✅",
    "گزارش تأییدشده از چند منبع": "☑️",
    "گزارش یک رسانه معتبر": "📰",
    "شایعه یا تأییدنشده": "🕵️",
    "خبر تأییدنشده": "⚠️"
}

def polish_selected(sel: SelectedNewsItem) -> None:
    for field in ("headline_persian", "summary_persian", "background_persian", "before_after_persian", "poll_question"):
        val = getattr(sel, field, "")
        if val:
            setattr(sel, field, persian_polish(val))
    if sel.key_points_persian:
        sel.key_points_persian = [persian_polish(p) for p in sel.key_points_persian]
    if sel.poll_options:
        sel.poll_options = [persian_polish(o) for o in sel.poll_options]

def format_rich_news_post(
    sel: SelectedNewsItem,
    orig_item: dict,
    main_cat_hashtag: str,
    verification_label: str,
    computed_confidence: int
) -> str:
    lines = []
    if sel.is_breaking:
        lines.append("🚨 <b>خبر فوری | پوشش ویژه</b>")
    if sel.series_name and sel.series_name in SERIALIZED_SERIES_HEADERS:
        lines.append(f"<b>{SERIALIZED_SERIES_HEADERS[sel.series_name]}</b>")
    lines.append(f"{_CAT_EMOJI.get(sel.category_id, '📰')} <b>{sanitize_telegram_html(sel.headline_persian)}</b>")

    cat_fa = CATEGORY_PERSIAN_NAMES.get(sel.category_id, "اخبار")
    ver = verification_label if verification_label in _VER_ICON else "خبر تأییدنشده"
    src_cnt = max(1, int(orig_item.get("source_count", 1)))
    pub_dom = html.escape(orig_item.get("publisher_domain", "منبع خبری"))

    lines.append(f"🗂 دسته‌بندی: {cat_fa} | {_VER_ICON[ver]} وضعیت: <b>{ver}</b>")
    lines.append(f"🏛 منبع اولیه: <code>{pub_dom}</code> | 🔗 ناشران مستقل: {to_fa_digits(src_cnt)} | 📊 اعتبار شواهد: {to_fa_digits(computed_confidence)}٪")
    lines.append("")

    summary = re.sub(r"\s*\n\s*", " ", sel.summary_persian or "")
    lines.append(f"<blockquote>{sanitize_telegram_html(summary)}</blockquote>")

    before_after = (sel.before_after_persian or "").strip()
    if before_after:
        lines.append("")
        lines.append(f"🔄 <b>مقایسه قبل و بعد:</b> {sanitize_telegram_html(before_after)}")

    background = (sel.background_persian or "").strip()
    if background:
        lines.append("")
        lines.append(f"📌 <b>پیش‌زمینه:</b> {sanitize_telegram_html(re.sub(r'\\s*\\n\\s*', ' ', background))}")

    if sel.related_game:
        archive_links = get_related_channel_archive_links(sel.related_game, orig_item['id'], limit=2)
        if archive_links:
            lines.append("")
            lines.append(f"🗂 <b>پرونده ویژه {html.escape(sel.related_game)} در کانال:</b>")
            for prev_h, prev_url in archive_links:
                lines.append(f"• <a href=\"{html.escape(prev_url)}\">{sanitize_telegram_html(prev_h)}</a>")

    if sel.key_points_persian:
        lines.append("")
        lines.append("<b>مهم‌ترین نکات تأییدشده:</b>")
        for pt in sel.key_points_persian[:4]:
            clean = sanitize_telegram_html(pt.lstrip("•-*▫️🔹 "))
            if clean:
                lines.append(f"🔹 {clean}")

    extra = []
    for tag in sel.topic_hashtags:
        clean_tag = re.sub(r"[^\w#]", "_", tag.strip())
        if not clean_tag.startswith("#"):
            clean_tag = "#" + clean_tag
        if clean_tag != main_cat_hashtag and len(clean_tag) > 2:
            extra.append(clean_tag)
    lines.append(f"\n🏷 {' '.join([main_cat_hashtag] + extra[:3])}{CHANNEL_SIGNATURE}")
    return "\n".join(lines)

def format_multiplatform_fact_pack(item_id: int, sel: SelectedNewsItem, orig_item: dict, ver_label: str) -> str:
    mp = sel.multiplatform or MultiPlatformPack()
    e = html.escape
    lines = [
        f"📦 <b>بسته محتوای چندپلتفرمی (Fact Pack #{item_id})</b>",
        f"📰 <b>تیتر:</b> {e(sel.headline_persian)}",
        f"🏛 <b>منبع:</b> {e(orig_item.get('publisher_domain', ''))} ({e(ver_label)})",
        f"🔗 {e(orig_item.get('link', ''))}",
        ""
    ]
    if mp.story_hook_persian:
        lines.append(f"🔥 <b>هوک استوری (Telegram / Instagram Story):</b>\n<blockquote>{e(persian_polish(mp.story_hook_persian))}</blockquote>\n")
    if mp.instagram_carousel_slides:
        lines.append("📸 <b>اسلایدهای پیشنهادی Instagram Carousel:</b>")
        for idx, sl in enumerate(mp.instagram_carousel_slides[:5], start=1):
            lines.append(f"اسلاید {to_fa_digits(idx)}: {e(persian_polish(sl))}")
        lines.append("")
    if mp.short_video_script_persian:
        lines.append(f"🎬 <b>سناریوی ویدیوی کوتاه (YouTube Shorts / TikTok / Reels):</b>\n<blockquote>{e(persian_polish(mp.short_video_script_persian))}</blockquote>")
    return "\n".join(lines)

async def publish_roundup_digest_post(
    session: aiohttp.ClientSession,
    roundup_items: list[tuple[SelectedNewsItem, dict]],
    silent_mode: bool
):
    if not roundup_items:
        return
    current_tehran = get_current_tehran_time()
    lines = [
        f"⚡ <b>مرور سریع و فشرده اخبار | بسته ساعت {to_fa_digits(current_tehran.strftime('%H:%M'))}</b>",
        "گزیده سایر رویدادهای تأییدشده دنیای گیمینگ، تکنولوژی و سرگرمی:",
        ""
    ]
    used_tags = {"#مرور_سریع"}

    for sel, orig_item in roundup_items:
        polish_selected(sel)
        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
        emoji = _CAT_EMOJI.get(cat_id, "🔹")
        used_tags.add(CATEGORY_HASHTAGS.get(cat_id, "#اخبار"))
        headline_clean = sanitize_telegram_html(sel.headline_persian)
        first_sentence = sanitize_telegram_html((sel.summary_persian or "").split(".")[0].strip())
        news_url = html.escape(orig_item.get('link', STORE_BASE_URL))
        pub_dom = html.escape(orig_item.get('publisher_domain', 'منبع'))

        lines.append(f"{emoji} <b>{headline_clean}</b>")
        if first_sentence:
            lines.append(f"▫️ {first_sentence}. (<a href=\"{news_url}\">{pub_dom}</a>)")
        lines.append("")

    lines.append(f"🏷 {' '.join(list(used_tags)[:5])}{CHANNEL_SIGNATURE}")
    try:
        msg = await send_post(session, "\n".join(lines), silent=silent_mode)
        for sel, orig_item in roundup_items:
            cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
            ver_lbl, conf_val = compute_evidence_based_verification(orig_item["publisher_domain"], orig_item["source_count"], None)
            mark_outbox_sent(orig_item['id'], msg.message_id)
            save_published_news_details(
                item_id=orig_item['id'],
                fingerprint=sel.topic_fingerprint,
                pub_cat=cat_id,
                pub_headline=sel.headline_persian,
                related_entity=sel.related_game,
                verification_label=ver_lbl,
                computed_confidence=conf_val,
                ai_payload=sel.model_dump(),
                multiplatform_pack=sel.multiplatform.model_dump() if sel.multiplatform else {},
                telegram_msg_id=msg.message_id
            )
            if sel.related_game:
                record_hype_event(sel.related_game, cat_id, float(sel.hype_score))
    except Exception as err:
        print(f"⚠️ خطا در انتشار بسته مرور سریع: {redact_secrets(str(err))}")
        update_news_status([orig['id'] for _, orig in roundup_items], 'failed', increment_retry=True)

async def process_and_publish_batch(
    session: aiohttp.ClientSession,
    breaking_only: bool = False,
    max_items: int = MAX_NEWS_PER_CYCLE
):
    recover_stale_leases()

    conn = get_db_connection()
    c = conn.cursor()
    if breaking_only:
        c.execute("""
            SELECT id, url, category, source, publisher_domain, raw_title, raw_text, image_url,
                   has_video_or_audio, source_count, is_breaking_candidate, source_published_at
            FROM news_items
            WHERE status IN ('pending', 'failed') AND retry_count < 3 AND is_breaking_candidate = 1
            ORDER BY source_count DESC, id DESC LIMIT 12
        """)
    else:
        c.execute("""
            SELECT id, url, category, source, publisher_domain, raw_title, raw_text, image_url,
                   has_video_or_audio, source_count, is_breaking_candidate, source_published_at
            FROM news_items
            WHERE status IN ('pending', 'failed') AND retry_count < 3
            ORDER BY is_breaking_candidate DESC, source_count DESC, id DESC LIMIT 45
        """)
    rows = c.fetchall()

    if not rows:
        conn.close()
        increment_metadata_counter("skipped_ai_calls_no_news", 1)
        return

    c.execute("""
        SELECT topic_fingerprint
        FROM news_items
        WHERE status = 'published' AND topic_fingerprint IS NOT NULL
        ORDER BY published_at DESC LIMIT 40
    """)
    recent_topics = [r[0] for r in c.fetchall() if r[0]]
    conn.close()

    all_fetched = [
        {
            'id': r[0],
            'link': sanitize_plain_url(r[1]),
            'category': r[2],
            'source': r[3],
            'publisher_domain': r[4] or extract_publisher_domain(r[1]),
            'title': r[5] or "",
            'text': (r[6] or "")[:360],
            'image_url': validate_safe_external_url(r[7]) if r[7] else None,
            'has_video_or_audio': bool(r[8]),
            'source_count': max(1, int(r[9] or 1)),
            'is_breaking_candidate': bool(r[10]),
            'source_published_at': r[11]
        }
        for r in rows
    ]

    cat_weights = get_category_engagement_weights()
    for item in all_fetched:
        item['_composite_score'] = compute_composite_candidate_score(item, cat_weights)
    all_fetched.sort(key=lambda x: x['_composite_score'], reverse=True)

    limit_cnt = MAX_BREAKING_PER_CYCLE if breaking_only else MAX_CANDIDATES_FOR_AI
    current_batch = all_fetched[:limit_cnt]
    dropped_ids = [x['id'] for x in all_fetched[limit_cnt:]]

    update_news_status([x['id'] for x in current_batch], 'processing')
    if not breaking_only and dropped_ids:
        update_news_status(dropped_ids, 'rejected')

    await fetch_article_evidence_for_candidates(session, current_batch)

    candidates_for_ai = [
        {
            "id": item['id'],
            "cat": item['category'],
            "publisher": item['publisher_domain'],
            "independent_sources": item['source_count'],
            "brk_candidate": item['is_breaking_candidate'],
            "title": item['title'],
            "rss_summary": item['text'],
            "article_evidence": item.get('full_article_excerpt', '')[:ARTICLE_MAX_CHARS],
            "extracted_numbers": item.get('extracted_numbers', []),
            "extracted_quotes": item.get('extracted_quotes', [])
        }
        for item in current_batch
    ]

    batch_id = f"{'brk' if breaking_only else 'reg'}_{int(time.time())}"
    prompt = f"""
Chief Editor of '@jazebestore'. Mode: {'BREAKING' if breaking_only else 'REGULAR CYCLE'}.
Already published topics (DO NOT repeat): {json.dumps(recent_topics[:30], ensure_ascii=False)}
Evidence-backed Candidates:
{json.dumps(candidates_for_ai, ensure_ascii=False)}

Strict Editorial Rules:
1. Select AT MOST {max_items} unique, newsworthy stories ordered by importance.
2. NEVER invent facts, dates, prices, quotes, image descriptions, or video transcripts. Use ONLY `rss_summary` and `article_evidence`.
3. Do NOT select memes here.
4. Persian writing: fluent standard Persian, proper half-spaces (نیم‌فاصله), Persian punctuation (، ؛ ؟ «»), keep English proper nouns.
   - `summary_persian`: 3-5 factual sentences; wrap 1-3 key facts in <b>...</b>.
   - `key_points_persian`: 2-4 factual bullets.
   - `before_after_persian`: 'قبل: ... | اکنون: ...' ONLY if the evidence shows a delay, price change, or spec upgrade, else "".
5. For the top 2 stories, populate `multiplatform` (3-4 Instagram Carousel slides, a 25-sec Shorts/TikTok script, and a 1-line Story hook).
6. For stories with `hype_score` >= 8, include `poll_question` and 2-3 short `poll_options`.
"""

    validated_result = await generate_editorial_batch(prompt, batch_id=batch_id)
    if not validated_result or not validated_result.selected_news:
        update_news_status([x['id'] for x in current_batch], 'pending')
        return

    batch_map = {item['id']: item for item in current_batch}
    valid_selections = [s for s in validated_result.selected_news if s.selected_id in batch_map][:max_items]
    selected_ids = {s.selected_id for s in valid_selections}
    unselected_ids = [item['id'] for item in current_batch if item['id'] not in selected_ids]

    if selected_ids:
        update_news_status(list(selected_ids), 'selected')
    if unselected_ids:
        update_news_status(unselected_ids, 'rejected' if not breaking_only else 'pending')

    standalone_limit = MAX_BREAKING_PER_CYCLE if breaking_only else MAX_STANDALONE_POSTS_PER_CYCLE
    standalone_selections = valid_selections[:standalone_limit]
    roundup_selections = [] if breaking_only else valid_selections[standalone_limit:]

    tehran_hour = get_current_tehran_time().hour
    silent_mode = (0 <= tehran_hour < 8) and not breaking_only
    memes_posted = 0

    for sel in standalone_selections:
        orig_item = batch_map.get(sel.selected_id)
        if not orig_item:
            continue

        already_sent_msg_id = mark_outbox_sending(orig_item['id'])
        if already_sent_msg_id:
            update_news_status([orig_item['id']], 'published')
            continue

        update_news_status([orig_item['id']], 'publishing')

        groq_ok, _ = await verify_sensitive_story_with_groq(sel, orig_item, batch_id=batch_id)
        ver_label, comp_conf = compute_evidence_based_verification(
            orig_item["publisher_domain"], orig_item["source_count"], groq_ok
        )

        polish_selected(sel)
        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
        main_cat_hashtag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")
        final_caption = format_rich_news_post(sel, orig_item, main_cat_hashtag, ver_label, comp_conf)

        news_link = orig_item.get('link', STORE_BASE_URL)
        video_url = orig_item.get('video_url', '')
        keyboard = [
            [InlineKeyboardButton("❤️ پسندیدن این خبر (0)", callback_data=f"like_{orig_item['id']}")],
            [InlineKeyboardButton("🔗 مطالعه گزارش کامل در منبع اصلی", url=news_link)]
        ]
        if video_url:
            keyboard.append([InlineKeyboardButton("▶️ تماشای ویدیوی خبر", url=video_url)])

        try:
            news_msg = await send_post(
                session, final_caption, image_url=orig_item.get('image_url'),
                reply_markup=InlineKeyboardMarkup(keyboard), silent=silent_mode, filename=f"img_{orig_item['id']}.jpg"
            )
            mark_outbox_sent(orig_item['id'], news_msg.message_id)
            save_published_news_details(
                item_id=orig_item['id'],
                fingerprint=sel.topic_fingerprint,
                pub_cat=cat_id,
                pub_headline=sel.headline_persian,
                related_entity=sel.related_game,
                verification_label=ver_label,
                computed_confidence=comp_conf,
                ai_payload=sel.model_dump(),
                multiplatform_pack=sel.multiplatform.model_dump() if sel.multiplatform else {},
                telegram_msg_id=news_msg.message_id
            )
            set_metadata(f"news_msg_{orig_item['id']}", str(news_msg.message_id))
            if sel.related_game:
                record_hype_event(sel.related_game, cat_id, float(sel.hype_score))

            if not silent_mode and sel.hype_score >= POLL_MIN_HYPE and sel.poll_question:
                await send_interactive_poll_reply(sel, news_msg.message_id, silent_mode)

            if not silent_mode and memes_posted < MEME_MAX_PER_CYCLE and sel.hype_score >= MEME_MIN_HYPE and sel.related_game:
                if await _try_meme(session, sel.related_game, sel.topic_fingerprint or sel.related_game, reply_to=news_msg.message_id):
                    memes_posted += 1

            await asyncio.sleep(3)
        except Exception as send_err:
            print(f"⚠️ خطا در ارسال خبر #{orig_item['id']}: {redact_secrets(str(send_err))}")
            update_news_status([orig_item['id']], 'failed', increment_retry=True)

    if roundup_selections:
        roundup_pairs = [(s, batch_map[s.selected_id]) for s in roundup_selections if s.selected_id in batch_map]
        await publish_roundup_digest_post(session, roundup_pairs, silent_mode)

# ================= ۱۴. گزارش خلاصه روزانه (Daily Digest ساعت ۰۰:۰۰) =================
async def publish_daily_digest_if_due():
    current_tehran = get_current_tehran_time()
    today_str = current_tehran.strftime("%Y-%m-%d")
    if current_tehran.hour != 0 or current_tehran.minute > 20:
        return
    if get_metadata("last_daily_digest_date") == today_str:
        return

    conn = get_db_connection()
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
        clean_u = sanitize_plain_url(url)
        entry_line = f"• <a href=\"{html.escape(clean_u)}\">{clean_h}</a>"
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
        "📅 <b>گزارش جامع روزانه (Daily Digest) | جمع‌بندی ۲۴ ساعت گذشته</b>",
        f"تاریخ: {today_str} | ساعت ۰۰:۰۰ به وقت تهران",
        ""
    ]
    if by_cat["gaming"]:
        digest_lines += ["🎮 <b>مهم‌ترین اخبار گیمینگ:</b>"] + by_cat["gaming"] + [""]
    if by_cat["technology"]:
        digest_lines += ["💻 <b>مهم‌ترین اخبار تکنولوژی:</b>"] + by_cat["technology"] + [""]
    if by_cat["hardware"]:
        digest_lines += ["⚡ <b>مهم‌ترین اخبار سخت‌افزار:</b>"] + by_cat["hardware"] + [""]
    if by_cat["ent"]:
        digest_lines += ["🍿 <b>سینما و موسیقی:</b>"] + by_cat["ent"] + [""]

    digest_lines.append(f"🚀 <b>داغ‌ترین ترندهای ۲۴ ساعت اخیر:</b> <b>{' | '.join(trend_names)}</b>")
    digest_lines.append(f"\n🏷 #خلاصه_روزانه #Daily_Digest #گیمینگ #تکنولوژی{CHANNEL_SIGNATURE}")

    try:
        await bot.send_message(chat_id=TARGET_CHANNEL, text="\n".join(digest_lines), parse_mode="HTML", disable_web_page_preview=True)
        set_metadata("last_daily_digest_date", today_str)
    except Exception as e:
        print(f"⚠️ خطا در ارسال Daily Digest: {redact_secrets(str(e))}")

# ================= ۱۵. داشبورد کامل ادمین (/status، /pack، /correct) و واکنش‌ها =================
async def admin_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not ADMIN_USER_ID or user_id != ADMIN_USER_ID:
        return

    today_str = get_current_tehran_time().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news_items WHERE status = 'published' AND published_at >= datetime('now', '-24 hours')")
    pub_24h = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM news_items WHERE status = 'pending'")
    pending_cnt = c.fetchone()[0] or 0

    c.execute("""
        SELECT provider, COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),
               COALESCE(SUM(total_tokens), 0), COALESCE(SUM(retry_count), 0)
        FROM ai_usage_logs
        WHERE request_date = ?
        GROUP BY provider
    """, (today_str,))
    usage_rows = {r[0]: r[1:] for r in c.fetchall()}

    c.execute("SELECT COUNT(*) FROM rss_feed_health WHERE consecutive_failures >= 3")
    failing_feeds = c.fetchone()[0] or 0
    conn.close()

    g_calls, g_in, g_out, g_tot, g_ret = usage_rows.get("gemini", (0, 0, 0, 0, 0))
    cf_calls, cf_in, cf_out, cf_tot, cf_ret = usage_rows.get("cloudflare", (0, 0, 0, 0, 0))
    q_calls, q_in, q_out, q_tot, q_ret = usage_rows.get("groq", (0, 0, 0, 0, 0))
    o_calls, o_in, o_out, o_tot, o_ret = usage_rows.get("openrouter", (0, 0, 0, 0, 0))

    total_tokens_today = g_tot + cf_tot + q_tot + o_tot
    total_retries_today = g_ret + cf_ret + q_ret + o_ret
    news_per_1k = round((pub_24h / (total_tokens_today / 1000.0)), 2) if total_tokens_today > 0 else pub_24h
    skipped_calls = int(get_metadata("skipped_ai_calls_no_news", "0") or 0)
    last_err = get_metadata("last_api_error", "بدون خطا")

    lines = [
        "🛠 <b>داشبورد وضعیت سلامت و سهمیه ربات @jazebestore</b>",
        f"🕒 زمان تهران: {get_current_tehran_time().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"📰 اخبار منتشرشده ۲۴ ساعت اخیر: <b>{to_fa_digits(pub_24h)}</b>",
        f"⏳ خبرهای آماده در صف (Pending): <b>{to_fa_digits(pending_cnt)}</b>",
        f"⚡ بهره‌وری توکن: <b>{to_fa_digits(news_per_1k)} خبر به ازای هر ۱۰۰۰ توکن</b>",
        f"🛡 فراخوانی‌های AI صرفه‌جویی‌شده (نبود خبر جدید): <b>{to_fa_digits(skipped_calls)}</b>",
        f"📡 فیدهای دارای خطای متوالی (Backoff): <b>{to_fa_digits(failing_feeds)} فید</b>",
        "",
        "📊 <b>مصرف و سهمیه داخلی امروز:</b>",
        f"• <b>Gemini:</b> {to_fa_digits(g_calls)}/{to_fa_digits(GEMINI_DAILY_INTERNAL_CALL_LIMIT)} درخواست | توکن: {to_fa_digits(g_tot)}",
        f"• <b>Cloudflare AI:</b> {to_fa_digits(cf_calls)}/{to_fa_digits(CLOUDFLARE_DAILY_INTERNAL_CALL_LIMIT)} درخواست | توکن: {to_fa_digits(cf_tot)}",
        f"• <b>Groq:</b> {to_fa_digits(q_calls)}/{to_fa_digits(GROQ_DAILY_INTERNAL_CALL_LIMIT)} درخواست | توکن: {to_fa_digits(q_tot)}/{to_fa_digits(GROQ_DAILY_INTERNAL_TOKEN_LIMIT)}",
        f"• <b>OpenRouter:</b> {to_fa_digits(o_calls)}/{to_fa_digits(OPENROUTER_DAILY_INTERNAL_CALL_LIMIT)} درخواست | توکن: {to_fa_digits(o_tot)}",
        f"• <b>مجموع Retry امروز:</b> {to_fa_digits(total_retries_today)}",
        f"• <b>آخرین خطای API:</b> <code>{html.escape(last_err)}</code>",
        "",
        "💡 <b>دستورات تحریریه ادمین:</b>",
        "• <code>/pack [id]</code> — دریافت بسته محتوای Instagram/Shorts/TikTok",
        "• <code>/correct [id] [متن اصلاحیه]</code> — ثبت و انتشار اصلاحیه رسمی خبر"
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def admin_pack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    if not ADMIN_USER_ID or update.effective_user.id != ADMIN_USER_ID:
        return

    conn = get_db_connection()
    c = conn.cursor()
    if context.args and context.args[0].isdigit():
        c.execute("""
            SELECT id, published_headline, url, publisher_domain, verification_label, ai_payload_json, multiplatform_pack_json
            FROM news_items WHERE id = ?
        """, (int(context.args[0]),))
    else:
        c.execute("""
            SELECT id, published_headline, url, publisher_domain, verification_label, ai_payload_json, multiplatform_pack_json
            FROM news_items WHERE status = 'published' AND multiplatform_pack_json IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """)
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("بسته محتوایی برای این شناسه یافت نشد.")
        return

    item_id, headline, url, pub_dom, ver_lbl, ai_json, mp_json = row
    sel = SelectedNewsItem.model_validate(json.loads(ai_json))
    orig = {"publisher_domain": pub_dom, "link": url}
    text = format_multiplatform_fact_pack(item_id, sel, orig, ver_lbl or "گزارش")
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

async def admin_correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    if not ADMIN_USER_ID or update.effective_user.id != ADMIN_USER_ID:
        return
    if not context.args or len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("فرمت دستور: `/correct <item_id> <متن اصلاحیه>`")
        return

    item_id = int(context.args[0])
    corr_text = persian_polish(" ".join(context.args[1:]))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT telegram_message_id, published_headline FROM news_items WHERE id = ?", (item_id,))
    row = c.fetchone()
    if not row or not row[0]:
        conn.close()
        await update.message.reply_text("خبر یا پیام تلگرام متناظر یافت نشد.")
        return

    tg_msg_id, headline = row[0], row[1]
    c.execute("""
        INSERT INTO correction_logs (news_item_id, telegram_message_id, correction_text)
        VALUES (?, ?, ?)
    """, (item_id, tg_msg_id, corr_text))
    conn.commit()
    conn.close()

    post_text = (
        f"📝 <b>اصلاحیه و تکمیلیه خبر</b>\n"
        f"پیرو خبر «{html.escape(headline or '')}»:\n"
        f"<blockquote>{html.escape(corr_text)}</blockquote>"
        f"{CHANNEL_SIGNATURE}"
    )
    await bot.send_message(chat_id=TARGET_CHANNEL, text=post_text, parse_mode="HTML", **_reply_kwargs(tg_msg_id))
    await update.message.reply_text(f"✅ اصلاحیه برای خبر #{item_id} ثبت و در کانال منتشر شد.")

async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return

    data = query.data or ""
    if data.startswith("like_"):
        try:
            item_id = int(data.split("_")[1])
        except Exception:
            await query.answer()
            return

        added, total_likes = register_unique_user_vote(item_id, query.from_user.id)
        if not added:
            await query.answer("شما قبلاً به این خبر رأی داده‌اید ❤️", show_alert=False)
            return

        await query.answer("رأی شما ثبت شد ❤️")
        try:
            existing_rows = [list(r) for r in query.message.reply_markup.inline_keyboard]
            existing_rows[0][0] = InlineKeyboardButton(f"❤️ پسندیدن این خبر ({to_fa_digits(total_likes)})", callback_data=data)
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(existing_rows))
        except Exception:
            pass

async def message_reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mrc = getattr(update, "message_reaction_count", None)
    if not mrc:
        return
    try:
        msg_id = mrc.message_id
        total_reacts = sum(int(getattr(r, "total_count", 0) or 0) for r in (mrc.reactions or []))
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE news_items SET reaction_count = ? WHERE telegram_message_id = ?", (total_reacts, msg_id))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ================= ۱۶. حلقه اصلی ۲۴ ساعته با نشست مشترک و TLS امن =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = redact_secrets(str(context.error))
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید...")
    else:
        print(f"Telegram warning: {err_msg}")

async def background_news_loop(app: Application):
    global bot
    bot = app.bot
    init_db()
    if not ADMIN_USER_ID:
        print("⚠️ هشدار امنیتی: متغیر ADMIN_USER_ID تنظیم نشده است؛ دستورات ادمین (/status) به صورت پیش‌فرض قفل هستند.")

    print("🚀 24/7 Evidence-Driven Editorial Engine (with Cloudflare Workers AI) is running...")
    await asyncio.sleep(8)

    last_regular_cycle_ts = 0.0
    connector = aiohttp.TCPConnector(limit=25)
    async with aiohttp.ClientSession(connector=connector) as shared_session:
        while True:
            try:
                now_ts = datetime.now(timezone.utc).timestamp()
                tehran_now = get_current_tehran_time()

                await publish_daily_digest_if_due()
                await run_daily_jobs(shared_session)
                await fetch_rss_sources(shared_session)

                if (now_ts - last_regular_cycle_ts) >= REGULAR_CYCLE_SECONDS:
                    print(f"\n--- [چرخه ۳۰ دقیقه‌ای تحریریه | {tehran_now.strftime('%Y-%m-%d %H:%M')} تهران] ---")
                    await process_and_publish_batch(
                        session=shared_session,
                        breaking_only=False,
                        max_items=MAX_NEWS_PER_CYCLE
                    )
                    last_regular_cycle_ts = now_ts
                else:
                    await process_and_publish_batch(
                        session=shared_session,
                        breaking_only=True,
                        max_items=MAX_BREAKING_PER_CYCLE
                    )
            except Exception as e:
                print(f"Error in 24/7 background loop: {redact_secrets(str(e))}")

            await asyncio.sleep(BREAKING_CHECK_INTERVAL_SECONDS)

def main():
    print("Waiting 15 seconds for old container to shut down cleanly...")
    time.sleep(15)

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .get_updates_read_timeout(30)
        .get_updates_connect_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("status", admin_status_command))
    application.add_handler(CommandHandler("pack", admin_pack_command))
    application.add_handler(CommandHandler("correct", admin_correct_command))
    application.add_handler(CallbackQueryHandler(button_click_handler))
    try:
        application.add_handler(MessageReactionHandler(message_reaction_handler))
    except Exception:
        pass
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        global bot
        bot = app.bot
        await app.bot.delete_webhook(drop_pending_updates=False)
        asyncio.create_task(background_news_loop(app))

    application.post_init = post_init

    print("Telegram Bot application started (Evidence-Driven + Cloudflare AI Mode)...")
    application.run_polling(
        drop_pending_updates=False,
        allowed_updates=["message", "callback_query", "message_reaction", "message_reaction_count"],
        close_loop=False
    )

if __name__ == '__main__':
    main()
