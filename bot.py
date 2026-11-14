import asyncio
import hashlib
import html
import ipaddress
import json
import math
import os
import re
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import aiohttp
import feedparser
import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ==============================================================================
# ۱. تنظیمات متمرکز، کلیدهای محیطی و سیاست‌های تحریریه (Configuration)
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0") or 0)

GEMINI_API_KEYS = [
    k.strip()
    for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", ""),
    ]
    if k.strip() and not k.startswith("YOUR_")
]
GROQ_API_KEYS = [
    k.strip()
    for k in os.environ.get("GROQ_API_KEYS", "").split(",")
    if k.strip() and not k.startswith("YOUR_")
]
OPENROUTER_API_KEYS = [
    k.strip()
    for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",")
    if k.strip() and not k.startswith("YOUR_")
]

TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "@jazebestore").strip()
CHANNEL_SIGNATURE = f"\n\n🎮 {TARGET_CHANNEL}"
DB_PATH = os.environ.get("DB_PATH", "rss_news_history.db").strip()

# سیاست کیفیت بر کمیت: چرخه عادی هر ۱ ساعت (حداکثر ۳ خبر ممتاز) | بررسی فوری هر ۴ دقیقه
BREAKING_CHECK_INTERVAL_SECONDS = 240
REGULAR_CYCLE_SECONDS = 3600
MAX_NEWS_PER_CYCLE = 3
MAX_BREAKING_PER_CYCLE = 1
MAX_CANDIDATES_FOR_AI = 6
MIN_LOCAL_NEWSWORTHINESS_SCORE = 52.0
MIN_QA_PUBLISH_SCORE = 80
ARTICLE_MAX_CHARS = 2600
MAX_ARTICLE_AGE_HOURS = 48
MEME_GAP_MINUTES = 60
DAILY_DIGEST_HOUR = 23

# سهمیه ایمن داخلی برای سرویس‌های رایگان
GROQ_DAILY_CALL_LIMIT = 40
OPENROUTER_DAILY_CALL_LIMIT = 15

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
OPENROUTER_MODELS = ["openrouter/free"]

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
REDDIT_HEADERS = {"User-Agent": "JazebeStoreNewsroom/3.0 (Editorial Telegram Bot)"}

RLM = "\u200f"
LRI = "\u2066"
PDI = "\u2069"

CATEGORY_METADATA = {
    "gaming": {"fa": "بازی‌های ویدیویی", "tag": "#گیمینگ", "icon": "🎮"},
    "technology": {"fa": "تکنولوژی و هوش مصنوعی", "tag": "#تکنولوژی", "icon": "💻"},
    "hardware": {"fa": "سخت‌افزار کامپیوتر و کنسول", "tag": "#سخت_افزار", "icon": "🖥"},
    "gadgets": {"fa": "گجت و موبایل", "tag": "#گجت", "icon": "📱"},
    "cinema": {"fa": "سینما و فیلم", "tag": "#سینما", "icon": "🎬"},
    "television": {"fa": "سریال و استریمینگ", "tag": "#تلویزیون_و_سریال", "icon": "📺"},
    "internet_culture": {"fa": "فرهنگ اینترنتی", "tag": "#فرهنگ_اینترنتی", "icon": "🌐"},
    "fun_meme": {"fa": "فان و میم", "tag": "#فان_و_میم", "icon": "😄"},
}

# فهرست منابع RSS با سطح اعتبار (Tier 1: رسمی، Tier 2: رسانه تخصصی معتبر، Tier 3: تحلیلی/عمومی)
# ساختار: (آدرس فید، دسته‌بندی پیش‌فرض، سطح اعتبار ۱ تا ۳، فاصله بررسی به دقیقه)
RSS_SOURCES: list[tuple[str, str, int, int]] = [
    # Tier 1: منابع رسمی اول‌شخص (بررسی هر ۴ دقیقه)
    ("https://blog.playstation.com/feed/", "gaming", 1, 4),
    ("https://news.xbox.com/en-us/feed/", "gaming", 1, 4),
    ("https://blogs.nvidia.com/feed/", "hardware", 1, 4),
    # Tier 2: رسانه‌های تخصصی بین‌المللی و معتبر (بررسی هر ۱۵ دقیقه)
    ("https://www.videogameschronicle.com/feed/", "gaming", 2, 15),
    ("https://www.eurogamer.net/feed", "gaming", 2, 15),
    ("https://feeds.feedburner.com/ign/games-all", "gaming", 2, 15),
    ("https://www.gamespot.com/feeds/mashup/", "gaming", 2, 15),
    ("https://www.pcgamer.com/rss/", "gaming", 2, 15),
    ("https://www.polygon.com/rss/index.xml", "gaming", 2, 15),
    ("https://kotaku.com/rss", "gaming", 2, 15),
    ("https://www.rockpapershotgun.com/feed", "gaming", 2, 15),
    ("https://www.theverge.com/rss/index.xml", "technology", 2, 15),
    ("https://feeds.arstechnica.com/arstechnica/index", "technology", 2, 15),
    ("https://techcrunch.com/feed/", "technology", 2, 15),
    ("https://www.wired.com/feed/rss", "technology", 2, 15),
    ("https://www.engadget.com/rss.xml", "gadgets", 2, 15),
    ("https://feeds.macrumors.com/MacRumors-All", "gadgets", 2, 15),
    ("https://9to5mac.com/feed/", "gadgets", 2, 15),
    ("https://9to5google.com/feed/", "gadgets", 2, 15),
    ("https://www.tomshardware.com/feeds/all", "hardware", 2, 15),
    ("https://wccftech.com/feed/", "hardware", 2, 20),
    ("https://www.hollywoodreporter.com/feed/", "cinema", 2, 20),
    ("https://variety.com/feed/", "television", 2, 20),
    # Tier 2/3: رسانه‌های تخصصی فارسی (بررسی هر ۲۰ دقیقه)
    ("https://www.zoomg.ir/feed/", "gaming", 2, 20),
    ("https://vigiato.net/feed", "gaming", 2, 20),
    ("https://gamefa.com/feed", "gaming", 3, 30),
    ("https://www.zoomit.ir/feed/", "technology", 2, 20),
    ("https://digiato.com/feed", "technology", 2, 20),
]

MEME_SUBREDDITS = {
    "gaming",
    "pcmasterrace",
    "playstation",
    "xbox",
    "nintendo",
    "memes",
    "dankmemes",
    "programmerhumor",
    "technology",
    "gamingmemes",
    "gta6",
}

os.makedirs("temp_media", exist_ok=True)
provider_cooldowns: dict[str, float] = {}


# ==============================================================================
# ۲. امنیت، محافظت SSRF، نرمال‌سازی URL و مدیریت زمان (Security & Utilities)
# ==============================================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_tehran() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tehran"))


def redact_secrets(text: str) -> str:
    """حذف کامل کلیدهای API و توکن ربات از رشته‌های لاگ و پیام‌های خطا"""
    if not text:
        return ""
    out = str(text)
    secrets = [TELEGRAM_BOT_TOKEN] + GEMINI_API_KEYS + GROQ_API_KEYS + OPENROUTER_API_KEYS
    for sec in secrets:
        if sec and len(sec) > 6:
            out = out.replace(sec, "***REDACTED***")
    out = re.sub(r"bot\d+:[A-Za-z0-9_-]{20,}", "bot***REDACTED***", out)
    out = re.sub(r"(AIza[0-9A-Za-z-_]{20,}|gsk_[0-9A-Za-z]{20,}|sk-or-[0-9A-Za-z-_]{20,})", "***KEY***", out)
    return out


def sanitize_plain_url(url: str) -> str:
    """حذف هرگونه فرمت Markdown تصادفی از رشته‌های URL"""
    if not url:
        return ""
    s = str(url).strip()
    m = re.search(r"\((https?://[^)\s]+)\)", s)
    if m:
        return m.group(1).strip()
    s = re.sub(r"^\[|\]$", "", s)
    return s.strip()


def validate_safe_external_url(url: str) -> str:
    """محافظت در برابر SSRF: فقط پروتکل http/https و رد IPهای محلی، خصوصی و رزروشده"""
    clean = sanitize_plain_url(url)
    if not clean:
        return ""
    try:
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https"):
            return ""
        host = (parsed.hostname or "").strip().lower()
        if not host or host in ("localhost", "0.0.0.0") or host.endswith((".local", ".internal")):
            return ""
        try:
            ip = ipaddress.ip_address(host)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return ""
        except ValueError:
            pass
        return clean
    except Exception:
        return ""


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def normalize_canonical_url(url: str) -> str:
    """حذف پارامترهای ردیابی بدون تخریب پارامترهای اصلی صفحه (مانند v در یوتیوب یا id خبر)"""
    safe = validate_safe_external_url(url)
    if not safe:
        return ""
    parsed = urlparse(safe)
    filtered_q = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    clean_path = re.sub(r"/+$", "", parsed.path) or "/"
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower().removeprefix("www."),
        path=clean_path,
        query=urlencode(filtered_q, doseq=True),
        fragment="",
    )
    return urlunparse(normalized)


def extract_domain(url: str) -> str:
    try:
        host = (urlparse(sanitize_plain_url(url)).hostname or "").lower()
        return host.removeprefix("www.") or "unknown"
    except Exception:
        return "unknown"


