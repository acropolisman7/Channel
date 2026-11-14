import asyncio
import sqlite3
import re
import os
import json
import math
import html
import time
import random
import hashlib
import aiohttp
import httpx
import feedparser
from typing import Literal
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import NetworkError, TimedOut, RetryAfter
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

try:
    from telegram import ReplyParameters
except ImportError:
    ReplyParameters = None

# ================= ۱. تابع محافظ لینک‌ها در برابر فرمت Markdown =================
def sanitize_plain_url(url: str) -> str:
    """تبدیل خودکار لینک‌های فرمت Markdown به URL خالص"""
    if not url:
        return ""
    u = str(url).strip()
    md_match = re.match(r'^\[[^\]]*\]\((https?://[^)]+)\)$', u)
    if md_match:
        u = md_match.group(1).strip()
    return u.strip("[]() ")

# ================= ۲. تنظیمات اصلی و کلیدهای API =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN").strip()

GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]

GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "").strip()

TARGET_CHANNEL = '@jazebestore'
STORE_BASE_URL = sanitize_plain_url('https://jazebestore.com')
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
DB_PATH = 'rss_news_history.db'

GROQ_BASE_URL = sanitize_plain_url("https://api.groq.com/openai/v1")
OPENROUTER_BASE_URL = sanitize_plain_url("https://openrouter.ai/api/v1")
GANJOOR_API_BASE = sanitize_plain_url("https://api.ganjoor.net/api/ganjoor")
GANJOOR_SAADI_FALLBACK_URL = sanitize_plain_url("https://ganjoor.net/saadi/")
OMDB_API_BASE = sanitize_plain_url("https://www.omdbapi.com/")

# تنظیمات زمانی و بهینه‌سازی مصرف توکن
BREAKING_CHECK_INTERVAL_SECONDS = 300   # بررسی اخبار فوری هر ۵ دقیقه
REGULAR_CYCLE_SECONDS = 2700          # چرخه عادی هر ۴۵ دقیقه
MAX_NEWS_PER_CYCLE = 5                # حداکثر ۵ خبر دست‌چین در هر چرخه
MAX_BREAKING_PER_CYCLE = 2            # حداکثر ۲ خبر فوری در هر نوبت
MAX_CANDIDATES_FOR_AI = 12            # ارسال فقط ۱۲ کاندیدای برتر پس از فیلتر محلی
SEMANTIC_SIMILARITY_THRESHOLD = 0.78
CLUSTER_SIMILARITY_THRESHOLD = 0.72
POLL_MIN_HYPE = 8

# سقف‌های روزانه و Cooldown سرویس‌های هوش مصنوعی
GEMINI_COOLDOWN_SECONDS = 900
GROQ_DAILY_CALL_LIMIT = 80
GROQ_DAILY_TOKEN_LIMIT = 220000
OPENROUTER_DAILY_CALL_LIMIT = 50

# تنظیمات پست‌های روزانه (تقویم + شعر سعدی و پیشنهاد فیلم/موسیقی)
TEHRAN = ZoneInfo("Asia/Tehran")
CALENDAR_POST_HOUR = 11
CALENDAR_WINDOW_END_HOUR = 24
DAILY_REC_HOUR = 12
DAILY_REC_WINDOW_END_HOUR = 24

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# مدل‌های فعال جمنای و پشتیبان‌ها
GEMINI_MODELS = [
    'gemini-4-hydrogen',
    'gemini-3.8-flash',
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
]
GROQ_MODELS = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b']
OPENROUTER_MODELS = ['openrouter/free', 'google/gemma-3-27b-it:free']

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
    "crypto": "کریپتو",
    "film_tv": "سینما و تلویزیون",
    "internet_culture": "فرهنگ اینترنتی",
    "fun_meme": "فان و میم",
    "music": "موسیقی",
    "general_news": "اخبار عمومی"
}

BREAKING_TRIGGER_KEYWORDS = [
    "officially announced", "official trailer", "release date announced",
    "delayed", "canceled", "cancelled", "state of play", "playstation showcase",
    "xbox games showcase", "gta vi", "gta 6", "ps5 pro", "nintendo switch 2",
    "rtx 5090", "rtx 5080", "به‌طور رسمی معرفی شد", "تاریخ انتشار", "تریلر رسمی"
]

HIGH_PRIORITY_KEYWORDS = [
    "gta", "playstation", "ps5", "xbox", "nintendo", "switch", "steam", "nvidia",
    "rtx", "amd", "intel", "apple", "iphone", "openai", "gemini", "ai", "bitcoin",
    "ethereum", "trailer", "release", "update", "review", "sony", "microsoft"
]

_RAW_RSS_SOURCES = {
    "gaming": [
        "https://www.ign.com/rss/v2/articles/feed",
        "https://www.gamespot.com/feeds/mashup/",
        "https://www.eurogamer.net/?format=rss",
        "https://www.videogameschronicle.com/feed/",
        "https://www.pcgamer.com/feeds.xml",
        "https://www.polygon.com/rss/index.xml",
        "https://www.gematsu.com/feed",
        "https://www.pushsquare.com/feeds/latest",
        "https://www.purexbox.com/feeds/latest",
        "https://www.nintendolife.com/feeds/latest",
        "https://blog.playstation.com/feed/",
        "https://news.xbox.com/en-us/feed/",
        "https://www.zoomg.ir/feed/",
        "https://vigiato.net/feed",
        "https://gamefa.com/feed"
    ],
    "technology": [
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://techcrunch.com/feed/",
        "https://www.engadget.com/rss.xml",
        "https://feeds.macrumors.com/MacRumors-All",
        "https://9to5mac.com/feed/",
        "https://www.zoomit.ir/feed/",
        "https://digiato.com/feed"
    ],
    "hardware": [
        "https://www.tomshardware.com/feeds/all",
        "https://www.techpowerup.com/rss/news"
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed"
    ],
    "film_tv": [
        "https://variety.com/feed/",
        "https://www.hollywoodreporter.com/feed/",
        "https://deadline.com/feed/",
        "https://collider.com/feed/"
    ],
    "internet_culture": [
        "https://knowyourmeme.com/newsfeed.rss",
        "https://www.dexerto.com/feed/"
    ],
    "music": [
        "https://www.billboard.com/feed/",
        "https://www.rollingstone.com/feed/",
        "https://www.nme.com/feed"
    ],
    "general_news": [
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://www.theguardian.com/world/rss"
    ]
}