def parse_feed_timestamp_utc(entry) -> datetime | None:
    """استخراج تاریخ انتشار ورودی RSS و تبدیل ایمن به UTC"""
    for field in ("published", "updated", "created"):
        raw = getattr(entry, field, None)
        if raw and isinstance(raw, str):
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
            try:
                iso = raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def is_entry_too_old(pub_dt: datetime | None, max_hours: int = MAX_ARTICLE_AGE_HOURS) -> bool:
    if pub_dt is None:
        return False
    age_seconds = (now_utc() - pub_dt).total_seconds()
    return age_seconds > (max_hours * 3600)


# ==============================================================================
# ۳. موتور نگارش فارسی، پاکسازی DOM و حل قطعی مشکل BiDi در تلگرام
# ==============================================================================
ALLOWED_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "blockquote", "a"}

TRANSLATIONESE_REPLACEMENTS = [
    (r"پشت[\s\u200c]*سرگیری بررسی[\s\u200c]*های", "صف بررسی بازی‌های"),
    (r"ارسال[\s\u200c]*های\s*AI", "آثار تولیدشده با هوش مصنوعی"),
    (r"گرفتن مرحله بالایی", "مهار و بازیابی مرحله بالایی"),
    (r"مواجه شده و این باعث ایجاد", "روبه‌رو شده و"),
    (r"در دنیای امروز،?", ""),
]


def persian_orthography_polish(text: str) -> str:
    """استانداردسازی حروف فارسی، نیم‌فاصله‌های فعل/جمع و حذف عبارات ترجمه‌ای ماشینی"""
    if not text:
        return ""
    res = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("ۀ", "هٔ")
    for pat, rep in TRANSLATIONESE_REPLACEMENTS:
        res = re.sub(pat, rep, res, flags=re.IGNORECASE)
    # اعمال نیم‌فاصله استاندارد برای پیشوند افعال (می / نمی) و پسوندهای جمع (ها / های / تر / ترین)
    res = re.sub(r"\b(می|نمی)\s+([آ-ی]{2,})", r"\1\u200c\2", res)
    res = re.sub(r"([آ-ی]{2,})\s+(ها|های|هایی|تر|ترین)\b", r"\1\u200c\2", res)
    res = re.sub(r"[ \t]{2,}", " ", res)
    return res.strip()


def ensure_persian_start(headline: str, category_id: str = "technology") -> str:
    """
    تضمین شروع تیتر با کلمه فارسی تا الگوریتم BiDi تلگرام جهت پاراگراف را چپ‌به‌راست نکند.
    اگر تیتر با نام برند انگلیسی شروع شده باشد، پیشوند فارسی مناسب به ابتدای آن می‌افزاید.
    """
    cleaned = persian_orthography_polish(headline).lstrip("•-–—:*# ")
    if not cleaned:
        return ""
    first_char = cleaned[0]
    if "A" <= first_char <= "Z" or "a" <= first_char <= "z":
        prefixes = {
            "gaming": "در دنیای گیمینگ؛ ",
            "hardware": "بررسی سخت‌افزاری؛ ",
            "gadgets": "معرفی و بررسی؛ ",
            "cinema": "در دنیای سینما؛ ",
            "television": "در دنیای سریال؛ ",
        }
        prefix = prefixes.get(category_id, "گزارش تازه؛ ")
        return f"{prefix}{cleaned}"
    return cleaned


def _isolate_latin_runs_in_plain_text(plain_text: str) -> str:
    """
    ایزوله‌سازی عبارت‌های انگلیسی/مدل‌های فنی در یک گره متنی خالص (قبل از html.escape)
    تا نه تگ‌های HTML آسیب ببینند و نه Entityهایی مثل &amp; شکسته شوند.
    """
    if not plain_text:
        return ""
    pattern = re.compile(
        r"([A-Za-z][A-Za-z0-9\s\.\-\+\_\:\'\/\&]*[A-Za-z0-9]|[A-Za-z]{2,})"
    )
    return pattern.sub(rf"{RLM}{LRI}\1{PDI}{RLM}", plain_text)


def sanitize_and_fix_bidi_html(raw_html: str) -> str:
    """
    پارس درختی DOM با BeautifulSoup:
    1. فقط تگ‌های مجاز تلگرام را نگه می‌دارد و تگ‌های باز را می‌بندد.
    2. ایزوله‌سازی BiDi را صرفاً روی گره‌های متنی (NavigableString) اعمال می‌کند.
    3. در ابتدای هر خط، کاراکتر نامرئی RLM را بیرون یا بلافاصله بعد از تگ بلاک قرار می‌دهد.
    """
    if not raw_html:
        return ""

    text = re.sub(r"<\s*br\s*/?\s*>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*p[^>]*>", "", text, flags=re.IGNORECASE)

    soup = BeautifulSoup(text, "html.parser")

    def _render_node(node) -> str:
        if isinstance(node, NavigableString):
            polished = persian_orthography_polish(str(node))
            isolated = _isolate_latin_runs_in_plain_text(polished)
            return html.escape(isolated, quote=False)
        if isinstance(node, Tag):
            inner = "".join(_render_node(c) for c in node.children)
            tname = node.name.lower()
            if tname in ALLOWED_TELEGRAM_TAGS:
                if tname == "a":
                    href = validate_safe_external_url(node.get("href", ""))
                    if href:
                        return f'<a href="{html.escape(href, quote=True)}">{inner}</a>'
                    return inner
                return f"<{tname}>{inner}</{tname}>"
            return inner
        return ""

    rendered = "".join(_render_node(c) for c in soup.contents)
    lines = rendered.split("\n")
    rtl_lines = []
    for line in lines:
        if not line.strip():
            rtl_lines.append("")
            continue
        # اگر خط با تگ بازکننده بلاک مثل <blockquote> شروع شود، RLM را داخل تگ قرار بده
        if line.lstrip().startswith("<blockquote>"):
            fixed = line.lstrip().replace("<blockquote>", f"<blockquote>{RLM}", 1)
        else:
            fixed = f"{RLM}{line}"
        rtl_lines.append(fixed)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(rtl_lines)).strip()


def visible_text_length(html_text: str) -> int:
    """محاسبه طول متن قابل مشاهده در تلگرام (بدون احتساب تگ‌های HTML)"""
    soup = BeautifulSoup(html_text or "", "html.parser")
    return len(soup.get_text())


def normalize_for_matching(text: str) -> str:
    if not text:
        return ""
    s = text.casefold().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    s = re.sub(r"[^\wآ-ی\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    t_norm = normalize_for_matching(text)
    k_norm = normalize_for_matching(keyword)
    if not k_norm:
        return False
    if k_norm.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(k_norm)}(?![a-z0-9])"
        return re.search(pattern, t_norm) is not None
    return k_norm in t_norm


# ==============================================================================
# ۴. لایه دیتابیس SQLite، مهاجرت خودکار Schema و مدیریت چرخه حیات (Database)
# ==============================================================================
def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_and_migrate_db():
    """ایجاد جداول و مهاجرت ایمن ستون‌ها بدون حذف یا بازنویسی داده‌های قبلی"""
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """CREATE TABLE IF NOT EXISTS news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        canonical_url TEXT,
        title_hash TEXT,
        category TEXT,
        source TEXT,
        publisher_domain TEXT,
        source_tier INTEGER DEFAULT 2,
        raw_title TEXT,
        raw_text TEXT,
        full_article_text TEXT,
        image_url TEXT,
        video_url TEXT,
        has_video_or_audio INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        is_breaking_candidate INTEGER DEFAULT 0,
        source_count INTEGER DEFAULT 1,
        newsworthiness_score REAL DEFAULT 0.0,
        qa_score INTEGER DEFAULT 0,
        embedding_json TEXT,
        topic_fingerprint TEXT,
        published_category TEXT,
        published_headline TEXT,
        published_summary TEXT,
        verification_status TEXT,
        related_entity TEXT,
        telegram_message_id INTEGER,
        source_published_at TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        published_at TIMESTAMP
    )"""
    )

    # مهاجرت ایمن برای دیتابیس‌های موجود از نسخه‌های قبلی
    c.execute("PRAGMA table_info(news_items)")
    existing_cols = {row[1] for row in c.fetchall()}
    required_migrations = {
        "canonical_url": "TEXT",
        "title_hash": "TEXT",
        "publisher_domain": "TEXT",
        "source_tier": "INTEGER DEFAULT 2",
        "full_article_text": "TEXT",
        "video_url": "TEXT",
        "has_video_or_audio": "INTEGER DEFAULT 0",
        "is_breaking_candidate": "INTEGER DEFAULT 0",
        "source_count": "INTEGER DEFAULT 1",
        "newsworthiness_score": "REAL DEFAULT 0.0",
        "qa_score": "INTEGER DEFAULT 0",
        "embedding_json": "TEXT",
        "topic_fingerprint": "TEXT",
        "published_category": "TEXT",
        "published_headline": "TEXT",
        "published_summary": "TEXT",
        "verification_status": "TEXT",
        "related_entity": "TEXT",
        "telegram_message_id": "INTEGER",
        "source_published_at": "TEXT",
        "updated_at": "TIMESTAMP",
    }
    for col_name, col_def in required_migrations.items():
        if col_name not in existing_cols:
            c.execute(f"ALTER TABLE news_items ADD COLUMN {col_name} {col_def}")

    c.execute(
        """CREATE TABLE IF NOT EXISTS source_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER NOT NULL,
        publisher_domain TEXT NOT NULL,
        feed_url TEXT,
        article_url TEXT,
        observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(news_item_id, publisher_domain)
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS feed_health (
        feed_url TEXT PRIMARY KEY,
        etag TEXT,
        last_modified TEXT,
        consecutive_failures INTEGER DEFAULT 0,
        last_http_status INTEGER DEFAULT 200,
        last_checked_at TIMESTAMP,
        next_fetch_at REAL DEFAULT 0.0
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS ai_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT,
        model TEXT,
        request_date TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        status TEXT,
        elapsed_ms INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS publish_outbox (
        news_item_id INTEGER PRIMARY KEY,
        telegram_message_id INTEGER,
        published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS corrections_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER,
        telegram_message_id INTEGER,
        correction_text TEXT,
        corrected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS hype_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_name TEXT,
        category TEXT,
        score REAL DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS post_likes (
        post_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (post_id, user_id)
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS bot_metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )"""
    )

    c.execute("CREATE INDEX IF NOT EXISTS idx_news_status ON news_items(status, discovered_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_canonical ON news_items(canonical_url)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_title_hash ON news_items(title_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_date ON ai_usage_logs(provider, request_date)")

    # بازیابی خبرهایی که در زمان ری‌استارت ناگهانی در وضعیت processing مانده‌اند
    c.execute("UPDATE news_items SET status = 'pending' WHERE status IN ('processing', 'publishing')")
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