CATEGORIZED_RSS_SOURCES = {
    cat: [sanitize_plain_url(u) for u in urls if sanitize_plain_url(u)]
    for cat, urls in _RAW_RSS_SOURCES.items()
}

# ================= ۳. راه‌اندازی دیتابیس و مدیریت سهمیه =================
bot = Bot(token=TELEGRAM_BOT_TOKEN)
os.makedirs('temp_media', exist_ok=True)
provider_rotation_index = 0
_extra_ai_rot = 0
_provider_cooldown_until = {"gemini": 0.0, "groq": 0.0, "openrouter": 0.0}

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

def _get_daily_usage(provider: str) -> tuple[int, int]:
    today = get_current_tehran_time().strftime("%Y-%m-%d")
    saved_date = get_metadata(f"usage_date_{provider}", "")
    if saved_date != today:
        set_metadata(f"usage_date_{provider}", today)
        set_metadata(f"usage_calls_{provider}", "0")
        set_metadata(f"usage_tokens_{provider}", "0")
        return 0, 0
    calls = int(get_metadata(f"usage_calls_{provider}", "0") or 0)
    tokens = int(get_metadata(f"usage_tokens_{provider}", "0") or 0)
    return calls, tokens

def _record_daily_usage(provider: str, tokens_used: int = 1200):
    calls, tokens = _get_daily_usage(provider)
    set_metadata(f"usage_calls_{provider}", str(calls + 1))
    set_metadata(f"usage_tokens_{provider}", str(tokens + max(0, tokens_used)))

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

# ================= ۴. زبان فارسی، تاریخ شمسی و ویرایش نگارشی =================
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

def polish_selected(sel) -> None:
    for field in ("headline_persian", "summary_persian", "poll_question_persian"):
        val = getattr(sel, field, "")
        if val:
            setattr(sel, field, persian_polish(val))
    if getattr(sel, "key_points_persian", None):
        sel.key_points_persian = [persian_polish(p) for p in sel.key_points_persian]
    if getattr(sel, "poll_options_persian", None):
        sel.poll_options_persian = [persian_polish(o) for o in sel.poll_options_persian]