def log_ai_usage(provider: str, model: str, in_tok: int, out_tok: int, status: str, elapsed_ms: int):
    today = now_tehran().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO ai_usage_logs
        (provider, model, request_date, input_tokens, output_tokens, status, elapsed_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (provider, model, today, in_tok, out_tok, status, elapsed_ms),
    )
    conn.commit()
    conn.close()


def get_provider_daily_calls(provider: str) -> int:
    today = now_tehran().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM ai_usage_logs WHERE provider = ? AND request_date = ?",
        (provider, today),
    )
    cnt = c.fetchone()[0]
    conn.close()
    return cnt


# ==============================================================================
# ۵. تشخیص اخبار تکراری ۵ لایه‌ای و امتیازدهی ارزش خبری (Deduplication & Scoring)
# ==============================================================================
def compute_title_hash(title: str) -> str:
    norm = normalize_for_matching(title)
    return hashlib.blake2b(norm.encode("utf-8"), digest_size=12).hexdigest()


def compute_stable_embedding(text: str, dims: int = 128) -> list[float]:
    """بردار پایدار blake2b از تک‌واژه‌ها و دوتایی‌های کلمه"""
    vec = [0.0] * dims
    tokens = re.findall(r"[a-z0-9آ-ی]{2,}", normalize_for_matching(text))
    if not tokens:
        return vec
    features = tokens + [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    for feat in features:
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        val = int.from_bytes(digest, "big")
        idx = val % dims
        sign = 1.0 if ((val >> 8) & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 4) for x in vec]


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    return sum(a * b for a, b in zip(v1, v2))


KEY_ENTITIES = [
    "gta vi",
    "gta 6",
    "ps5 pro",
    "ps6",
    "playstation",
    "xbox",
    "switch 2",
    "nintendo",
    "steam",
    "valve",
    "nvidia",
    "rtx 5090",
    "rtx 5080",
    "amd",
    "intel",
    "apple",
    "iphone",
    "openai",
    "chatgpt",
    "gemini",
    "spacex",
    "starship",
    "netflix",
    "HBO",
]

BREAKING_ACTION_VERBS = [
    "officially announced",
    "announces",
    "confirmed",
    "delayed",
    "release date",
    "launches",
    "launched",
    "unveiled",
    "revealed",
    "cancelled",
    "canceled",
    "acquires",
    "تأیید شد",
    "معرفی شد",
    "به تعویق افتاد",
]


def extract_matched_entities(text: str) -> set[str]:
    return {ent for ent in KEY_ENTITIES if contains_keyword(text, ent)}


def detect_breaking_signal(title: str, text: str, tier: int, source_count: int) -> bool:
    combined = f"{title} {text}"
    has_entity = bool(extract_matched_entities(combined))
    has_verb = any(contains_keyword(combined, v) for v in BREAKING_ACTION_VERBS)
    has_authority = (tier == 1) or (tier == 2 and source_count >= 2)
    return has_entity and has_verb and has_authority


def compute_newsworthiness_score(item: dict) -> float:
    """
    امتیازدهی ارزش خبری در مقیاس ۰ تا ۱۰۰ مطابق ابعاد ۷گانه استاندارد JSON:
    - source_quality (20)
    - relevance (20)
    - impact (20)
    - timeliness (15)
    - novelty / independent corroboration (10)
    - information_value & media richness (10)
    - editorial_confidence (5)
    """
    tier = item.get("source_tier", 2)
    src_cnt = item.get("source_count", 1)
    title = item.get("raw_title", "")
    body = item.get("raw_text", "")
    combined = f"{title} {body}"

    # 1. Source Quality (0-20)
    source_quality = 20.0 if tier == 1 else (16.0 if tier == 2 else 10.0)

    # 2. Relevance to Channel Audience (0-20)
    matched_ents = extract_matched_entities(combined)
    relevance = min(20.0, 10.0 + len(matched_ents) * 5.0)

    # 3. Impact (0-20)
    has_action = any(contains_keyword(combined, v) for v in BREAKING_ACTION_VERBS)
    has_numbers = bool(re.search(r"\b(\d+\s*%|\$\d+|\d{4})\b", combined))
    impact = 10.0 + (6.0 if has_action else 0.0) + (4.0 if has_numbers else 0.0)

    # 4. Timeliness (0-15)
    timeliness = 13.0
    pub_str = item.get("source_published_at") or ""
    if pub_str:
        try:
            dt = datetime.fromisoformat(pub_str)
            hours_old = max(0.0, (now_utc() - dt).total_seconds() / 3600.0)
            timeliness = max(2.0, 15.0 - (hours_old * 0.4))
        except Exception:
            pass

    # 5. Novelty & Corroboration (0-10)
    novelty = min(10.0, 5.0 + (src_cnt - 1) * 2.5)

    # 6. Information & Media Value (0-10)
    info_val = 0.0
    if len(body) >= 300:
        info_val += 4.0
    if item.get("image_url"):
        info_val += 3.0
    if item.get("has_video_or_audio"):
        info_val += 3.0

    # 7. Editorial Confidence (0-5)
    confidence = 5.0 if (tier == 1 or src_cnt >= 2) else 3.5

    total = source_quality + relevance + impact + timeliness + novelty + info_val + confidence
    return round(min(100.0, total), 2)