# ================= ۵. موتور Embedding پایدار و خوشه‌بندی =================
def _deterministic_token_hash(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")

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
        h = _deterministic_token_hash(token)
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

async def run_semantic_clustering_and_deduplication():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT embedding_json, raw_title
        FROM news_items
        WHERE status = 'published' AND published_at >= datetime('now', '-72 hours')
        ORDER BY id DESC LIMIT 150
    """)
    published_rows = c.fetchall()

    published_embeddings = []
    for emb_str, pub_title in published_rows:
        if emb_str:
            try:
                published_embeddings.append((json.loads(emb_str), pub_title))
            except Exception:
                pass

    while True:
        c.execute("""
            SELECT id, raw_title, raw_text, source, is_breaking_candidate
            FROM news_items
            WHERE status = 'discovered'
            ORDER BY id ASC LIMIT 120
        """)
        discovered_rows = c.fetchall()
        if not discovered_rows:
            break

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

        if rejected_ids:
            placeholders = ",".join(["?"] * len(rejected_ids))
            c.execute(f"UPDATE news_items SET status = 'rejected' WHERE id IN ({placeholders})", rejected_ids)

        for cluster in clusters:
            primary = max(cluster, key=lambda x: len(x['text']))
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
            for extra in cluster:
                if extra['id'] != primary['id']:
                    c.execute("UPDATE news_items SET status = 'rejected' WHERE id = ?", (extra['id'],))

        conn.commit()
    conn.close()

# ================= ۶. پیش‌فیلتر محلی کاندیداها =================
def score_candidate_locally(item: dict) -> float:
    score = float(item.get('source_count', 1)) * 3.0
    if item.get('is_breaking_candidate'):
        score += 5.0
    if item.get('image_url'):
        score += 1.5
    low_text = f"{item.get('title', '')} {item.get('text', '')}".lower()
    for kw in HIGH_PRIORITY_KEYWORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", low_text):
            score += 1.2
    return score

# ================= ۷. پاک‌سازی متن، HTML و ارسال یکپارچه =================
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
            m_url = sanitize_plain_url(mc.get('url', ''))
            if 'video' in m_type or 'audio' in m_type or 'youtube.com' in m_url:
                has_av = True
            elif not img_url and m_url:
                img_url = m_url

    if not img_url and 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        img_url = sanitize_plain_url(entry.media_thumbnail[0].get('url', ''))

    link_str = sanitize_plain_url(getattr(entry, 'link', '') or '')
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
            img_url = sanitize_plain_url(img_tag['src'])

    return img_url, has_av

async def download_image_from_url(session: aiohttp.ClientSession, url: str, filename: str) -> str | None:
    clean_url = sanitize_plain_url(url)
    if not clean_url:
        return None
    try:
        async with session.get(clean_url, timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
            if resp.status == 200:
                filepath = os.path.join('temp_media', filename)
                with open(filepath, 'wb') as f:
                    f.write(await resp.read())
                return filepath
    except Exception:
        pass
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
    text = _fit_lines(text, 3900)
    clean_img_url = sanitize_plain_url(image_url) if image_url else None

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

    img_path = None
    if clean_img_url and _visible_len(text) <= 980:
        img_path = await download_image_from_url(session, clean_img_url, filename)

    try:
        for attempt in range(1, 4):
            try:
                if img_path and os.path.exists(img_path):
                    try:
                        return await send_photo_single(img_path, text, "HTML", reply_markup, reply_to)
                    except Exception as photo_err:
                        err_str = str(photo_err).lower()
                        if "entities" in err_str or "parse" in err_str:
                            return await send_photo_single(img_path, _strip_tags(text), None, reply_markup, reply_to)
                        if isinstance(photo_err, (NetworkError, TimedOut, RetryAfter)):
                            raise
                        img_path = None

                try:
                    return await send_text_single(text, "HTML", reply_markup, reply_to, media_url=clean_img_url)
                except Exception as err:
                    err_low = str(err).lower()
                    if "entities" in err_low or "parse" in err_low:
                        return await send_text_single(_strip_tags(text), None, reply_markup, reply_to, media_url=clean_img_url)
                    if isinstance(err, (NetworkError, TimedOut, RetryAfter)):
                        raise
                    return await send_text_single(text, "HTML", reply_markup, reply_to, media_url=None)

            except RetryAfter as ra:
                wait_sec = int(getattr(ra, "retry_after", 10)) + 2
                await asyncio.sleep(wait_sec)
            except (NetworkError, TimedOut) as net_err:
                if attempt == 3:
                    raise
                print(f"⚠️ اختلال شبکه در ارسال به تلگرام (تلاش {attempt}/3): {net_err}")
                await asyncio.sleep(attempt * 5)
    finally:
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass

# ================= ۸. پین کردن تا ۰۰:۰۰ =================
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
        print(f"⚠️ پین ناموفق: {e}")

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

# ================= ۹. Schema فشرده و بهینه =================
VerificationStatusType = Literal["تأیید رسمی", "گزارش رسانه‌ای", "پیش‌بینی تحلیلگران"]

class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="ID of the selected candidate")
    category_id: str = Field(description="One of: gaming, technology, hardware, crypto, film_tv, internet_culture, fun_meme, music, general_news")
    verification_status: VerificationStatusType = Field(
        description="Strictly one of: 'تأیید رسمی', 'گزارش رسانه‌ای', or 'پیش‌بینی تحلیلگران'"
    )
    is_breaking: bool = Field(default=False, description="True ONLY if verification_status is 'تأیید رسمی' and major news")
    headline_persian: str = Field(description="Short, clear Persian headline (max 14 words). Prefix with 'پیش‌بینی تحلیلگران:' if it is an analyst forecast.")
    summary_persian: str = Field(description="Concise, clear 2-3 sentence Persian summary (<320 chars). Attribute claims to exact speaker/firm. Distinguish Average Selling Price (میانگین قیمت فروش) from official price. Use exact years (e.g., اوایل سال ۲۰۲۷).")
    key_points_persian: list[str] = Field(description="2 to 3 short, ultra-clear Persian bullet points (max 12 words each)")
    poll_question_persian: str = Field(default="", description="Short Persian poll question ONLY if verification_status != 'پیش‌بینی تحلیلگران' and hype_score >= 8; else empty string")
    poll_options_persian: list[str] = Field(default_factory=list, description="2 to 3 short neutral poll options, or empty list")
    topic_hashtags: list[str] = Field(description="2 short Persian hashtags starting with #")
    topic_fingerprint: str = Field(description="Short 6-word English topic key for deduplication")
    related_game: str = Field(default="", description="Canonical English name of game/device, or empty")
    hype_score: int = Field(default=5, ge=1, le=10)

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۱۰. موتور AI با مدیریت هوشمند Cooldown و سقف روزانه =================
JSON_SCHEMA_INSTRUCTION = """
Respond ONLY with valid JSON matching:
{"selected_news":[{"selected_id":1,"category_id":"gaming","verification_status":"تأیید رسمی","is_breaking":false,"headline_persian":"...","summary_persian":"...","key_points_persian":["...","..."],"poll_question_persian":"","poll_options_persian":[],"topic_hashtags":["#گیمینگ"],"topic_fingerprint":"...","related_game":"","hype_score":7}]}
"""

def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(40.0, connect=20.0),
        http2=False,
        trust_env=False,
        follow_redirects=True
    )

def _format_net_error(e: Exception) -> str:
    cause = getattr(e, "__cause__", None)
    if cause:
        return f"{type(e).__name__}: {e} | cause: {type(cause).__name__}: {cause}"
    return f"{type(e).__name__}: {e}"

def _extract_json_from_llm_content(raw_content: str | None) -> dict:
    if not raw_content or not isinstance(raw_content, str):
        raise ValueError("Empty content")
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)

def _is_quota_error(err: Exception) -> bool:
    s = str(err).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s or "rate limit" in s

async def call_gemini_provider(prompt: str) -> BatchProcessResult | None:
    if not GEMINI_API_KEYS:
        return None
    now = time.time()
    if now < _provider_cooldown_until["gemini"]:
        rem = int(_provider_cooldown_until["gemini"] - now)
        print(f"ℹ️ عبور از Gemini: در وضعیت استراحت (Cooldown) تا {rem} ثانیه دیگر")
        return None
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            try:
                print(f"تلاش با Gemini (کلید #{key_idx} | {model_name})...")
                response = await asyncio.to_thread(
                    temp_client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchProcessResult,
                        temperature=0.2
                    )
                )
                raw_dict = _extract_json_from_llm_content(response.text)
                validated = BatchProcessResult.model_validate(raw_dict)
                print(f"✅ موفقیت با Gemini ({model_name})")
                return validated
            except (ValidationError, json.JSONDecodeError, ValueError) as ve:
                print(f"⚠️ خطای فرمت JSON در Gemini ({model_name}): {ve}")
                continue
            except Exception as e:
                print(f"⚠️ خطا در Gemini ({model_name}): {e}")
                if _is_quota_error(e):
                    _provider_cooldown_until["gemini"] = time.time() + GEMINI_COOLDOWN_SECONDS
                    print(f"⚠️ سهمیه Gemini به سقف رسیده است (Cooldown به مدت {GEMINI_COOLDOWN_SECONDS // 60} دقیقه).")
                    return None
                await asyncio.sleep(1)
    return None

async def call_groq_provider(prompt: str) -> BatchProcessResult | None:
    if not GROQ_API_KEYS:
        return None
    now = time.time()
    if now < _provider_cooldown_until["groq"]:
        return None
    calls, tokens = _get_daily_usage("groq")
    if calls >= GROQ_DAILY_CALL_LIMIT or tokens >= GROQ_DAILY_TOKEN_LIMIT:
        print(f"ℹ️ عبور از Groq: سقف روزانه داخلی Groq ({calls}/{GROQ_DAILY_CALL_LIMIT} درخواست | {tokens} توکن) پر شده")
        return None
    clean_groq_url = sanitize_plain_url(GROQ_BASE_URL)
    async with _build_http_client() as http_client:
        for key_idx, groq_key in enumerate(GROQ_API_KEYS, start=1):
            groq_client = AsyncOpenAI(
                api_key=groq_key.strip(),
                base_url=clean_groq_url,
                http_client=http_client
            )
            for model_name in GROQ_MODELS:
                try:
                    print(f"تلاش با Groq (کلید #{key_idx} | {model_name})...")
                    completion = await groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2
                    )
                    content = completion.choices[0].message.content if completion.choices else None
                    used_toks = getattr(completion.usage, "total_tokens", 1400) if getattr(completion, "usage", None) else 1400
                    _record_daily_usage("groq", used_toks)
                    raw_dict = _extract_json_from_llm_content(content)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت با Groq ({model_name} | مصرف: {used_toks} توکن)")
                    return validated
                except (ValidationError, json.JSONDecodeError, ValueError):
                    continue
                except Exception as e:
                    print(f"⚠️ خطا در Groq ({model_name}): {_format_net_error(e)}")
                    if _is_quota_error(e):
                        _provider_cooldown_until["groq"] = time.time() + 900
                        return None
                    await asyncio.sleep(1)
    return None

async def call_openrouter_provider(prompt: str) -> BatchProcessResult | None:
    if not OPENROUTER_API_KEYS:
        return None
    now = time.time()
    if now < _provider_cooldown_until["openrouter"]:
        return None
    calls, _ = _get_daily_usage("openrouter")
    if calls >= OPENROUTER_DAILY_CALL_LIMIT:
        print(f"ℹ️ عبور از OpenRouter: سقف روزانه داخلی ({calls}/{OPENROUTER_DAILY_CALL_LIMIT}) پر شده")
        return None
    clean_or_url = sanitize_plain_url(OPENROUTER_BASE_URL)
    async with _build_http_client() as http_client:
        for key_idx, or_key in enumerate(OPENROUTER_API_KEYS, start=1):
            or_client = AsyncOpenAI(
                api_key=or_key.strip(),
                base_url=clean_or_url,
                http_client=http_client
            )
            for model_name in OPENROUTER_MODELS:
                try:
                    print(f"تلاش با OpenRouter (کلید #{key_idx} | {model_name})...")
                    completion = await or_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "Chief Editor JSON API. " + JSON_SCHEMA_INSTRUCTION},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.2
                    )
                    content = completion.choices[0].message.content if completion.choices else None
                    _record_daily_usage("openrouter", 1400)
                    raw_dict = _extract_json_from_llm_content(content)
                    validated = BatchProcessResult.model_validate(raw_dict)
                    print(f"✅ موفقیت با OpenRouter ({model_name})")
                    return validated
                except (ValidationError, json.JSONDecodeError, ValueError):
                    continue
                except Exception as e:
                    print(f"⚠️ خطا در OpenRouter ({model_name}): {_format_net_error(e)}")
                    if _is_quota_error(e):
                        _provider_cooldown_until["openrouter"] = time.time() + 1800
                        return None
                    await asyncio.sleep(1)
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
    sys_msg = ("Respond ONLY with valid JSON matching schema:\n" + schema_hint)

    async def gemini_fn():
        if not GEMINI_API_KEYS or time.time() < _provider_cooldown_until["gemini"]:
            return None
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
                except Exception as e:
                    if _is_quota_error(e):
                        _provider_cooldown_until["gemini"] = time.time() + GEMINI_COOLDOWN_SECONDS
                        return None
                    break
        return None

    async def openai_compat(name, keys, base_url, models, limit, use_json_mode: bool = True):
        if not keys or time.time() < _provider_cooldown_until[name]:
            return None
        calls, _ = _get_daily_usage(name)
        if calls >= limit:
            return None
        clean_base = sanitize_plain_url(base_url)
        async with _build_http_client() as http_client:
            for key in keys:
                client = AsyncOpenAI(api_key=key.strip(), base_url=clean_base, http_client=http_client)
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
                        _record_daily_usage(name, 1000)
                        return model_cls.model_validate(_extract_json_from_llm_content(content))
                    except (ValidationError, json.JSONDecodeError, ValueError):
                        continue
                    except Exception as e:
                        if _is_quota_error(e):
                            _provider_cooldown_until[name] = time.time() + 900
                            return None
                        break
        return None

    backends = [
        gemini_fn,
        lambda: openai_compat("groq", GROQ_API_KEYS, GROQ_BASE_URL, GROQ_MODELS, GROQ_DAILY_CALL_LIMIT, True),
        lambda: openai_compat("openrouter", OPENROUTER_API_KEYS, OPENROUTER_BASE_URL, OPENROUTER_MODELS, OPENROUTER_DAILY_CALL_LIMIT, False),
    ]
    start = _extra_ai_rot % 3
    _extra_ai_rot += 1
    for fn in backends[start:] + backends[:start]:
        result = await fn()
        if result:
            return result
    return None

# ================= ۱۱. پست روزانه تقویم و بیتی از سعدی (ساعت ۱۱) =================
FALLBACK_VERSES = [
    ("بنی‌آدم اعضای یکدیگرند", "که در آفرینش ز یک گوهرند", "گلستان، باب اول، حکایت ۱۰"),
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
    base = sanitize_plain_url(GANJOOR_API_BASE)
    try:
        poet_id = get_metadata("ganjoor_saadi_id", "")
        if not poet_id:
            async with session.get(sanitize_plain_url(f"{base}/poets"), timeout=aiohttp.ClientTimeout(total=15), headers=UA) as resp:
                poets = await resp.json(content_type=None)
            for p in poets:
                name = (p.get("name") or "").replace("ي", "ی")
                if (p.get("fullUrl") or "").strip("/") == "saadi" or name.strip() == "سعدی":
                    poet_id = str(p["id"])
                    set_metadata("ganjoor_saadi_id", poet_id)
                    break
        if poet_id:
            for _ in range(5):
                try:
                    poem_api_url = sanitize_plain_url(f"{base}/poem/random?poetId={poet_id}")
                    async with session.get(poem_api_url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
                        if resp.status != 200:
                            continue
                        poem = await resp.json(content_type=None)
                    beit = _extract_beit(poem)
                    if beit:
                        return beit
                except Exception:
                    continue
    except Exception:
        pass
    m1, m2, title = random.choice(FALLBACK_VERSES)
    return {"m1": m1, "m2": m2, "title": title, "url": sanitize_plain_url(GANJOOR_SAADI_FALLBACK_URL)}

def build_daily_calendar_post(verse: dict, dt: datetime) -> str:
    d = format_dates(dt)
    clean_url = sanitize_plain_url(verse.get("url", "")) or sanitize_plain_url(GANJOOR_SAADI_FALLBACK_URL)
    lines = [
        "🗓 <b>تقویم امروز و کلام سعدی</b>",
        f"📅 امروز: <b>{d['weekday']}</b> ({d['weekday_order']})",
        f"☀️ تاریخ شمسی: <b>{d['jalali']}</b>",
        f"🌍 تاریخ میلادی: <b>{d['gregorian']}</b>",
        "",
        "📜 <b>بیتی از سعدی</b>",
        f"<blockquote>{html.escape(verse['m1'])}\n{html.escape(verse['m2'])}</blockquote>",
        f"✍️ سعدی شیرازی | <a href=\"{html.escape(clean_url)}\">{html.escape(verse['title'])}</a>",
        f"\n🏷 #تقویم_روز #سعدی #شعر_فارسی{CHANNEL_SIGNATURE}",
    ]
    return "\n".join(lines)

async def publish_daily_calendar_post_if_due(session):
    current_tehran = get_current_tehran_time()
    today = current_tehran.strftime("%Y-%m-%d")
    if not (CALENDAR_POST_HOUR <= current_tehran.hour < CALENDAR_WINDOW_END_HOUR):
        return
    if get_metadata("last_calendar_post_date") == today:
        return
    verse = await fetch_saadi_verse(session)
    clean_url = sanitize_plain_url(verse.get("url", "")) or sanitize_plain_url(GANJOOR_SAADI_FALLBACK_URL)
    verse["url"] = clean_url
    text = build_daily_calendar_post(verse, current_tehran)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📜 خواندن شعر کامل در گنجور", url=clean_url)]])
    msg = await send_post(session, text, reply_markup=markup, silent=False)
    set_metadata("last_calendar_post_date", today)
    await pin_post(msg.message_id)

# ================= ۱۲. فیلم و موسیقی روزانه (ساعت ۱۲) =================
INTERNATIONAL_DAYS = {
    "02-13": ("World Radio Day", "روز جهانی رادیو"),
    "03-08": ("International Women's Day", "روز جهانی زن"),
    "03-20": ("International Day of Happiness", "روز جهانی شادی"),
    "03-21": ("World Poetry Day", "روز جهانی شعر"),
    "03-27": ("World Theatre Day", "روز جهانی تئاتر"),
    "04-15": ("World Art Day", "روز جهانی هنر"),
    "04-22": ("Earth Day", "روز جهانی زمین"),
    "04-23": ("World Book and Copyright Day", "روز جهانی کتاب و حق مؤلف"),
    "04-30": ("International Jazz Day", "روز جهانی جاز"),
    "05-03": ("World Press Freedom Day", "روز جهانی آزادی مطبوعات"),
    "05-18": ("International Museum Day", "روز جهانی موزه"),
    "06-05": ("World Environment Day", "روز جهانی محیط زیست"),
    "06-21": ("World Music Day", "روز جهانی موسیقی"),
    "07-30": ("International Day of Friendship", "روز جهانی دوستی"),
    "08-19": ("World Photography Day", "روز جهانی عکاسی"),
    "09-21": ("International Day of Peace", "روز جهانی صلح"),
    "10-01": ("International Music Day", "روز جهانی موسیقی"),
    "10-10": ("World Mental Health Day", "روز جهانی سلامت روان"),
    "11-10": ("World Science Day", "روز جهانی علم"),
    "11-13": ("World Kindness Day", "روز جهانی مهربانی"),
    "11-16": ("International Day for Tolerance", "روز جهانی مدارا"),
    "11-21": ("World Television Day", "روز جهانی تلویزیون"),
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
    imdb_rating: float = Field(description="IMDb rating strictly above 7.0")
    plot_hook_persian: str = Field(description="2 short spoiler-free sentences")
    why_today_persian: str = Field(description="1 short sentence connecting to today")

class MusicRec(BaseModel):
    artist: str
    track: str
    album: str = ""
    year: int = 0
    why_today_persian: str = Field(description="1 short sentence connecting to today")

class DailyRec(BaseModel):
    occasion_persian: str = ""
    movie: MovieRec
    music: MusicRec

async def omdb_lookup(session, title: str, year: int):
    if not OMDB_API_KEY:
        return None
    try:
        omdb_base = sanitize_plain_url(OMDB_API_BASE)
        url = sanitize_plain_url(f"{omdb_base}?apikey={OMDB_API_KEY}&t={quote_plus(title)}&y={year}&type=movie")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
            data = await resp.json(content_type=None)
        if data.get("Response") != "True":
            return None
        rating = float(data.get("imdbRating", "0"))
        votes = int(to_en_digits(data.get("imdbVotes", "0")).replace(",", "") or 0)
        raw_poster = sanitize_plain_url(str(data.get("Poster", "")))
        poster = raw_poster if raw_poster.startswith("http") else None
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
    occasion_line = f"Occasion: {occasion[0]} ({occasion[1]})." if occasion else "No special UN day; match season/date."
    prompt = f"""
Culture editor for Persian Telegram @jazebestore. Date: {dt.strftime('%A, %d %B %Y')}. {occasion_line}
Pick ONE real feature film (IMDb > 7.0) and ONE real music track (genre: {genre_key}) fitting today.
Avoid: {json.dumps(recent['movies'][-40:] + recent['music'][-40:], ensure_ascii=False)}.
Write *_persian in natural fluent Persian with half-spaces; keep titles in English.
"""
    rec = await ask_ai_json(prompt, DailyRec, temperature=0.6)
    if not rec or rec.movie.imdb_rating <= 7.0:
        return None
    info = await omdb_lookup(session, rec.movie.title_en, rec.movie.year)
    if info and info["rating"] > 7.0:
        rec.movie.imdb_rating = info["rating"]
    return rec, info, genre_key, genre_fa, occasion

def build_daily_rec_post(rec: DailyRec, info, genre_fa: str, occasion, dt: datetime) -> str:
    d = format_dates(dt)
    occ_fa = rec.occasion_persian or (occasion[1] if occasion else "")
    m, mu = rec.movie, rec.music
    e = html.escape
    lines = [f"🌍 <b>{e(persian_polish(occ_fa))}</b>" if occ_fa else "🗓 <b>پیشنهاد فرهنگی امروز</b>",
             f"📅 امروز: <b>{d['weekday']}</b> ({d['weekday_order']}) | {d['jalali']} | {d['gregorian']}",
             "", "🎬 <b>فیلم پیشنهادی امروز</b>",
             f"<b>{e(m.title_fa)} ({e(m.title_en)}، {m.year})</b>" if m.title_fa else f"<b>{e(m.title_en)} ({m.year})</b>",
             f"⭐ نمره IMDb: <b>{m.imdb_rating}/10</b>",
             e(persian_polish(m.plot_hook_persian)),
             f"💡 {e(persian_polish(m.why_today_persian))}",
             "", f"🎧 <b>موسیقی پیشنهادی | {genre_fa}</b>",
             f"<b>{e(mu.artist)} — «{e(mu.track)}»</b>",
             e(persian_polish(mu.why_today_persian)),
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
    raw_imdb = f"[https://www.imdb.com/title/](https://www.imdb.com/title/){info['id']}/" if info and info.get("id") else \
        f"[https://www.imdb.com/find/?q=](https://www.imdb.com/find/?q=){quote_plus(m.title_en + ' ' + str(m.year))}"
    imdb_url = sanitize_plain_url(raw_imdb)
    music_q = quote_plus(f"{mu.artist} {mu.track}")
    yt_url = sanitize_plain_url(f"[https://www.youtube.com/results?search_query=](https://www.youtube.com/results?search_query=){music_q}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 صفحه‌ی فیلم در IMDb", url=imdb_url)],
        [InlineKeyboardButton("▶️ شنیدن موسیقی در YouTube", url=yt_url)],
    ])
    msg = await send_post(session, text, image_url=(info or {}).get("poster"), reply_markup=markup, filename="daily_rec.jpg")
    set_metadata("last_daily_rec_date", today)
    recent = _recent_load()
    recent["movies"] = (recent["movies"] + [m.title_en])[-100:]
    recent["music"] = (recent["music"] + [f"{mu.artist} - {mu.track}"])[-100:]
    set_metadata("recent_recs", json.dumps(recent, ensure_ascii=False))
    await pin_post(msg.message_id)

async def run_daily_jobs(session):
    for job in (unpin_expired_pins, publish_daily_calendar_post_if_due, publish_daily_recommendation_if_due):
        try:
            await job(session)
        except Exception as e:
            print(f"⚠️ خطا در کار روزانه {job.__name__}: {e}")

# ================= ۱۳. جمع‌آوری هم‌زمان فیدهای RSS =================
async def fetch_single_feed(session: aiohttp.ClientSession, sem: asyncio.Semaphore, category: str, url: str) -> list[dict]:
    clean_feed_url = sanitize_plain_url(url)
    if not clean_feed_url:
        return []
    async with sem:
        try:
            async with session.get(clean_feed_url, timeout=aiohttp.ClientTimeout(total=12), headers=UA) as resp:
                if resp.status != 200:
                    return []
                xml_data = await resp.text()

            feed = await asyncio.to_thread(feedparser.parse, xml_data)
            extracted = []
            for entry in feed.entries[:2]:
                link = sanitize_plain_url(getattr(entry, 'link', None))
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
                    'source': clean_feed_url,
                    'link': link,
                    'raw_title': title[:250],
                    'raw_text': cleaned_body[:450],
                    'image_url': sanitize_plain_url(img_url) if img_url else None,
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

# ================= ۱۴. قالب ساده، مینیمال و غیرگیج‌کننده خبر =================
_CAT_EMOJI = {"gaming": "🎮", "technology": "💻", "hardware": "⚡", "crypto": "🪙", "film_tv": "🍿",
              "internet_culture": "🌐", "fun_meme": "😄", "music": "🎵", "general_news": "📰"}
_VER_ICON = {
    "تأیید رسمی": "✅",
    "گزارش رسانه‌ای": "📰",
    "پیش‌بینی تحلیلگران": "📊"
}

def format_clean_news_post(sel: SelectedNewsItem, main_cat_hashtag: str) -> str:
    lines = []
    if sel.is_breaking and sel.verification_status == "تأیید رسمی":
        lines.append("🚨 <b>خبر فوری</b>")

    lines.append(f"{_CAT_EMOJI.get(sel.category_id, '📰')} <b>{sanitize_telegram_html(sel.headline_persian)}</b>")

    cat_fa = CATEGORY_PERSIAN_NAMES.get(sel.category_id, "اخبار")
    ver = sel.verification_status if sel.verification_status in _VER_ICON else "گزارش رسانه‌ای"
    lines.append(f"📂 {cat_fa} | {_VER_ICON[ver]} <b>{ver}</b>")
    lines.append("")

    summary = re.sub(r"\s*\n\s*", " ", sel.summary_persian or "")
    lines.append(f"<blockquote>{sanitize_telegram_html(summary)}</blockquote>")

    if sel.key_points_persian:
        lines.append("")
        for pt in sel.key_points_persian[:3]:
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
    lines.append(f"\n🏷 {' '.join([main_cat_hashtag] + extra[:2])}{CHANNEL_SIGNATURE}")
    return "\n".join(lines)

def remember_news_message(item_id: int, message_id: int):
    set_metadata(f"news_msg_{item_id}", str(message_id))

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
            ORDER BY source_count DESC, id DESC LIMIT 12
        """)
    else:
        c.execute("""
            SELECT id, url, category, source, raw_title, raw_text, image_url, has_video_or_audio, source_count, is_breaking_candidate
            FROM news_items
            WHERE status IN ('pending', 'failed') AND retry_count < 3
            ORDER BY is_breaking_candidate DESC, source_count DESC, id DESC LIMIT 36
        """)

    rows = c.fetchall()
    if not rows:
        conn.close()
        return

    c.execute("""
        SELECT topic_fingerprint
        FROM news_items
        WHERE status = 'published' AND topic_fingerprint IS NOT NULL
        ORDER BY published_at DESC LIMIT 30
    """)
    recent_topics = [r[0] for r in c.fetchall() if r[0]]
    conn.close()

    all_candidates = [
        {
            'id': r[0],
            'link': sanitize_plain_url(r[1]),
            'category': r[2],
            'source': r[3],
            'title': r[4],
            'text': r[5][:420],
            'image_url': sanitize_plain_url(r[6]) if r[6] else None,
            'has_video_or_audio': bool(r[7]),
            'source_count': r[8],
            'is_breaking_candidate': bool(r[9])
        }
        for r in rows
    ]

    all_candidates.sort(key=score_candidate_locally, reverse=True)
    current_batch = all_candidates[:MAX_CANDIDATES_FOR_AI]
    dropped_ids = [item['id'] for item in all_candidates[MAX_CANDIDATES_FOR_AI:]]
    if not breaking_only and dropped_ids:
        update_news_status(dropped_ids, 'rejected')

    candidates_for_ai = [
        {
            "id": item['id'],
            "cat": item['category'],
            "src": item['source_count'],
            "text": item['text']
        }
        for item in current_batch
    ]

    prompt = f"""
Editor for '@jazebestore' (Persian Gaming/Tech/Crypto/Entertainment channel). Date: Nov 2026.
Already published (DO NOT repeat): {json.dumps(recent_topics, ensure_ascii=False)}
Candidates: {json.dumps(candidates_for_ai, ensure_ascii=False)}

RULES:
1. Pick AT MOST {max_items} best, distinct news items.
2. `verification_status` MUST be one of:
   - "تأیید رسمی": Official announcement by studio/company.
   - "گزارش رسانه‌ای": Media report/leak without official confirmation.
   - "پیش‌بینی تحلیلگران": Analyst estimates, financial projections, ASP forecasts, or rumors.
3. FACT & FINANCIAL PRECISION:
   - Never merge different analysts' estimates; name each analyst/firm next to their claim.
   - Never confuse "Average Selling Price (ASP)" (میانگین قیمت فروش) with "Official Base Price" (قیمت پایه رسمی).
   - Replace vague timeframes like "early next year" with exact years (e.g., «اوایل سال ۲۰۲۷»).
4. POLLS: Only create a poll if `verification_status` != "پیش‌بینی تحلیلگران" and `hype_score` >= 8; otherwise leave empty ("", []).
5. STYLE: Keep Persian text concise, simple, and uncluttered (2-3 short sentences + 2-3 short bullets), natural Persian with half-spaces (نیم‌فاصله) & English proper nouns.
"""

    validated_result = await generate_news_with_fallback(prompt)
    if not validated_result:
        print("❌ سرویس‌های AI موقتاً در دسترس نیستند؛ کاندیداها برای نوبت بعد حفظ شدند.")
        return

    selected_items = validated_result.selected_news[:max_items]
    batch_map = {item['id']: item for item in current_batch}
    selected_ids = {sel.selected_id for sel in selected_items if sel.selected_id in batch_map}
    non_selected_ids = [item['id'] for item in current_batch if item['id'] not in selected_ids]

    if selected_ids:
        update_news_status(list(selected_ids), 'selected')
    if not breaking_only and non_selected_ids:
        update_news_status(non_selected_ids, 'rejected')

    tehran_hour = get_current_tehran_time().hour
    silent_mode = (0 <= tehran_hour < 8) and not breaking_only

    for sel in selected_items:
        orig_item = batch_map.get(sel.selected_id)
        if not orig_item:
            continue

        polish_selected(sel)
        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig_item.get('category', 'general_news')
        main_cat_hashtag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")
        final_caption = format_clean_news_post(sel, main_cat_hashtag)

        news_link = sanitize_plain_url(orig_item.get('link', '')) or sanitize_plain_url(STORE_BASE_URL)
        keyboard = [
            [InlineKeyboardButton("❤️ پسندیدن این خبر (0)", callback_data=f"like_{orig_item['id']}")],
            [InlineKeyboardButton("🔗 مطالعه گزارش کامل در منبع اصلی", url=news_link)]
        ]
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

            if (
                not silent_mode
                and sel.verification_status != "پیش‌بینی تحلیلگران"
                and sel.hype_score >= POLL_MIN_HYPE
                and sel.poll_question_persian.strip()
                and len(sel.poll_options_persian) >= 2
            ):
                try:
                    clean_opts = [opt.strip()[:100] for opt in sel.poll_options_persian[:3] if opt.strip()]
                    if len(clean_opts) >= 2:
                        await bot.send_poll(
                            chat_id=TARGET_CHANNEL,
                            question=sel.poll_question_persian.strip()[:300],
                            options=clean_opts,
                            is_anonymous=True,
                            **_reply_kwargs(news_msg.message_id)
                        )
                except Exception as poll_err:
                    print(f"⚠️ ارسال نظرسنجی ناموفق: {poll_err}")

            await asyncio.sleep(3)

        except Exception as send_err:
            print(f"⚠️ خطا در ارسال خبر #{orig_item['id']}: {send_err}")
            update_news_status([orig_item['id']], 'failed', increment_retry=True)