# ==============================================================================
# ۶. جمع‌آوری RSS، پایش سلامت فیدها و استخراج مقاله کامل (RSS & Extractor)
# ==============================================================================
async def fetch_single_feed(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    feed_url: str,
    default_cat: str,
    tier: int,
    interval_min: int,
):
    safe_feed_url = validate_safe_external_url(feed_url)
    if not safe_feed_url:
        return

    now_ts = time.time()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT etag, last_modified, consecutive_failures, next_fetch_at FROM feed_health WHERE feed_url = ?",
        (safe_feed_url,),
    )
    row = c.fetchone()
    conn.close()

    if row and row[3] and now_ts < row[3]:
        return

    headers = dict(UA_HEADERS)
    if row:
        if row[0]:
            headers["If-None-Match"] = row[0]
        if row[1]:
            headers["If-Modified-Since"] = row[1]

    async with sem:
        try:
            async with session.get(safe_feed_url, headers=headers, timeout=14) as resp:
                status_code = resp.status
                if status_code == 304:
                    conn = get_db_connection()
                    conn.execute(
                        """UPDATE feed_health
                           SET consecutive_failures = 0, last_http_status = 304,
                               last_checked_at = CURRENT_TIMESTAMP, next_fetch_at = ?
                           WHERE feed_url = ?""",
                        (now_ts + interval_min * 60, safe_feed_url),
                    )
                    conn.commit()
                    conn.close()
                    return

                if status_code != 200:
                    raise RuntimeError(f"HTTP {status_code}")

                new_etag = resp.headers.get("ETag", "")
                new_lm = resp.headers.get("Last-Modified", "")
                raw_bytes = await resp.content.read(2_500_000)
                xml_text = raw_bytes.decode("utf-8", errors="ignore")
        except Exception:
            fails = (row[2] + 1) if row else 1
            backoff_sec = min(7200, interval_min * 60 * (2 if fails >= 3 else 1))
            conn = get_db_connection()
            conn.execute(
                """INSERT OR REPLACE INTO feed_health
                   (feed_url, etag, last_modified, consecutive_failures, last_http_status, last_checked_at, next_fetch_at)
                   VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP, ?)""",
                (safe_feed_url, row[0] if row else "", row[1] if row else "", fails, now_ts + backoff_sec),
            )
            conn.commit()
            conn.close()
            return

    feed = await asyncio.to_thread(feedparser.parse, xml_text)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """INSERT OR REPLACE INTO feed_health
           (feed_url, etag, last_modified, consecutive_failures, last_http_status, last_checked_at, next_fetch_at)
           VALUES (?, ?, ?, 0, 200, CURRENT_TIMESTAMP, ?)""",
        (safe_feed_url, new_etag, new_lm, now_ts + interval_min * 60),
    )

    c.execute(
        """SELECT id, canonical_url, title_hash, publisher_domain, source_tier, embedding_json
           FROM news_items
           WHERE discovered_at >= datetime('now', '-48 hours')"""
    )
    recent_rows = c.fetchall()
    recent_items = []
    for r in recent_rows:
        try:
            recent_items.append(
                {
                    "id": r[0],
                    "canonical_url": r[1],
                    "title_hash": r[2],
                    "domain": r[3],
                    "tier": r[4],
                    "emb": json.loads(r[5]) if r[5] else [],
                }
            )
        except Exception:
            pass

    for entry in feed.entries[:8]:
        raw_link = getattr(entry, "link", "") or ""
        canonical = normalize_canonical_url(raw_link)
        title = html.unescape(getattr(entry, "title", "") or "").strip()
        if not canonical or len(title) < 12:
            continue

        pub_dt = parse_feed_timestamp_utc(entry)
        if is_entry_too_old(pub_dt):
            continue

        t_hash = compute_title_hash(title)
        summary_html = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        clean_summary = BeautifulSoup(summary_html, "html.parser").get_text(" ", strip=True)[:1000]
        if len(f"{title} {clean_summary}".strip()) < 45:
            continue

        domain = extract_domain(canonical)
        emb = compute_stable_embedding(f"{title} {clean_summary}")

        # لایه ۱ تا ۴ حذف تکراری و ثبت ناشر مستقل در source_observations
        matched_id = None
        for rec in recent_items:
            if rec["canonical_url"] == canonical or rec["title_hash"] == t_hash:
                matched_id = rec["id"]
                break
            if cosine_similarity(emb, rec["emb"]) >= 0.73:
                matched_id = rec["id"]
                break

        if matched_id is not None:
            c.execute(
                """INSERT OR IGNORE INTO source_observations
                   (news_item_id, publisher_domain, feed_url, article_url)
                   VALUES (?, ?, ?, ?)""",
                (matched_id, domain, safe_feed_url, canonical),
            )
            c.execute(
                """UPDATE news_items
                   SET source_count = (SELECT COUNT(DISTINCT publisher_domain) FROM source_observations WHERE news_item_id = ?),
                       source_tier = MIN(source_tier, ?),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (matched_id, tier, matched_id),
            )
            continue

        img_url = ""
        if getattr(entry, "media_content", None):
            img_url = validate_safe_external_url(entry.media_content[0].get("url", ""))
        if not img_url and getattr(entry, "media_thumbnail", None):
            img_url = validate_safe_external_url(entry.media_thumbnail[0].get("url", ""))
        if not img_url:
            m_img = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', summary_html, re.I)
            if m_img:
                img_url = validate_safe_external_url(m_img.group(1))

        has_av = (
            1
            if re.search(r"\b(trailer|showcase|gameplay|podcast|video|teaser)\b", f"{title} {clean_summary}", re.I)
            else 0
        )
        is_brk = 1 if detect_breaking_signal(title, clean_summary, tier, 1) else 0
        pub_iso = pub_dt.isoformat() if pub_dt else now_utc().isoformat()

        candidate_dict = {
            "source_tier": tier,
            "source_count": 1,
            "raw_title": title,
            "raw_text": f"{title}\n{clean_summary}",
            "image_url": img_url,
            "has_video_or_audio": has_av,
            "source_published_at": pub_iso,
        }
        nw_score = compute_newsworthiness_score(candidate_dict)

        c.execute(
            """INSERT OR IGNORE INTO news_items
               (url, canonical_url, title_hash, category, source, publisher_domain, source_tier,
                raw_title, raw_text, image_url, has_video_or_audio, status, is_breaking_candidate,
                source_count, newsworthiness_score, embedding_json, source_published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 1, ?, ?, ?)""",
            (
                canonical,
                canonical,
                t_hash,
                default_cat,
                safe_feed_url,
                domain,
                tier,
                title,
                f"{title}\n{clean_summary}",
                img_url,
                has_av,
                is_brk,
                nw_score,
                json.dumps(emb),
                pub_iso,
            ),
        )
        if c.lastrowid:
            new_id = c.lastrowid
            c.execute(
                """INSERT OR IGNORE INTO source_observations
                   (news_item_id, publisher_domain, feed_url, article_url)
                   VALUES (?, ?, ?, ?)""",
                (new_id, domain, safe_feed_url, canonical),
            )
            recent_items.append(
                {
                    "id": new_id,
                    "canonical_url": canonical,
                    "title_hash": t_hash,
                    "domain": domain,
                    "tier": tier,
                    "emb": emb,
                }
            )

    conn.commit()
    conn.close()


async def collect_all_feeds(session: aiohttp.ClientSession):
    sem = asyncio.Semaphore(10)
    tasks = [
        fetch_single_feed(session, sem, url, cat, tier, interval)
        for url, cat, tier, interval in RSS_SOURCES
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


_NOISE_RE = re.compile(
    r"cookie|subscribe|newsletter|sign up|all rights reserved|advertisement|privacy policy|terms of use",
    re.I,
)


def _normalize_video_url(url: str) -> str:
    safe = validate_safe_external_url(url)
    if not safe:
        return ""
    m = re.search(r"youtube\.com/embed/([\w-]{6,})", safe)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return safe


async def fetch_full_article_and_media(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str, str]:
    """استخراج ایمن متن کامل مقاله، ویدیو و تصویر اصلی با محدودیت حجم دانلود"""
    safe_url = validate_safe_external_url(url)
    if not safe_url:
        return "", "", ""
    try:
        async with session.get(safe_url, timeout=12, headers=UA_HEADERS) as resp:
            if resp.status != 200 or "html" not in resp.headers.get("Content-Type", "").lower():
                return "", "", ""
            raw_bytes = await resp.content.read(2_000_000)
            html_page = raw_bytes.decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_page, "html.parser")

            og_img = ""
            img_tag = soup.find("meta", property="og:image")
            if img_tag and img_tag.get("content"):
                og_img = validate_safe_external_url(img_tag["content"])

            video_url = ""
            for prop in ("og:video:url", "og:video", "og:video:secure_url"):
                v_tag = soup.find("meta", property=prop)
                if v_tag and v_tag.get("content"):
                    video_url = _normalize_video_url(v_tag["content"])
                    if video_url:
                        break
            if not video_url:
                iframe = soup.find(
                    "iframe", src=re.compile(r"youtube\.com/embed|youtu\.be|player\.vimeo")
                )
                if iframe:
                    src = iframe.get("src", "")
                    video_url = _normalize_video_url(("https:" + src) if src.startswith("//") else src)

            for tag in soup(
                ["script", "style", "nav", "aside", "footer", "form", "header", "noscript"]
            ):
                tag.decompose()
            container = soup.find("article") or soup.find("main") or soup
            paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
            paras = [p for p in paras if len(p) > 45 and not _NOISE_RE.search(p)]
            body = " ".join(paras)[:ARTICLE_MAX_CHARS]
            return body, video_url, og_img
    except Exception:
        return "", "", ""


# ==============================================================================
# ۷. اسکیماهای Pydantic و موتور هوش مصنوعی با مدیریت سهمیه (AI Editor)
# ==============================================================================
VerificationType = Literal[
    "تأیید رسمی",
    "گزارش تأییدشده چندمنبعی",
    "گزارش رسانه‌ای",
    "پیش‌بینی تحلیلگران",
    "شایعه و گزارش غیررسمی",
]


class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="Exact ID of the candidate")
    category_id: Literal[
        "gaming",
        "technology",
        "hardware",
        "gadgets",
        "cinema",
        "television",
        "internet_culture",
    ]
    verification_status: VerificationType
    is_breaking: bool = Field(default=False)
    headline_persian: str = Field(
        description="Informative, non-clickbait Persian headline MUST start with a Persian word, no emojis, no HTML"
    )
    summary_persian: str = Field(
        description="3 to 5 rich, natural Persian sentences (inverted pyramid) grounded strictly in the provided text. Wrap 1 to 3 key facts/numbers in <b>...</b>."
    )
    key_points_persian: list[str] = Field(
        description="2 to 3 structured Persian bullets (e.g., 'جزئیات فنی: ...', 'پلتفرم و زمان عرضه: ...', 'منبع گزارش: ...')"
    )
    why_it_matters_persian: str = Field(
        default="",
        description="1 concise Persian sentence explaining why this matters or relevant context supported by the source, or empty string",
    )
    media_note_persian: str = Field(
        default="",
        description="If has_video_or_audio is true, 1 short Persian sentence describing the video/trailer for deaf/accessibility users; else empty",
    )
    image_alt_persian: str = Field(
        default="",
        description="1 short Persian phrase describing the subject for screen-reader users; else empty",
    )
    topic_hashtags: list[str] = Field(description="2 to 3 relevant Persian hashtags")
    topic_fingerprint: str = Field(description="Concise English event summary for deduplication")
    related_entity: str = Field(default="", description="Main English game, product, or company name")
    hype_score: int = Field(default=6, ge=1, le=10)


class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]


class DailyDigestOutput(BaseModel):
    top_story_highlight: str
    gaming_highlights: list[str]
    tech_hardware_highlights: list[str]
    cinema_tv_highlights: list[str]
    editorial_takeaway: str


class MemePick(BaseModel):
    chosen_index: int
    joke_persian: str = ""
    context_persian: str = ""
    is_safe_and_funny: bool = False


async def call_gemini_json(prompt: str, schema_cls, temperature: float = 0.2):
    now_ts = time.time()
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            cd_key = f"gemini:{key_idx}:{model_name}"
            if provider_cooldowns.get(cd_key, 0) > now_ts:
                continue
            t0 = time.monotonic()
            try:
                resp = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema_cls,
                        temperature=temperature,
                    ),
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                usage = getattr(resp, "usage_metadata", None)
                in_tok = getattr(usage, "prompt_token_count", 0) or 0
                out_tok = getattr(usage, "candidates_token_count", 0) or 0
                log_ai_usage("gemini", model_name, in_tok, out_tok, "success", elapsed)
                raw = json.loads(resp.text)
                return schema_cls.model_validate(raw)
            except Exception as e:
                elapsed = int((time.monotonic() - t0) * 1000)
                err_str = redact_secrets(str(e))
                log_ai_usage("gemini", model_name, 0, 0, f"error:{err_str[:60]}", elapsed)
                if "429" in err_str or "ResourceExhausted" in err_str:
                    provider_cooldowns[cd_key] = now_ts + 1800
                print(f"⚠️ خطا در Gemini ({model_name} | کلید #{key_idx}): {err_str[:130]}")
    return None


async def call_openai_compat_json(
    provider: str,
    base_url: str,
    keys: list[str],
    models: list[str],
    daily_limit: int,
    prompt: str,
    schema_cls,
    temperature: float = 0.2,
):
    if not keys or get_provider_daily_calls(provider) >= daily_limit:
        return None
    now_ts = time.time()
    schema_hint = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
    for key_idx, api_key in enumerate(keys, start=1):
        http_client = httpx.AsyncClient(http2=False, trust_env=False, timeout=40.0)
        client = AsyncOpenAI(
            api_key=api_key, base_url=sanitize_plain_url(base_url), http_client=http_client
        )
        try:
            for model_name in models:
                cd_key = f"{provider}:{key_idx}:{model_name}"
                if provider_cooldowns.get(cd_key, 0) > now_ts:
                    continue
                t0 = time.monotonic()
                try:
                    comp = await client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": f"Return ONLY valid JSON strictly matching this JSON Schema:\n{schema_hint}",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                        temperature=temperature,
                    )
                    elapsed = int((time.monotonic() - t0) * 1000)
                    u = getattr(comp, "usage", None)
                    in_tok = getattr(u, "prompt_tokens", 0) or 0
                    out_tok = getattr(u, "completion_tokens", 0) or 0
                    log_ai_usage(provider, model_name, in_tok, out_tok, "success", elapsed)
                    content = comp.choices[0].message.content or "{}"
                    content = re.sub(r"^```json\s*|\s*```$", "", content.strip())
                    return schema_cls.model_validate(json.loads(content))
                except Exception as e:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    err_str = redact_secrets(str(e))
                    log_ai_usage(provider, model_name, 0, 0, f"error:{err_str[:60]}", elapsed)
                    if "429" in err_str:
                        provider_cooldowns[cd_key] = now_ts + 1800
                    print(f"⚠️ خطا در {provider} ({model_name} | کلید #{key_idx}): {err_str[:130]}")
        finally:
            await http_client.aclose()
    return None


async def ask_structured_ai(prompt: str, schema_cls, temperature: float = 0.2):
    res = await call_gemini_json(prompt, schema_cls, temperature)
    if res:
        return res
    res = await call_openai_compat_json(
        "groq",
        "https://api.groq.com/openai/v1",
        GROQ_API_KEYS,
        GROQ_MODELS,
        GROQ_DAILY_CALL_LIMIT,
        prompt,
        schema_cls,
        temperature,
    )
    if res:
        return res
    res = await call_openai_compat_json(
        "openrouter",
        "https://openrouter.ai/api/v1",
        OPENROUTER_API_KEYS,
        OPENROUTER_MODELS,
        OPENROUTER_DAILY_CALL_LIMIT,
        prompt,
        schema_cls,
        temperature,
    )
    return res


# ==============================================================================
# ۸. سیستم راستی‌آزمایی، ضدتوهم و دروازه کنترل کیفیت قطعی (QA & Verification Gate)
# ==============================================================================
RUMOR_INDICATORS = [
    "rumor",
    "rumour",
    "leak",
    "leaked",
    "allegedly",
    "unconfirmed",
    "speculation",
    "insider claims",
    "شایعه",
    "لیک",
]
ANALYST_INDICATORS = [
    "analyst",
    "forecast",
    "predicts",
    "projection",
    "estimated",
    "sensor tower",
    "circana",
    "dfc intelligence",
    "پیش‌بینی",
    "تحلیلگر",
]


def enforce_evidence_based_verification(
    ai_status: str, orig_item: dict
) -> VerificationType:
    """
    تعیین و اصلاح وضعیت اعتبار خبر بر اساس شواهد واقعی (سطح منبع، تعداد ناشران مستقل و واژگان متن)
    تا مدل نتواند یک شایعه یا گزارش رسانه‌ای را به اشتباه «تأیید رسمی» اعلام کند.
    """
    tier = orig_item.get("source_tier", 2)
    src_cnt = orig_item.get("source_count", 1)
    full_text = f"{orig_item.get('raw_title', '')} {orig_item.get('full_article', '')}".casefold()

    if any(contains_keyword(full_text, w) for w in ANALYST_INDICATORS):
        return "پیش‌بینی تحلیلگران"
    if any(contains_keyword(full_text, w) for w in RUMOR_INDICATORS) and tier > 1:
        return "شایعه و گزارش غیررسمی"

    if ai_status == "تأیید رسمی":
        if tier == 1 or (
            tier == 2
            and any(
                contains_keyword(full_text, w)
                for w in ["officially announced", "official statement", "confirmed by", "رسماً اعلام کرد"]
            )
        ):
            return "تأیید رسمی"
        return "گزارش تأییدشده چندمنبعی" if src_cnt >= 2 else "گزارش رسانه‌ای"

    if src_cnt >= 2 and ai_status in ("گزارش رسانه‌ای", "گزارش تأییدشده چندمنبعی"):
        return "گزارش تأییدشده چندمنبعی"

    if ai_status in (
        "تأیید رسمی",
        "گزارش تأییدشده چندمنبعی",
        "گزارش رسانه‌ای",
        "پیش‌بینی تحلیلگران",
        "شایعه و گزارش غیررسمی",
    ):
        return ai_status  # type: ignore
    return "گزارش رسانه‌ای"


PERSIAN_TO_ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def verify_numbers_against_source(persian_text: str, source_text: str) -> tuple[bool, str]:
    """
    بررسی ضدتوهم اعداد: اگر در متن فارسی درصد یا سال مشخصی ادعا شده باشد که در متن منبع نیست،
    هشدار عدم تطابق برمی‌گرداند.
    """
    norm_fa = persian_text.translate(PERSIAN_TO_ASCII_DIGITS)
    norm_src = source_text.translate(PERSIAN_TO_ASCII_DIGITS)

    fa_percentages = set(re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:%|درصد)", norm_fa))
    src_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", norm_src))

    for pct in fa_percentages:
        if pct not in src_numbers:
            return False, f"Unverified percentage {pct}% not found in source"

    fa_years = set(re.findall(r"\b(202[4-9]|203\d)\b", norm_fa))
    for yr in fa_years:
        # سال ۲۰۲۶ و ۲۰۲۷ ممکن است از تبدیل عبارت next year حاصل شده باشند؛ سایر سال‌ها باید در منبع باشند
        if yr not in ("2026", "2027") and yr not in src_numbers:
            return False, f"Unverified year {yr} not found in source"

    return True, "OK"


def evaluate_and_gate_news_item(
    sel: SelectedNewsItem, orig_item: dict
) -> tuple[int, bool, str]:
    """
    دروازه کنترل کیفیت ۹ بعدی مطابق استاندارد JSON (مقیاس ۰ تا ۱۰۰؛ حداقل امتیاز انتشار: ۸۰):
    - factual_accuracy (25)
    - source_and_attribution (15)
    - headline_quality (10)
    - writing_quality (15)
    - information_value (10)
    - readability (10)
    - originality (5)
    - accessibility (5)
    - formatting (5)
    """
    source_blob = f"{orig_item.get('raw_title', '')} {orig_item.get('full_article', '')}"
    combined_fa = f"{sel.headline_persian} {sel.summary_persian} {' '.join(sel.key_points_persian)}"

    # 1. Factual Accuracy (0-25)
    nums_ok, reason = verify_numbers_against_source(combined_fa, source_blob)
    if not nums_ok:
        return 0, False, f"BLOCKING: {reason}"
    factual_score = 24

    # 2. Source & Attribution (0-15)
    sel.verification_status = enforce_evidence_based_verification(
        sel.verification_status, orig_item
    )
    if sel.verification_status in ("شایعه و گزارش غیررسمی", "پیش‌بینی تحلیلگران"):
        sel.is_breaking = False
    attr_score = 14

    # 3. Headline Quality (0-10)
    sel.headline_persian = ensure_persian_start(sel.headline_persian, sel.category_id)
    hl_len = len(sel.headline_persian)
    if hl_len < 15 or hl_len > 145:
        return 0, False, "BLOCKING: Headline length out of bounds"
    headline_score = 9

    # 4. Writing Quality (0-15)
    sel.summary_persian = persian_orthography_polish(sel.summary_persian)
    if len(sel.summary_persian) < 90:
        return 0, False, "BLOCKING: Summary too thin"
    writing_score = 14

    # 5. Information Value (0-10)
    valid_bullets = [b.strip() for b in sel.key_points_persian if len(b.strip()) >= 8]
    if len(valid_bullets) < 2:
        return 0, False, "BLOCKING: Insufficient key points"
    info_score = 9

    # 6. Readability (0-10)
    readability_score = 9 if len(sel.summary_persian) <= 750 else 7

    # 7. Originality (0-5)
    orig_score = 5 if sel.why_it_matters_persian else 4

    # 8. Accessibility (0-5)
    acc_score = 5 if (sel.image_alt_persian or sel.media_note_persian) else 4

    # 9. Formatting (0-5)
    fmt_score = 5

    total_qa = (
        factual_score
        + attr_score
        + headline_score
        + writing_score
        + info_score
        + readability_score
        + orig_score
        + acc_score
        + fmt_score
    )
    passed = total_qa >= MIN_QA_PUBLISH_SCORE
    return total_qa, passed, "PASSED" if passed else f"Score {total_qa} < {MIN_QA_PUBLISH_SCORE}"


# ==============================================================================
# ۹. قالب‌بندی نهایی تلگرام، مدیریت طول کپشن عکس و انتشار امن (Telegram Publisher)
# ==============================================================================
def format_newsroom_post(
    sel: SelectedNewsItem, publisher_domain: str, include_optional: bool = True
) -> str:
    status_badges = {
        "تأیید رسمی": "✅ تأیید رسمی",
        "گزارش تأییدشده چندمنبعی": "☑️ گزارش تأییدشده چندمنبعی",
        "گزارش رسانه‌ای": "📰 گزارش رسانه‌ای",
        "پیش‌بینی تحلیلگران": "📊 پیش‌بینی تحلیلگران",
        "شایعه و گزارش غیررسمی": "⚠️ شایعه / گزارش غیررسمی",
    }
    cat_meta = CATEGORY_METADATA.get(sel.category_id, CATEGORY_METADATA["technology"])
    badge = status_badges.get(sel.verification_status, "📰 گزارش رسانه‌ای")

    urg_prefix = "🚨 <b>خبر فوری</b>\n" if sel.is_breaking else ""
    lines = [
        f"{urg_prefix}{cat_meta['icon']} <b>{sel.headline_persian}</b>",
        f"📂 {cat_meta['fa']} | {badge} | 🏢 منبع: {publisher_domain}",
        "",
        f"<blockquote>{sel.summary_persian}</blockquote>",
    ]

    bullets = [b.lstrip("•-🔹 ").strip() for b in sel.key_points_persian[:3] if b.strip()]
    if bullets:
        lines.append("")
        for b in bullets:
            lines.append(f"🔹 {b}")

    if include_optional and sel.why_it_matters_persian.strip():
        lines.append(f"\n💡 <b>اهمیت خبر:</b> {sel.why_it_matters_persian.strip()}")

    if include_optional and sel.media_note_persian.strip():
        lines.append(f"\n🎬 <b>شرح رسانه همراه:</b> <i>{sel.media_note_persian.strip()}</i>")

    tags = [cat_meta["tag"]]
    for t in sel.topic_hashtags[:2]:
        clean_t = "#" + re.sub(r"[^\wآ-ی]", "_", t.lstrip("#").strip())
        if len(clean_t) > 2 and clean_t not in tags:
            tags.append(clean_t)

    lines.append(f"\n🏷 {' '.join(tags)}{CHANNEL_SIGNATURE}")
    return sanitize_and_fix_bidi_html("\n".join(lines))


def fit_post_for_telegram_photo(sel: SelectedNewsItem, publisher_domain: str) -> str:
    """تنظیم هوشمند طول پست زیر ۱,۰۱۰ کاراکتر قابل مشاهده تا همیشه با عکس واقعی ارسال شود"""
    full_post = format_newsroom_post(sel, publisher_domain, include_optional=True)
    if visible_text_length(full_post) <= 1010:
        return full_post
    compact_post = format_newsroom_post(sel, publisher_domain, include_optional=False)
    if visible_text_length(compact_post) <= 1010:
        return compact_post
    # در صورت طولانی بودن خلاصه، تنها ۲ بولت اول حفظ می‌شود
    sel_copy = sel.model_copy(deep=True)
    sel_copy.key_points_persian = sel_copy.key_points_persian[:2]
    return format_newsroom_post(sel_copy, publisher_domain, include_optional=False)


async def download_image_safely(
    session: aiohttp.ClientSession, url: str, filename: str
) -> str:
    safe_url = validate_safe_external_url(url)
    if not safe_url:
        return ""
    path = os.path.join("temp_media", filename)
    try:
        async with session.get(safe_url, timeout=14, headers=UA_HEADERS) as resp:
            if resp.status != 200:
                return ""
            ctype = resp.headers.get("Content-Type", "").lower()
            if "image" not in ctype and not re.search(r"\.(jpe?g|png|webp)(\?|$)", safe_url, re.I):
                return ""
            data = await resp.content.read(8_500_000)
            if len(data) < 4096 or len(data) >= 8_500_000:
                return ""
            with open(path, "wb") as f:
                f.write(data)
            return path
    except Exception:
        return ""


async def send_telegram_post_resilient(
    tg_bot: Bot,
    session: aiohttp.ClientSession,
    news_id: int,
    html_caption: str,
    image_url: str,
    video_url: str,
    reply_markup: InlineKeyboardMarkup,
    silent: bool = False,
):
    """ارسال مقاوم به تلگرام با ثبت در publish_outbox (جلوگیری از انتشار تکراری) و Retry شبکه"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT telegram_message_id FROM publish_outbox WHERE news_item_id = ?", (news_id,))
    existing = c.fetchone()
    conn.close()
    if existing and existing[0]:
        return existing[0]

    img_path = ""
    if image_url:
        img_path = await download_image_safely(session, image_url, f"news_{news_id}.jpg")

    try:
        for attempt in range(1, 4):
            try:
                if img_path and os.path.exists(img_path) and visible_text_length(html_caption) <= 1020:
                    with open(img_path, "rb") as ph:
                        msg = await tg_bot.send_photo(
                            chat_id=TARGET_CHANNEL,
                            photo=ph,
                            caption=html_caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                            disable_notification=silent,
                        )
                else:
                    preview_target = video_url or image_url or ""
                    link_opts = (
                        LinkPreviewOptions(
                            url=preview_target, prefer_large_media=True, show_above_text=True
                        )
                        if preview_target
                        else LinkPreviewOptions(is_disabled=True)
                    )
                    msg = await tg_bot.send_message(
                        chat_id=TARGET_CHANNEL,
                        text=html_caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        link_preview_options=link_opts,
                        disable_notification=silent,
                    )

                if msg and msg.message_id:
                    conn = get_db_connection()
                    conn.execute(
                        "INSERT OR REPLACE INTO publish_outbox (news_item_id, telegram_message_id) VALUES (?, ?)",
                        (news_id, msg.message_id),
                    )
                    conn.commit()
                    conn.close()
                    return msg.message_id
            except RetryAfter as ra:
                await asyncio.sleep(int(getattr(ra, "retry_after", 10)) + 2)
            except (NetworkError, TimedOut) as net_err:
                if attempt == 3:
                    raise
                print(
                    f"⚠️ اختلال موقت شبکه تلگرام (تلاش {attempt}/3): {redact_secrets(str(net_err))}"
                )
                await asyncio.sleep(attempt * 5)
    finally:
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass
    return None


# ==============================================================================
# ۱۰. پایپ‌لاین اصلی پردازش، غنی‌سازی، کنترل کیفیت و انتشار خبر
# ==============================================================================
async def process_and_publish_batch(
    tg_bot: Bot, session: aiohttp.ClientSession, breaking_only: bool = False
):
    conn = get_db_connection()
    c = conn.cursor()
    if breaking_only:
        c.execute(
            """SELECT id, url, category, publisher_domain, source_tier, raw_title, raw_text,
                      image_url, video_url, has_video_or_audio, source_count, is_breaking_candidate, source_published_at
               FROM news_items
               WHERE status = 'pending' AND is_breaking_candidate = 1
               ORDER BY newsworthiness_score DESC, id DESC LIMIT 4"""
        )
    else:
        c.execute(
            """SELECT id, url, category, publisher_domain, source_tier, raw_title, raw_text,
                      image_url, video_url, has_video_or_audio, source_count, is_breaking_candidate, source_published_at
               FROM news_items
               WHERE status = 'pending'
               ORDER BY newsworthiness_score DESC, id DESC LIMIT 30"""
        )
    rows = c.fetchall()

    c.execute(
        """SELECT topic_fingerprint FROM news_items
           WHERE status = 'published' AND topic_fingerprint IS NOT NULL
           ORDER BY published_at DESC LIMIT 65"""
    )
    recent_topics = [r[0] for r in c.fetchall() if r[0]]
    conn.close()

    if not rows:
        if breaking_only:
            skipped = int(get_metadata("skipped_ai_calls", "0") or 0) + 1
            set_metadata("skipped_ai_calls", str(skipped))
        return

    candidates = []
    for r in rows:
        it = {
            "id": r[0],
            "url": r[1],
            "category": r[2],
            "domain": r[3] or extract_domain(r[1]),
            "source_tier": r[4],
            "raw_title": r[5],
            "raw_text": r[6],
            "image_url": r[7] or "",
            "video_url": r[8] or "",
            "has_video_or_audio": bool(r[9]),
            "source_count": r[10],
            "is_breaking_candidate": bool(r[11]),
            "source_published_at": r[12] or "",
        }
        it["score"] = compute_newsworthiness_score(it)
        if it["score"] >= MIN_LOCAL_NEWSWORTHINESS_SCORE:
            candidates.append(it)

    if not candidates:
        return

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[: (2 if breaking_only else MAX_CANDIDATES_FOR_AI)]

    # علامت‌گذاری موقت به processing
    conn = get_db_connection()
    ph = ",".join(["?"] * len(top_candidates))
    conn.execute(
        f"UPDATE news_items SET status = 'processing' WHERE id IN ({ph})",
        [x["id"] for x in top_candidates],
    )
    conn.commit()
    conn.close()

    # استخراج متن کامل مقاله، ویدیو و تصویر اصلی پیش از ارسال به هوش مصنوعی
    async def _enrich(it: dict):
        body, vid, og_img = await fetch_full_article_and_media(session, it["url"])
        it["full_article"] = body if len(body) >= 220 else it["raw_text"]
        if vid and not it["video_url"]:
            it["video_url"] = vid
            it["has_video_or_audio"] = True
        if og_img and not it["image_url"]:
            it["image_url"] = og_img

    await asyncio.gather(*(_enrich(it) for it in top_candidates), return_exceptions=True)

    max_pick = MAX_BREAKING_PER_CYCLE if breaking_only else MAX_NEWS_PER_CYCLE
    ai_payload = [
        {
            "id": it["id"],
            "category_hint": it["category"],
            "publisher_domain": it["domain"],
            "source_tier": it["source_tier"],
            "independent_sources_count": it["source_count"],
            "has_image": bool(it["image_url"]),
            "has_video_or_audio": it["has_video_or_audio"],
            "article_evidence": it["full_article"],
        }
        for it in top_candidates
    ]

    prompt = f"""
You are the Senior Editorial Intelligence System v3.0 for '{TARGET_CHANNEL}' (Persian Gaming, Technology, Hardware, Gadgets, Cinema & TV Newsroom).
Reference Date: November 2026.

EDITORIAL PRIORITY: Accuracy > Reliability > Reader Value > Clarity > Speed > Engagement.
Select AT MOST {max_pick} genuinely high-value stories from the candidates below. If only 1 or 2 stories have rich factual value and media, return only those 1 or 2.
Do NOT repeat any event in `already_published`:
{json.dumps(recent_topics, ensure_ascii=False)}

STRICT JOURNALISTIC & PERSIAN LANGUAGE RULES:
1. EVIDENCE-GROUNDED GENERATION ONLY:
   - Every name, date, number, percentage, price, specification, and quote MUST come directly from `article_evidence`.
   - Never invent details, never turn analyst estimates/ASP into official retail prices, and never merge different analysts' numbers.
2. NATURAL, PROFESSIONAL PERSIAN (NO MACHINE TRANSLATION):
   - Write in clear, fluent journalistic Persian using inverted-pyramid structure.
   - Start EVERY `headline_persian`, `summary_persian`, and bullet with a Persian word (NEVER start a line with a Latin word).
   - Keep proper names, game titles, and hardware models in English (e.g., Steam, SpaceX, Starship, GTA VI, RTX 5090).
   - Use established Persian technical terms: «نرخ فریم» (Frame Rate), «رهگیری پرتو» (Ray Tracing), «ارتقای وضوح تصویر» (Upscaling), «دسترسی زودهنگام» (Early Access), «صف بررسی بازی‌ها» (Review Queue), «میانگین قیمت فروش» (ASP).
3. HEADLINE ENGINE:
   - Informative, direct statement without clickbait, fake urgency, or emojis.

Candidates:
{json.dumps(ai_payload, ensure_ascii=False)}
"""

    result = await ask_structured_ai(prompt, BatchProcessResult, temperature=0.2)
    if not result or not result.selected_news:
        conn = get_db_connection()
        conn.execute(
            f"UPDATE news_items SET status = 'pending' WHERE id IN ({ph})",
            [x["id"] for x in top_candidates],
        )
        conn.commit()
        conn.close()
        return

    cand_map = {it["id"]: it for it in top_candidates}
    chosen_ids = set()
    tehran_hr = now_tehran().hour
    silent = (0 <= tehran_hr < 8) and not breaking_only

    for sel in result.selected_news[:max_pick]:
        orig = cand_map.get(sel.selected_id)
        if not orig:
            continue

        qa_score, passed, qa_note = evaluate_and_gate_news_item(sel, orig)
        if not passed:
            print(f"⛔ خبر #{orig['id']} در دروازه کنترل کیفیت رد شد: {qa_note}")
            conn = get_db_connection()
            conn.execute(
                "UPDATE news_items SET status = 'rejected', qa_score = ? WHERE id = ?",
                (qa_score, orig["id"]),
            )
            conn.commit()
            conn.close()
            continue

        chosen_ids.add(orig["id"])
        caption = (
            fit_post_for_telegram_photo(sel, orig["domain"])
            if orig.get("image_url")
            else format_newsroom_post(sel, orig["domain"], include_optional=True)
        )

        kb = [
            [
                InlineKeyboardButton("❤️ پسندیدن (0)", callback_data=f"like_{orig['id']}"),
                InlineKeyboardButton(f"🔗 منبع ({orig['domain']})", url=orig["url"]),
            ]
        ]
        if orig.get("video_url"):
            kb.append([InlineKeyboardButton("🎬 تماشای ویدیو / تریلر رسمی", url=orig["video_url"])])
        markup = InlineKeyboardMarkup(kb)

        msg_id = await send_telegram_post_resilient(
            tg_bot=tg_bot,
            session=session,
            news_id=orig["id"],
            html_caption=caption,
            image_url=orig.get("image_url", ""),
            video_url=orig.get("video_url", ""),
            reply_markup=markup,
            silent=silent,
        )

        if msg_id:
            conn = get_db_connection()
            conn.execute(
                """UPDATE news_items
                   SET status = 'published', published_at = CURRENT_TIMESTAMP,
                       full_article_text = ?, video_url = ?, qa_score = ?,
                       topic_fingerprint = ?, published_category = ?,
                       published_headline = ?, published_summary = ?,
                       verification_status = ?, related_entity = ?,
                       telegram_message_id = ?
                   WHERE id = ?""",
                (
                    orig.get("full_article", ""),
                    orig.get("video_url", ""),
                    qa_score,
                    sel.topic_fingerprint,
                    sel.category_id,
                    sel.headline_persian,
                    sel.summary_persian,
                    sel.verification_status,
                    sel.related_entity,
                    msg_id,
                    orig["id"],
                ),
            )
            if sel.related_entity:
                conn.execute(
                    "INSERT INTO hype_events (entity_name, category, score) VALUES (?, ?, ?)",
                    (sel.related_entity.strip(), sel.category_id, float(sel.hype_score)),
                )
            conn.commit()
            conn.close()
            await asyncio.sleep(4)

    # تعیین وضعیت سایر کاندیداهای بررسی‌شده تا صف انباشته نشود
    other_ids = [r[0] for r in rows if r[0] not in chosen_ids]
    if other_ids and not breaking_only:
        conn = get_db_connection()
        ph_oth = ",".join(["?"] * len(other_ids))
        conn.execute(f"UPDATE news_items SET status = 'rejected' WHERE id IN ({ph_oth})", other_ids)
        conn.commit()
        conn.close()