# ================= ۱۵. خلاصه روزانه (ساعت ۰۰:۰۰ به وقت تهران) =================
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
        ORDER BY id DESC LIMIT 12
    """)
    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return

    digest_lines = [
        "📅 <b>مرور مهم‌ترین خبرهای ۲۴ ساعت گذشته</b>",
        f"تاریخ: {today_str}",
        ""
    ]
    for _, headline, url in rows[:8]:
        clean_h = sanitize_telegram_html(headline)
        clean_u = sanitize_plain_url(url)
        digest_lines.append(f"• <a href=\"{html.escape(clean_u)}\">{clean_h}</a>")

    digest_lines.append(f"\n🏷 #مرور_روزانه #گیمینگ #تکنولوژی{CHANNEL_SIGNATURE}")

    try:
        await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text="\n".join(digest_lines),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        set_metadata("last_daily_digest_date", today_str)
    except Exception as e:
        print(f"⚠️ خطا در ارسال خلاصه روزانه: {e}")

# ================= ۱۶. مدیریت دکمه لایک =================
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
        except Exception:
            pass

# ================= ۱۷. حلقه اصلی ۲۴ ساعته =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید...")
    else:
        print(f"Telegram network warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    print("🚀 Clean & Token-Optimized News Bot is running...")

    await asyncio.sleep(10)

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
                    print(f"\n--- [چرخه ۴۵ دقیقه‌ای | {tehran_now.strftime('%Y-%m-%d %H:%M')} تهران] ---")
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
                print(f"Error in background loop: {e}")

            await asyncio.sleep(BREAKING_CHECK_INTERVAL_SECONDS)

def main():
    print("Waiting 20 seconds for old container to shut down cleanly...")
    time.sleep(20)

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connection_pool_size(16)
        .connect_timeout(30.0)
        .read_timeout(45.0)
        .write_timeout(45.0)
        .pool_timeout(30.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(45.0)
        .http_version("1.1")
        .get_updates_http_version("1.1")
        .build()
    )
    application.add_handler(CallbackQueryHandler(button_click_handler))
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        global bot
        bot = app.bot
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            print(f"⚠️ خطای موقت در delete_webhook: {e}")
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["callback_query"],
        bootstrap_retries=-1,
        close_loop=False
    )

if __name__ == '__main__':
    main()