# ==============================================================================
# ۱۱. موتور میم و شوخی کاربران و مرور تحلیلی شبانه (Memes & Daily Digest)
# ==============================================================================
def detect_24h_trends(top_n: int = 5) -> list[str]:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """SELECT entity_name, SUM(score) as total_score
           FROM hype_events
           WHERE created_at >= datetime('now', '-24 hours')
           GROUP BY lower(entity_name)
           ORDER BY total_score DESC LIMIT ?""",
        (top_n,),
    )
    rows = [r[0] for r in c.fetchall() if r[0]]
    conn.close()
    return rows


async def fetch_reddit_memes(session: aiohttp.ClientSession, query: str) -> list[dict]:
    try:
        seen = set(json.loads(get_metadata("seen_memes", "[]")))
    except Exception:
        seen = set()

    out = []
    for period in ("day", "week"):
        url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=top&t={period}&limit=25"
        try:
            async with session.get(url, timeout=14, headers=REDDIT_HEADERS) as resp:
                if resp.status != 200:
                    continue
                xml = await resp.text(errors="ignore")
        except Exception:
            continue

        feed = await asyncio.to_thread(feedparser.parse, xml)
        for entry in feed.entries:
            tags = getattr(entry, "tags", []) or []
            sub = str(tags[0].get("term", "")).lower() if tags else ""
            link = validate_safe_external_url(getattr(entry, "link", ""))
            if sub not in MEME_SUBREDDITS or not link or link in seen:
                continue
            body = entry.content[0].value if getattr(entry, "content", None) else ""
            m = re.search(
                r'https://(?:i|preview)\.redd\.it/[^"\']+?\.(?:jpe?g|png|webp)[^"\']*', body
            )
            img = validate_safe_external_url(html.unescape(m.group(0))) if m else ""
            if not img and getattr(entry, "media_thumbnail", None):
                img = validate_safe_external_url(entry.media_thumbnail[0].get("url", ""))
            out.append(
                {
                    "index": len(out),
                    "subreddit": sub,
                    "title": (entry.title or "")[:200],
                    "link": link,
                    "image": img,
                }
            )
            if len(out) >= 6:
                return out
        if out:
            break
    return out


async def publish_community_meme_if_due(tg_bot: Bot, session: aiohttp.ClientSession):
    t_now = now_tehran()
    if 0 <= t_now.hour < 9:
        return
    last_ts = float(get_metadata("last_meme_ts", "0") or 0)
    if t_now.timestamp() - last_ts < MEME_GAP_MINUTES * 60:
        return

    queries = detect_24h_trends(top_n=3) + ["PlayStation meme", "PC gaming meme", "Steam meme"]
    for q in queries[:4]:
        cands = await fetch_reddit_memes(session, q)
        if not cands:
            continue

        prompt = f"""
Topic: {q}
Reddit community posts:
{json.dumps([{k: x[k] for k in ("index", "subreddit", "title")} for x in cands], ensure_ascii=False)}

Pick the ONE post that is genuinely witty and relatable for a Persian gaming/tech audience (chosen_index = -1 if none).
- Write `joke_persian` in natural, punchy Persian starting with a Persian word.
- Reject anything offensive, political, or NSFW (`is_safe_and_funny` = false).
"""
        pick = await ask_structured_ai(prompt, MemePick, temperature=0.4)
        if (
            not pick
            or pick.chosen_index < 0
            or pick.chosen_index >= len(cands)
            or not pick.is_safe_and_funny
        ):
            continue

        chosen = cands[pick.chosen_index]
        lines = [
            "😄 <b>شوخی و میم کاربران فضای مجازی</b>",
            "",
            f"<blockquote>{pick.joke_persian.strip()}</blockquote>",
        ]
        if pick.context_persian.strip():
            lines.append(f"💬 <i>{pick.context_persian.strip()}</i>")
        lines.append(f"📎 انجمن Reddit (r/{chosen['subreddit']})")
        lines.append(f"\n🏷 #فان_و_میم #شوخی_کاربران{CHANNEL_SIGNATURE}")

        caption = sanitize_and_fix_bidi_html("\n".join(lines))
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔗 مشاهده پست در Reddit", url=chosen["link"])]]
        )

        img_path = ""
        if chosen.get("image"):
            img_path = await download_image_safely(session, chosen["image"], "meme_post.jpg")
        try:
            if img_path and os.path.exists(img_path):
                with open(img_path, "rb") as ph:
                    await tg_bot.send_photo(
                        chat_id=TARGET_CHANNEL,
                        photo=ph,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
            else:
                await tg_bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                )

            try:
                seen_list = json.loads(get_metadata("seen_memes", "[]"))
            except Exception:
                seen_list = []
            seen_list.append(chosen["link"])
            set_metadata("seen_memes", json.dumps(seen_list[-250:]))
            set_metadata("last_meme_ts", str(t_now.timestamp()))
            return
        except Exception as e:
            print(f"⚠️ خطا در ارسال میم: {redact_secrets(str(e))}")
        finally:
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except OSError:
                    pass


async def publish_daily_digest_if_due(tg_bot: Bot):
    t_now = now_tehran()
    if t_now.hour != DAILY_DIGEST_HOUR:
        return
    today_str = t_now.strftime("%Y-%m-%d")
    if get_metadata("last_digest_date") == today_str:
        return

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """SELECT published_category, published_headline, published_summary, verification_status
           FROM news_items
           WHERE status = 'published' AND published_at >= datetime('now', '-24 hours')
           ORDER BY id DESC LIMIT 25"""
    )
    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return

    items = [
        {"cat": r[0], "headline": r[1], "summary": (r[2] or "")[:280], "status": r[3]}
        for r in rows
    ]
    prompt = f"""
You are the Editor-in-Chief of '{TARGET_CHANNEL}'. Date: {today_str}.
Stories published in the last 24 hours:
{json.dumps(items, ensure_ascii=False)}

Generate an analytical Persian 24-hour synthesis (`DailyDigestOutput`).
RULES:
- NEVER copy-paste old headlines verbatim. Synthesize related developments and explain why they matter.
- Start every sentence and bullet with a Persian word.
"""
    digest = await ask_structured_ai(prompt, DailyDigestOutput, temperature=0.25)
    if not digest:
        return

    lines = [
        "📅 <b>تحلیل و جمع‌بندی مهم‌ترین رویدادهای ۲۴ ساعت گذشته</b>",
        f"🗓 تاریخ: {today_str}",
        "",
        "🔥 <b>محور اصلی رویدادهای امروز:</b>",
        f"<blockquote>{digest.top_story_highlight}</blockquote>",
    ]
    if digest.gaming_highlights:
        lines.append("\n🎮 <b>تحولات دنیای گیمینگ:</b>")
        for b in digest.gaming_highlights[:3]:
            lines.append(f"• {b.lstrip('•- ')}")
    if digest.tech_hardware_highlights:
        lines.append("\n💻 <b>تکنولوژی، سخت‌افزار و گجت:</b>")
        for b in digest.tech_hardware_highlights[:3]:
            lines.append(f"• {b.lstrip('•- ')}")
    if digest.cinema_tv_highlights:
        lines.append("\n🎬 <b>سینما و تلویزیون:</b>")
        for b in digest.cinema_tv_highlights[:2]:
            lines.append(f"• {b.lstrip('•- ')}")
    if digest.editorial_takeaway:
        lines.append(f"\n🧭 <b>چشم‌انداز فردا:</b> {digest.editorial_takeaway}")

    lines.append(f"\n🏷 #مرور_روزانه #تحلیل_خبری #گیمینگ #تکنولوژی{CHANNEL_SIGNATURE}")
    final_html = sanitize_and_fix_bidi_html("\n".join(lines))

    try:
        await tg_bot.send_message(chat_id=TARGET_CHANNEL, text=final_html, parse_mode="HTML")
        set_metadata("last_digest_date", today_str)
    except Exception as e:
        print(f"⚠️ خطا در ارسال مرور روزانه: {redact_secrets(str(e))}")


# ==============================================================================
# ۱۲. تعامل کاربران، مدیریت اصلاحیه (/correct) و داشبورد ادمین (/status)
# ==============================================================================
async def handle_like_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("like_"):
        return
    try:
        post_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
    except Exception:
        await query.answer()
        return

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    exists = c.fetchone() is not None
    if exists:
        c.execute("DELETE FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        msg = "رأی شما برداشته شد."
    else:
        c.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, user_id))
        msg = "❤️ سپاس از همراهی شما!"
    c.execute("SELECT COUNT(*) FROM post_likes WHERE post_id = ?", (post_id,))
    total = c.fetchone()[0]
    conn.commit()
    conn.close()

    await query.answer(msg)
    try:
        old_kb = query.message.reply_markup
        if old_kb and old_kb.inline_keyboard:
            new_rows = []
            for row in old_kb.inline_keyboard:
                new_row = []
                for btn in row:
                    if btn.callback_data == query.data:
                        new_row.append(
                            InlineKeyboardButton(
                                f"❤️ پسندیدن ({total})", callback_data=btn.callback_data
                            )
                        )
                    else:
                        new_row.append(btn)
                new_rows.append(new_row)
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        pass


async def handle_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """داشبورد وضعیت سلامت تحریریه با قفل امنیتی Fail-Closed"""
    if not ADMIN_USER_ID or not update.effective_user or update.effective_user.id != ADMIN_USER_ID:
        return

    today = now_tehran().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*), AVG(qa_score) FROM news_items WHERE status = 'published' AND published_at >= datetime('now', '-24 hours')"
    )
    pub_row = c.fetchone()
    pub_24h = pub_row[0] or 0
    avg_qa = round(pub_row[1] or 0.0, 1)

    c.execute("SELECT COUNT(*) FROM news_items WHERE status = 'pending'")
    pending_cnt = c.fetchone()[0]

    c.execute(
        """SELECT provider, COUNT(*), SUM(input_tokens), SUM(output_tokens)
           FROM ai_usage_logs WHERE request_date = ? GROUP BY provider""",
        (today,),
    )
    usage_rows = c.fetchall()

    c.execute("SELECT COUNT(*) FROM feed_health WHERE consecutive_failures >= 3")
    failing_feeds = c.fetchone()[0]
    conn.close()

    usage_lines = []
    for prov, calls, in_t, out_t in usage_rows:
        usage_lines.append(f"  • {prov}: {calls} درخواست ({in_t or 0} ورودی / {out_t or 0} خروجی)")
    usage_str = "\n".join(usage_lines) if usage_lines else "  • هنوز درخواستی ثبت نشده"

    skipped = get_metadata("skipped_ai_calls", "0")
    report = (
        f"📊 <b>داشبورد تحریریه هوشمند {TARGET_CHANNEL}</b>\n\n"
        f"✅ اخبار منتشرشده (۲۴ ساعت): <b>{pub_24h}</b> (میانگین امتیاز کیفی: <b>{avg_qa}/100</b>)\n"
        f"⏳ اخبار در صف بررسی: <b>{pending_cnt}</b>\n"
        f"🛡 فراخوانی‌های صرفه‌جویی‌شده AI: <b>{skipped}</b>\n"
        f"📡 فیدهای دارای خطای موقت: <b>{failing_feeds}</b>\n\n"
        f"🤖 <b>مصرف امروز مدل‌ها ({today}):</b>\n{usage_str}"
    )
    await update.message.reply_text(sanitize_and_fix_bidi_html(report), parse_mode="HTML")


async def handle_correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
