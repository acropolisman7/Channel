import asyncio
import sqlite3
import re
import os
import json
import math
import html
import random
import hashlib
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus
from typing import Literal

import aiohttp
import httpx
import feedparser
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

# ================= ۱. تنظیمات اصلی و کلیدهای API =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN").strip()
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0") or 0)

GEMINI_API_KEYS = [
    k.strip() for k in [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", "")
    ] if k.strip() and not k.startswith("YOUR_")
]
GROQ_API_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
OPENROUTER_API_KEYS = [k.strip() for k in os.environ.get("OPENROUTER_API_KEYS", "").split(",") if k.strip()]

TARGET_CHANNEL = "@jazebestore"
STORE_BASE_URL = "https://jazebestore.com"
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"
DB_PATH = "rss_news_history.db"

# اولویت کیفیت بر کمیت: هر ۱ ساعت حداکثر ۳ خبر غنی + بررسی خبر فوری هر ۴ دقیقه
BREAKING_CHECK_INTERVAL_SECONDS = 240
REGULAR_CYCLE_SECONDS = 3600
MAX_NEWS_PER_CYCLE = 3
MAX_BREAKING_PER_CYCLE = 1
MAX_CANDIDATES_FOR_AI = 10
ARTICLE_MAX_CHARS = 2600
MEME_GAP_MINUTES = 55
DAILY_CALENDAR_HOUR = 9
DAILY_DIGEST_HOUR = 23

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
OPENROUTER_MODELS = ["openrouter/free", "google/gemma-3-27b-it:free"]

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}
REDDIT_UA = {"User-Agent": "JazebeStoreNewsBot/2.0 (by /u/jazebestore)"}
RLM = "\u200f"

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
    "fun_meme": "فان و میم",
    "music": "موسیقی",
    "general_news": "اخبار عمومی"
}

RSS_SOURCES = [
    ("https://blog.playstation.com/feed/", "gaming", 3),
    ("https://news.xbox.com/en-us/feed/", "gaming", 3),
    ("https://blogs.nvidia.com/feed/", "hardware", 3),
    ("https://www.videogameschronicle.com/feed/", "gaming", 3),
    ("https://www.eurogamer.net/feed", "gaming", 3),
    ("https://feeds.feedburner.com/ign/games-all", "gaming", 3),
    ("https://www.gamespot.com/feeds/mashup/", "gaming", 3),
    ("https://www.theverge.com/rss/index.xml", "technology", 3),
    ("https://feeds.arstechnica.com/arstechnica/index", "technology", 3),
    ("https://www.polygon.com/rss/index.xml", "gaming", 2),
    ("https://kotaku.com/rss", "gaming", 2),
    ("https://www.pcgamer.com/rss/", "gaming", 2),
    ("https://www.rockpapershotgun.com/feed", "gaming", 2),
    ("https://feeds.macrumors.com/MacRumors-All", "technology", 2),
    ("https://9to5mac.com/feed/", "technology", 2),
    ("https://9to5google.com/feed/", "technology", 2),
    ("https://www.tomshardware.com/feeds/all", "hardware", 2),
    ("https://wccftech.com/feed/", "hardware", 2),
    ("https://www.engadget.com/rss.xml", "technology", 2),
    ("https://techcrunch.com/feed/", "technology", 2),
    ("https://www.wired.com/feed/rss", "technology", 2),
    ("https://www.hollywoodreporter.com/feed/", "film_tv", 2),
    ("https://variety.com/feed/", "film_tv", 2),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto", 2),
    ("https://www.zoomg.ir/feed/", "gaming", 2),
    ("https://vigiato.net/feed", "gaming", 2),
    ("https://gamefa.com/feed", "gaming", 2),
    ("https://www.zoomit.ir/feed/", "technology", 2),
    ("https://digiato.com/feed", "technology", 2),
]

MEME_SUBREDDITS = {
    "gaming", "pcmasterrace", "playstation", "xbox", "nintendo",
    "memes", "dankmemes", "programmerhumor", "chatgpt", "technology",
    "gamingmemes", "spidermanps4", "gta6", "eldenring"
}

FALLBACK_VERSES = [
    ("بنی‌آدم اعضای یکدیگرند", "که در آفرینش ز یک گوهرند", "گلستان سعدی"),
    ("چو عضوی به درد آورد روزگار", "دگر عضوها را نماند قرار", "گلستان سعدی"),
    ("به جهان خرم از آنم که جهان خرم از اوست", "عاشقم بر همه عالم که همه عالم از اوست", "غزلیات سعدی"),
    ("دوست آن باشد که گیرد دست دوست", "در پریشان‌حالی و درماندگی", "بوستان سعدی"),
]

# ================= ۲. توابع کمکی زمان، نگارش فارسی و اصلاح BiDi =================
def get_current_tehran_time() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tehran"))

def sanitize_plain_url(url: str) -> str:
    if not url:
        return ""
    u = str(url).strip()
    u = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", u)
    return u.strip("[]() ")

def persian_polish(text: str) -> str:
    if not text:
        return ""
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    text = re.sub(r"\b(می|نمی)\s+([آ-ی]{2,})", r"\1\u200c\2", text)
    text = re.sub(r"([آ-ی]{2,})\s+(ها|های|هایی|تر|ترین|ام|ات|اش|ایم|اید|اند)\b", r"\1\u200c\2", text)
    return text.strip()

def fix_bidi_persian(text: str) -> str:
    """جلوگیری کامل از بهم‌ریختگی کلمات فارسی و انگلیسی در تلگرام"""
    if not text:
        return ""
    lines = text.split("\n")
    fixed_lines = []
    for line in lines:
        if not line.strip():
            fixed_lines.append("")
            continue
        if line.lstrip().startswith("<"):
            line_rtl = re.sub(r"^(<[^>]+>)", rf"\1{RLM}", line.lstrip(), count=1)
        else:
            line_rtl = f"{RLM}{line}"
        line_rtl = re.sub(
            r"(?<![\w#&;/=])([A-Za-z][A-Za-z0-9\s\.\-\+\_\:\&\']*?[A-Za-z0-9]|[A-Za-z]{2,})(?![^<]*>)",
            rf"{RLM}\1{RLM}",
            line_rtl
        )
        fixed_lines.append(line_rtl)
    return "\n".join(fixed_lines)

def sanitize_telegram_html(text: str) -> str:
    if not text:
        return ""
    allowed_patterns = [
        (r"<b>(.*?)</b>", r"[[B]]\1[[/B]]"),
        (r"<i>(.*?)</i>", r"[[I]]\1[[/I]]"),
        (r"<blockquote>(.*?)</blockquote>", r"[[BQ]]\1[[/BQ]]"),
    ]
    tmp = text
    for pat, rep in allowed_patterns:
        tmp = re.sub(pat, rep, tmp, flags=re.DOTALL | re.IGNORECASE)
    tmp = html.escape(tmp)
    tmp = tmp.replace("[[B]]", "<b>").replace("[[/B]]", "</b>")
    tmp = tmp.replace("[[I]]", "<i>").replace("[[/I]]", "</i>")
    tmp = tmp.replace("[[BQ]]", "<blockquote>").replace("[[/BQ]]", "</blockquote>")
    return tmp

def contains_keyword(text: str, keyword: str) -> bool:
    text_cf = text.casefold()
    kw_cf = keyword.casefold()
    if kw_cf.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(kw_cf)}(?![a-z0-9])"
        return re.search(pattern, text_cf) is not None
    return kw_cf in text_cf

# ================= ۳. دیتابیس و مدیریت چرخه حیات خبر =================
os.makedirs("temp_media", exist_ok=True)
provider_cooldowns: dict[str, float] = {}
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        category TEXT,
        source TEXT,
        publisher_domain TEXT,
        source_tier INTEGER DEFAULT 2,
        raw_title TEXT,
        raw_text TEXT,
        image_url TEXT,
        video_url TEXT,
        has_video_or_audio INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        is_breaking_candidate INTEGER DEFAULT 0,
        source_count INTEGER DEFAULT 1,
        retry_count INTEGER DEFAULT 0,
        embedding_json TEXT,
        topic_fingerprint TEXT,
        published_category TEXT,
        published_headline TEXT,
        published_summary TEXT,
        related_entity TEXT,
        source_published_at TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        published_at TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feed_health (
        feed_url TEXT PRIMARY KEY,
        etag TEXT,
        last_modified TEXT,
        consecutive_failures INTEGER DEFAULT 0,
        last_checked_at TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS hype_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_name TEXT,
        category TEXT,
        score REAL DEFAULT 1.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS post_likes (
        post_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (post_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
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

def compute_stable_embedding(text: str, dims: int = 128) -> list[float]:
    vec = [0.0] * dims
    tokens = re.findall(r"[a-z0-9آ-ی]{2,}", text.casefold())
    if not tokens:
        return vec
    bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    for tok in tokens + bigrams:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
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

def record_hype_event(entity_name: str, category: str, score: float):
    if not entity_name:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO hype_events (entity_name, category, score) VALUES (?, ?, ?)",
        (entity_name.strip(), category, score)
    )
    conn.commit()
    conn.close()

def detect_24h_trends(top_n: int = 6) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT entity_name, SUM(score) as total_score, COUNT(*) as mentions
        FROM hype_events
        WHERE created_at >= datetime('now', '-24 hours')
        GROUP BY lower(entity_name)
        ORDER BY total_score DESC LIMIT ?
    """, (top_n,))
    rows = c.fetchall()
    conn.close()
    return [{"entity": r[0], "score": round(r[1], 1), "mentions": r[2]} for r in rows]

# ================= ۴. اسکیمای خروجی هوش مصنوعی =================
class SelectedNewsItem(BaseModel):
    selected_id: int = Field(description="ID of the selected news candidate")
    category_id: str = Field(description="One of: gaming, technology, hardware, crypto, film_tv, internet_culture, music, general_news")
    verification_status: Literal["تأیید رسمی", "گزارش رسانه‌ای", "پیش‌بینی تحلیلگران"]
    is_breaking: bool = Field(default=False)
    headline_persian: str = Field(
        description="Fluent journalistic Persian headline starting with a Persian word (NOT an English brand name), no emojis, no HTML"
    )
    summary_persian: str = Field(
        description="3 to 5 rich, well-edited Persian sentences with exact numbers, dates, quotes, and names from the full article. Wrap 1 to 3 key facts in <b>...</b>. Never translate word-for-word."
    )
    key_points_persian: list[str] = Field(
        description="3 concise, high-value Persian bullet points"
    )
    media_note_persian: str = Field(
        default="",
        description="If the article includes a trailer, video, or audio, 1 short Persian sentence describing it; else empty string"
    )
    topic_hashtags: list[str] = Field(description="2 to 3 relevant hashtags")
    topic_fingerprint: str = Field(description="Concise English summary of the event for deduplication")
    related_game: str = Field(default="", description="Canonical English game/product/company name if applicable")
    hype_score: int = Field(default=5, ge=1, le=10)

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

class DailyDigestOutput(BaseModel):
    top_story_highlight: str = Field(description="2-3 sentence Persian editorial synthesis of the single biggest theme/trend of the past 24 hours")
    gaming_highlights: list[str] = Field(description="Up to 3 synthesized, insightful Persian bullets on top gaming developments")
    tech_hardware_highlights: list[str] = Field(description="Up to 3 synthesized, insightful Persian bullets on top tech/AI/hardware developments")
    entertainment_culture_highlights: list[str] = Field(description="Up to 2 synthesized Persian bullets on cinema/internet culture if available, else empty")
    editorial_takeaway: str = Field(description="1 crisp concluding Persian insight on what to watch tomorrow")

class MemePick(BaseModel):
    chosen_index: int = Field(description="Index of the best genuine community joke/meme, or -1")
    joke_persian: str = Field(default="", description="Witty, natural Persian adaptation of the joke/meme (NOT literal translation)")
    context_persian: str = Field(default="", description="1 short Persian sentence explaining the reference if helpful")
    is_safe_and_funny: bool = False

# ================= ۵. موتور هوش مصنوعی با چرخش خودکار =================
async def call_gemini_json(prompt: str, schema_cls, temperature: float = 0.25):
    now_ts = datetime.now().timestamp()
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            cd_key = f"gemini:{key_idx}:{model_name}"
            if provider_cooldowns.get(cd_key, 0) > now_ts:
                continue
            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema_cls,
                        temperature=temperature
                    )
                )
                raw = json.loads(resp.text)
                return schema_cls.model_validate(raw)
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "ResourceExhausted" in err_str:
                    provider_cooldowns[cd_key] = now_ts + 1800
                print(f"⚠️ خطا در Gemini ({model_name} | کلید #{key_idx}): {err_str[:140]}")
    return None

async def call_openai_compat_json(provider: str, base_url: str, keys: list[str], models: list[str], prompt: str, schema_cls, temperature: float = 0.25):
    now_ts = datetime.now().timestamp()
    clean_base = sanitize_plain_url(base_url)
    schema_hint = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
    for key_idx, api_key in enumerate(keys, start=1):
        http_client = httpx.AsyncClient(http2=False, trust_env=False, timeout=45.0)
        client = AsyncOpenAI(api_key=api_key, base_url=clean_base, http_client=http_client)
        try:
            for model_name in models:
                cd_key = f"{provider}:{key_idx}:{model_name}"
                if provider_cooldowns.get(cd_key, 0) > now_ts:
                    continue
                try:
                    comp = await client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": f"Return ONLY valid JSON matching this schema:\n{schema_hint}"},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=temperature
                    )
                    content = comp.choices[0].message.content or "{}"
                    content = re.sub(r"^```json\s*|\s*```$", "", content.strip())
                    return schema_cls.model_validate(json.loads(content))
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str:
                        provider_cooldowns[cd_key] = now_ts + 1800
                    print(f"⚠️ خطا در {provider} ({model_name} | کلید #{key_idx}): {err_str[:140]}")
        finally:
            await http_client.aclose()
    return None

async def ask_structured_ai(prompt: str, schema_cls, temperature: float = 0.25):
    res = await call_gemini_json(prompt, schema_cls, temperature)
    if res:
        return res
    if GROQ_API_KEYS:
        res = await call_openai_compat_json(
            "Groq", "https://api.groq.com/openai/v1", GROQ_API_KEYS, GROQ_MODELS, prompt, schema_cls, temperature
        )
        if res:
            return res
    if OPENROUTER_API_KEYS:
        res = await call_openai_compat_json(
            "OpenRouter", "https://openrouter.ai/api/v1", OPENROUTER_API_KEYS, OPENROUTER_MODELS, prompt, schema_cls, temperature
        )
        if res:
            return res
    return None

# ================= ۶. دریافت فیدهای RSS و استخراج متن کامل مقاله =================
def extract_domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else "unknown"

def detect_breaking_signal(title: str, text: str, tier: int) -> bool:
    combined = f"{title} {text}"
    subjects = [
        "gta vi", "gta 6", "ps5 pro", "playstation 6", "ps6", "nintendo switch 2",
        "half-life 3", "elder scrolls vi", "witcher 4", "apple", "openai", "nvidia",
        "rtx 50", "rtx 60", "steam", "valve", "rockstar", "starship", "spacex"
    ]
    action_verbs = [
        "announced", "announces", "officially", "delayed", "delay", "release date",
        "launches", "launched", "revealed", "unveiled", "canceled", "cancelled", "acquires"
    ]
    has_subject = any(contains_keyword(combined, s) for s in subjects)
    has_action = any(contains_keyword(combined, v) for v in action_verbs)
    return has_subject and has_action and tier >= 2

async def fetch_single_feed(session: aiohttp.ClientSession, sem: asyncio.Semaphore, feed_url: str, default_cat: str, tier: int):
    feed_url = sanitize_plain_url(feed_url)
    async with sem:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT etag, last_modified FROM feed_health WHERE feed_url = ?", (feed_url,))
        row = c.fetchone()
        conn.close()

        headers = dict(UA)
        if row:
            if row[0]:
                headers["If-None-Match"] = row[0]
            if row[1]:
                headers["If-Modified-Since"] = row[1]

        try:
            async with session.get(feed_url, headers=headers, timeout=14) as resp:
                if resp.status in (304, 403, 404) or resp.status != 200:
                    return
                new_etag = resp.headers.get("ETag", "")
                new_lm = resp.headers.get("Last-Modified", "")
                xml_text = await resp.text(errors="ignore")
        except Exception:
            return

        feed = await asyncio.to_thread(feedparser.parse, xml_text)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO feed_health (feed_url, etag, last_modified, consecutive_failures, last_checked_at)
            VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
        """, (feed_url, new_etag, new_lm))

        c.execute("SELECT id, publisher_domain, embedding_json FROM news_items WHERE discovered_at >= datetime('now', '-36 hours')")
        recent_items = [(r[0], r[1], json.loads(r[2])) for r in c.fetchall() if r[2]]

        for entry in feed.entries[:10]:
            link = sanitize_plain_url((getattr(entry, "link", "") or "").split("?utm_")[0].strip())
            title = html.unescape(getattr(entry, "title", "") or "").strip()
            if not link or not title:
                continue

            c.execute("SELECT 1 FROM news_items WHERE url = ?", (link,))
            if c.fetchone():
                continue

            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            clean_summary = BeautifulSoup(summary_raw, "html.parser").get_text(" ", strip=True)[:1000]
            domain = extract_domain(link)
            emb = compute_stable_embedding(f"{title} {clean_summary}")

            matched_id = None
            for r_id, r_dom, r_emb in recent_items:
                if cosine_similarity(emb, r_emb) >= 0.74:
                    matched_id = r_id
                    if r_dom != domain:
                        c.execute("UPDATE news_items SET source_count = source_count + 1 WHERE id = ?", (r_id,))
                    break
            if matched_id:
                continue

            img_url = ""
            if getattr(entry, "media_content", None):
                img_url = entry.media_content[0].get("url", "")
            if not img_url and getattr(entry, "media_thumbnail", None):
                img_url = entry.media_thumbnail[0].get("url", "")
            if not img_url:
                m_img = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', summary_raw, re.I)
                if m_img:
                    img_url = m_img.group(1)

            has_av = 1 if re.search(r"trailer|showcase|gameplay|podcast|video|youtube|watch", f"{title} {clean_summary}", re.I) else 0
            is_brk = 1 if detect_breaking_signal(title, clean_summary, tier) else 0
            pub_date = getattr(entry, "published", "") or ""

            c.execute("""
                INSERT OR IGNORE INTO news_items
                (url, category, source, publisher_domain, source_tier, raw_title, raw_text, image_url,
                 has_video_or_audio, status, is_breaking_candidate, embedding_json, source_published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (
                link, default_cat, feed_url, domain, tier, title,
                f"{title}\n{clean_summary}", sanitize_plain_url(img_url), has_av, is_brk,
                json.dumps(emb), pub_date
            ))
            if c.lastrowid:
                recent_items.append((c.lastrowid, domain, emb))

        conn.commit()
        conn.close()

async def collect_all_feeds(session: aiohttp.ClientSession):
    sem = asyncio.Semaphore(10)
    tasks = [fetch_single_feed(session, sem, url, cat, tier) for url, cat, tier in RSS_SOURCES]
    await asyncio.gather(*tasks, return_exceptions=True)

_NOISE_RE = re.compile(r"cookie|subscribe|newsletter|sign up|all rights reserved|advertisement|read more", re.I)

def _normalize_video_url(url: str) -> str:
    if not url:
        return ""
    url = sanitize_plain_url(url)
    m = re.search(r"youtube\.com/embed/([\w-]{6,})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url

async def fetch_full_article_and_media(session: aiohttp.ClientSession, url: str) -> tuple[str, str, str]:
    url = sanitize_plain_url(url)
    try:
        async with session.get(url, timeout=12, headers=UA) as resp:
            if resp.status != 200 or "html" not in resp.headers.get("Content-Type", "").lower():
                return "", "", ""
            html_page = await resp.text(errors="ignore")
            soup = BeautifulSoup(html_page, "html.parser")

            og_img = ""
            img_tag = soup.find("meta", property="og:image")
            if img_tag and img_tag.get("content", "").startswith("http"):
                og_img = sanitize_plain_url(img_tag["content"])

            video_url = ""
            for prop in ("og:video:url", "og:video", "og:video:secure_url"):
                v_tag = soup.find("meta", property=prop)
                if v_tag and v_tag.get("content", "").startswith("http"):
                    video_url = sanitize_plain_url(v_tag["content"])
                    break
            if not video_url:
                iframe = soup.find("iframe", src=re.compile(r"youtube\.com/embed|youtu\.be|player\.vimeo"))
                if iframe:
                    src = iframe.get("src", "")
                    video_url = ("https:" + src) if src.startswith("//") else src

            for tag in soup(["script", "style", "nav", "aside", "footer", "form", "header", "noscript"]):
                tag.decompose()
            container = soup.find("article") or soup.find("main") or soup
            paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
            paras = [p for p in paras if len(p) > 45 and not _NOISE_RE.search(p)]
            body = " ".join(paras)[:ARTICLE_MAX_CHARS]
            return body, _normalize_video_url(video_url), og_img
    except Exception:
        return "", "", ""

def score_candidate_locally(item: dict) -> float:
    score = 0.0
    score += item.get("source_tier", 2) * 18.0
    score += min(item.get("source_count", 1), 4) * 15.0
    if item.get("is_breaking_candidate"):
        score += 25.0
    if item.get("image_url"):
        score += 16.0
    if item.get("has_video_or_audio"):
        score += 20.0
    if len(item.get("raw_text", "")) > 350:
        score += 10.0
    hot_topics = [
        "playstation", "ps5", "xbox", "nintendo", "switch 2", "steam", "gta",
        "nvidia", "rtx", "apple", "iphone", "openai", "gemini", "ai", "spacex", "starship"
    ]
    low_title = item.get("raw_title", "").casefold()
    if any(contains_keyword(low_title, kw) for kw in hot_topics):
        score += 14.0
    return score

# ================= ۷. قالب‌بندی و انتشار اخبار باکیفیت =================
async def download_image_from_url(session: aiohttp.ClientSession, url: str, filename: str) -> str:
    url = sanitize_plain_url(url)
    if not url or not url.startswith("http"):
        return ""
    path = os.path.join("temp_media", filename)
    try:
        async with session.get(url, timeout=15, headers=UA) as resp:
            if resp.status != 200:
                return ""
            ctype = resp.headers.get("Content-Type", "").lower()
            if "image" not in ctype and not re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I):
                return ""
            data = await resp.read()
            if len(data) < 4096 or len(data) > 9_000_000:
                return ""
            with open(path, "wb") as f:
                f.write(data)
            return path
    except Exception:
        return ""

def format_quality_news_post(sel: SelectedNewsItem, cat_id: str) -> str:
    status_icons = {
        "تأیید رسمی": "✅",
        "گزارش رسانه‌ای": "📰",
        "پیش‌بینی تحلیلگران": "📊"
    }
    st_icon = status_icons.get(sel.verification_status, "📰")
    cat_persian = CATEGORY_PERSIAN_NAMES.get(cat_id, "اخبار")
    main_tag = CATEGORY_HASHTAGS.get(cat_id, "#اخبار")

    headline = persian_polish(html.escape(sel.headline_persian))
    summary = sanitize_telegram_html(persian_polish(sel.summary_persian))
    bullets = [persian_polish(html.escape(b.lstrip("•-🔹 ").strip())) for b in sel.key_points_persian[:3] if b.strip()]

    prefix = "🚨 <b>خبر فوری</b>\n" if sel.is_breaking else ""
    lines = [
        f"{prefix}🌐 <b>{headline}</b>",
        f"📂 {cat_persian} | {st_icon} <b>{sel.verification_status}</b>",
        "",
        f"<blockquote>{summary}</blockquote>"
    ]

    if bullets:
        lines.append("")
        for b in bullets:
            lines.append(f"🔹 {b}")

    if sel.media_note_persian and sel.media_note_persian.strip():
        note = persian_polish(html.escape(sel.media_note_persian.strip()))
        lines.append(f"\n🎬 <i>{note}</i>")

    clean_tags = [main_tag]
    for t in sel.topic_hashtags[:2]:
        t_clean = "#" + re.sub(r"[^\wآ-ی]", "_", t.lstrip("#").strip())
        if len(t_clean) > 2 and t_clean not in clean_tags:
            clean_tags.append(t_clean)

    lines.append(f"\n🏷 {' '.join(clean_tags)}{CHANNEL_SIGNATURE}")
    return fix_bidi_persian("\n".join(lines))

async def process_and_publish_batch(session: aiohttp.ClientSession, breaking_only: bool = False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if breaking_only:
        c.execute("""
            SELECT id, url, category, publisher_domain, source_tier, raw_title, raw_text, image_url, video_url, has_video_or_audio, source_count, is_breaking_candidate
            FROM news_items
            WHERE status = 'pending' AND is_breaking_candidate = 1
            ORDER BY source_tier DESC, source_count DESC, id DESC LIMIT 8
        """)
    else:
        c.execute("""
            SELECT id, url, category, publisher_domain, source_tier, raw_title, raw_text, image_url, video_url, has_video_or_audio, source_count, is_breaking_candidate
            FROM news_items
            WHERE status = 'pending'
            ORDER BY id DESC LIMIT 45
        """)
    rows = c.fetchall()

    c.execute("""
        SELECT topic_fingerprint FROM news_items
        WHERE status = 'published' AND topic_fingerprint IS NOT NULL
        ORDER BY published_at DESC LIMIT 60
    """)
    recent_topics = [r[0] for r in c.fetchall() if r[0]]
    conn.close()

    if not rows:
        return

    candidates = []
    for r in rows:
        item = {
            "id": r[0], "url": sanitize_plain_url(r[1]), "category": r[2], "domain": r[3],
            "source_tier": r[4], "raw_title": r[5], "raw_text": r[6],
            "image_url": sanitize_plain_url(r[7] or ""), "video_url": sanitize_plain_url(r[8] or ""),
            "has_video_or_audio": bool(r[9]), "source_count": r[10],
            "is_breaking_candidate": bool(r[11])
        }
        item["local_score"] = score_candidate_locally(item)
        candidates.append(item)

    candidates.sort(key=lambda x: x["local_score"], reverse=True)
    top_candidates = candidates[:(4 if breaking_only else MAX_CANDIDATES_FOR_AI)]

    async def enrich_before_ai(it: dict):
        body, vid, og_img = await fetch_full_article_and_media(session, it["url"])
        it["full_article"] = body if (body and len(body) > 250) else it["raw_text"]
        if vid and not it["video_url"]:
            it["video_url"] = vid
            it["has_video_or_audio"] = True
        if og_img and not it["image_url"]:
            it["image_url"] = og_img

    await asyncio.gather(*(enrich_before_ai(it) for it in top_candidates), return_exceptions=True)

    max_pick = MAX_BREAKING_PER_CYCLE if breaking_only else MAX_NEWS_PER_CYCLE
    ai_input = [
        {
            "id": it["id"],
            "default_category": it["category"],
            "source_domain": it["domain"],
            "independent_sources_count": it["source_count"],
            "has_image": bool(it["image_url"]),
            "has_video_or_audio": it["has_video_or_audio"],
            "full_article_text": it["full_article"]
        }
        for it in top_candidates
    ]

    prompt = f"""
You are the Senior Chief Editor for '@jazebestore', a Persian Gaming, Technology, and Hardware Telegram channel.
Current Year: 2026.

CRITICAL EDITORIAL PHILOSOPHY — QUALITY OVER QUANTITY:
- Select AT MOST {max_pick} truly standout, high-value stories (even 2 exceptional stories is better than 3 mediocre ones).
- Prioritize stories with `has_image` = true or `has_video_or_audio` = true AND rich factual depth.
- NEVER repeat any topic in `already_published`:
{json.dumps(recent_topics, ensure_ascii=False)}

STRICT PERSIAN JOURNALISTIC WRITING & ACCURACY RULES:
1. NO LITERAL / MACHINE TRANSLATION (ترجمه ماشینی اکیداً ممنوع):
   - Rewrite each story as an original, fluent, engaging Persian journalistic report.
   - Use natural Persian idioms (e.g., «صف بررسی بازی‌های Steam» instead of «پشت‌سرگیری بررسی‌ها»; «محتوای ساخته‌شده با هوش مصنوعی» instead of «ارسال‌های AI»; «مهار و بازیابی مرحله بالایی Starship» instead of «گرفتن مرحله بالایی»).
2. START EVERY HEADLINE & SENTENCE WITH A PERSIAN WORD:
   - Never start `headline_persian` or `summary_persian` with an English word (e.g., write «تلاش بی‌سابقه SpaceX برای...» instead of «SpaceX برای اولین بار...»).
   - Keep brand names, game titles, and hardware models in exact English.
3. RICH DETAIL & ATTRIBUTION:
   - Include concrete numbers, prices, release windows, and direct attributions from `full_article_text`.
   - Wrap 1 to 3 key facts/numbers in `<b>...</b>` inside `summary_persian`.
4. `verification_status` must strictly be one of: "تأیید رسمی", "گزارش رسانه‌ای", or "پیش‌بینی تحلیلگران".

Candidates:
{json.dumps(ai_input, ensure_ascii=False)}
"""

    result = await ask_structured_ai(prompt, BatchProcessResult, temperature=0.25)
    if not result or not result.selected_news:
        return

    chosen_list = result.selected_news[:max_pick]
    cand_map = {it["id"]: it for it in top_candidates}
    chosen_ids = {s.selected_id for s in chosen_list if s.selected_id in cand_map}

    all_row_ids = [r[0] for r in rows]
    rejected_ids = [rid for rid in all_row_ids if rid not in chosen_ids]
    if rejected_ids and not breaking_only:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        ph = ",".join(["?"] * len(rejected_ids))
        c.execute(f"UPDATE news_items SET status = 'rejected' WHERE id IN ({ph})", rejected_ids)
        conn.commit()
        conn.close()

    tehran_hr = get_current_tehran_time().hour
    silent = (0 <= tehran_hr < 8) and not breaking_only

    for sel in chosen_list:
        orig = cand_map.get(sel.selected_id)
        if not orig:
            continue

        cat_id = sel.category_id if sel.category_id in CATEGORY_HASHTAGS else orig["category"]
        caption = format_quality_news_post(sel, cat_id)

        kb = [
            [
                InlineKeyboardButton("❤️ پسندیدن (0)", callback_data=f"like_{orig['id']}"),
                InlineKeyboardButton("🔗 منبع اصلی خبر", url=sanitize_plain_url(orig["url"]))
            ]
        ]
        if orig.get("video_url"):
            kb.append([InlineKeyboardButton("🎬 تماشای ویدیو / تریلر مرتبط", url=sanitize_plain_url(orig["video_url"]))])
        markup = InlineKeyboardMarkup(kb)

        sent_msg = None
        try:
            img_path = ""
            if orig.get("image_url"):
                img_path = await download_image_from_url(session, orig["image_url"], f"news_{orig['id']}.jpg")

            if img_path and os.path.exists(img_path) and len(caption) <= 1020:
                with open(img_path, "rb") as f:
                    sent_msg = await bot.send_photo(
                        chat_id=TARGET_CHANNEL,
                        photo=f,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=markup,
                        disable_notification=silent
                    )
            else:
                preview_url = orig.get("video_url") or orig.get("image_url") or ""
                link_opts = LinkPreviewOptions(
                    url=preview_url,
                    prefer_large_media=True,
                    show_above_text=True
                ) if preview_url else LinkPreviewOptions(is_disabled=True)

                sent_msg = await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                    link_preview_options=link_opts,
                    disable_notification=silent
                )

            if img_path and os.path.exists(img_path):
                os.remove(img_path)

            if sent_msg:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("""
                    UPDATE news_items
                    SET status = 'published', published_at = CURRENT_TIMESTAMP,
                        topic_fingerprint = ?, published_category = ?,
                        published_headline = ?, published_summary = ?, related_entity = ?
                    WHERE id = ?
                """, (
                    sel.topic_fingerprint, cat_id, sel.headline_persian,
                    sel.summary_persian, sel.related_game, orig["id"]
                ))
                conn.commit()
                conn.close()

                set_metadata(f"news_msg_{orig['id']}", str(sent_msg.message_id))
                if sel.related_game:
                    record_hype_event(sel.related_game, cat_id, float(sel.hype_score))

            await asyncio.sleep(5)
        except Exception as e:
            print(f"⚠️ خطا در انتشار خبر #{orig['id']}: {e}")

# ================= ۸. بخش تضمینی میم و شوخی کاربران =================
def _get_seen_memes() -> list[str]:
    try:
        return json.loads(get_metadata("seen_memes", "[]"))
    except Exception:
        return []

async def fetch_reddit_memes(session: aiohttp.ClientSession, query: str) -> list[dict]:
    seen = set(_get_seen_memes())
    out = []
    for period in ("day", "week"):
        url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=top&t={period}&limit=25"
        try:
            async with session.get(url, timeout=15, headers=REDDIT_UA) as resp:
                if resp.status != 200:
                    continue
                xml = await resp.text()
        except Exception:
            continue

        feed = await asyncio.to_thread(feedparser.parse, xml)
        for entry in feed.entries:
            tags = getattr(entry, "tags", []) or []
            sub = str(tags[0].get("term", "")).lower() if tags else ""
            link = sanitize_plain_url(getattr(entry, "link", ""))
            if sub not in MEME_SUBREDDITS or not link or link in seen:
                continue
            body = entry.content[0].value if getattr(entry, "content", None) else ""
            m = re.search(r"https://(?:i|preview)\.redd\.it/[^\"\']+?\.(?:jpe?g|png|webp)[^\"\']*", body)
            img = html.unescape(m.group(0)) if m else ""
            if not img and getattr(entry, "media_thumbnail", None):
                img = entry.media_thumbnail[0].get("url", "")
            out.append({
                "index": len(out),
                "subreddit": sub,
                "title": (entry.title or "")[:220],
                "link": link,
                "image": sanitize_plain_url(img)
            })
            if len(out) >= 6:
                return out
        if out:
            break
    return out

async def publish_community_meme_if_due(session: aiohttp.ClientSession):
    tehran_now = get_current_tehran_time()
    if 0 <= tehran_now.hour < 9:
        return

    last_ts = float(get_metadata("last_meme_ts", "0") or 0)
    if tehran_now.timestamp() - last_ts < MEME_GAP_MINUTES * 60:
        return

    trends = [t["entity"] for t in detect_24h_trends(top_n=4)]
    fallback_queries = ["PlayStation gaming meme", "PC gaming meme", "AI meme", "GTA 6 meme", "Steam meme"]
    search_queries = trends + [q for q in fallback_queries if q not in trends]

    for query in search_queries[:4]:
        cands = await fetch_reddit_memes(session, query)
        if not cands:
            continue

        reply_to_id = None
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT id FROM news_items
            WHERE status = 'published' AND lower(related_entity) LIKE ?
              AND published_at >= datetime('now', '-24 hours')
            ORDER BY id DESC LIMIT 1
        """, (f"%{query.lower()}%",))
        row = c.fetchone()
        conn.close()
        if row:
            mid = get_metadata(f"news_msg_{row[0]}", "")
            if mid.isdigit():
                reply_to_id = int(mid)

        prompt = f"""
Topic context: {query}
Candidate Reddit community posts:
{json.dumps([{k: x[k] for k in ("index", "subreddit", "title")} for x in cands], ensure_ascii=False)}

Select the ONE candidate that is genuinely funny, witty, and relatable for a Persian gaming/tech audience (chosen_index = -1 if none).
- Adapt the humor into natural, punchy Persian (`joke_persian`) — NOT word-for-word translation. Start with a Persian word.
- Reject anything offensive, political, religious, or NSFW (`is_safe_and_funny` = false).
"""
        pick = await ask_structured_ai(prompt, MemePick, temperature=0.45)
        if not pick or pick.chosen_index < 0 or pick.chosen_index >= len(cands) or not pick.is_safe_and_funny:
            continue

        chosen = cands[pick.chosen_index]
        joke_fa = persian_polish(html.escape(pick.joke_persian.strip()))
        ctx_fa = persian_polish(html.escape(pick.context_persian.strip()))

        lines = [
            "😄 <b>شوخی و میم کاربران فضای مجازی</b>",
            "",
            f"<blockquote>{joke_fa}</blockquote>"
        ]
        if ctx_fa:
            lines.append(f"💬 <i>{ctx_fa}</i>")
        lines.append(f"📎 انجمن Reddit (r/{html.escape(chosen['subreddit'])})")
        lines.append(f"\n🏷 #میم #فان #شوخی_کاربران{CHANNEL_SIGNATURE}")

        final_text = fix_bidi_persian("\n".join(lines))
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 مشاهده پست اصلی در Reddit", url=chosen["link"])]])

        try:
            img_path = ""
            if chosen.get("image"):
                img_path = await download_image_from_url(session, chosen["image"], f"meme_{chosen['index']}.jpg")

            if img_path and os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    await bot.send_photo(
                        chat_id=TARGET_CHANNEL,
                        photo=f,
                        caption=final_text,
                        parse_mode="HTML",
                        reply_markup=markup,
                        reply_to_message_id=reply_to_id
                    )
                os.remove(img_path)
            else:
                await bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=final_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                    reply_to_message_id=reply_to_id
                )

            seen_updated = (_get_seen_memes() + [chosen["link"]])[-300:]
            set_metadata("seen_memes", json.dumps(seen_updated))
            set_metadata("last_meme_ts", str(tehran_now.timestamp()))
            return
        except Exception as e:
            print(f"⚠️ خطا در ارسال میم کاربران: {e}")

# ================= ۹. پست صبحگاهی تقویم و شعر سعدی + مرور تحلیلی شبانه =================
async def fetch_saadi_verse(session: aiohttp.ClientSession) -> dict:
    base = "https://api.ganjoor.net/api/ganjoor"
    try:
        for _ in range(5):
            async with session.get(f"{base}/poem/random?poetId=7", timeout=12, headers=UA) as resp:
                if resp.status != 200:
                    continue
                poem = await resp.json(content_type=None)
            verses = poem.get("verses") or []
            full_url = poem.get("fullUrl") or ""
            for i in range(len(verses) - 1):
                a, b = verses[i], verses[i + 1]
                if a.get("versePosition") == 0 and b.get("versePosition") == 1:
                    m1, m2 = (a.get("text") or "").strip(), (b.get("text") or "").strip()
                    if 8 <= len(m1) <= 90 and 8 <= len(m2) <= 90:
                        return {
                            "m1": persian_polish(m1),
                            "m2": persian_polish(m2),
                            "title": poem.get("fullTitle") or "دیوان سعدی",
                            "url": sanitize_plain_url("https://ganjoor.net" + full_url)
                        }
    except Exception:
        pass
    m1, m2, title = random.choice(FALLBACK_VERSES)
    return {"m1": m1, "m2": m2, "title": title, "url": "https://ganjoor.net/saadi"}

async def publish_daily_calendar_post_if_due(session: aiohttp.ClientSession):
    tehran_now = get_current_tehran_time()
    if tehran_now.hour != DAILY_CALENDAR_HOUR:
        return
    today_str = tehran_now.strftime("%Y-%m-%d")
    if get_metadata("last_calendar_date") == today_str:
        return

    beit = await fetch_saadi_verse(session)
    lines = [
        f"📅 <b>تقویم امروز و شعر صبحگاهی</b>",
        f"🗓 تاریخ میلادی: {today_str}",
        "",
        f"📜 <b>بیتی از سعدی ({html.escape(beit['title'])}):</b>",
        f"<blockquote>{html.escape(beit['m1'])}\n{html.escape(beit['m2'])}</blockquote>",
        f"\n🏷 #تقویم_روز #سعدی{CHANNEL_SIGNATURE}"
    ]
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📜 خواندن شعر کامل", url=beit["url"])]])
    try:
        msg = await bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=fix_bidi_persian("\n".join(lines)),
            parse_mode="HTML",
            reply_markup=markup
        )
        set_metadata("last_calendar_date", today_str)
        try:
            await bot.pin_chat_message(chat_id=TARGET_CHANNEL, message_id=msg.message_id, disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ خطا در ارسال پست تقویم روزانه: {e}")

async def publish_daily_digest_if_due():
    tehran_now = get_current_tehran_time()
    if tehran_now.hour != DAILY_DIGEST_HOUR:
        return

    today_str = tehran_now.strftime("%Y-%m-%d")
    if get_metadata("last_digest_date") == today_str:
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT published_category, published_headline, published_summary
        FROM news_items
        WHERE status = 'published' AND published_at >= datetime('now', '-24 hours')
        ORDER BY id DESC LIMIT 25
    """)
    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return

    archive_items = [
        {"category": r[0], "headline": r[1], "summary": (r[2] or "")[:300]}
        for r in rows
    ]

    prompt = f"""
You are the Editor-in-Chief of '@jazebestore'. Date: {today_str}.
Below are the news stories published in the last 24 hours:
{json.dumps(archive_items, ensure_ascii=False)}

TASK: Create an insightful, synthesized Persian 24-Hour Executive Briefing (`DailyDigestOutput`).
CRITICAL RULES:
- DO NOT copy-paste the raw headlines verbatim. Synthesize, group related developments, and explain WHY they matter in sharp, journalistic Persian.
- Start every bullet and sentence with a Persian word (keep brand/game names in English).
"""
    digest = await ask_structured_ai(prompt, DailyDigestOutput, temperature=0.3)
    if not digest:
        return

    lines = [
        "📅 <b>پرونده جمع‌بندی و تحلیل مهم‌ترین رویدادهای ۲۴ ساعت گذشته</b>",
        f"🗓 تاریخ: {today_str}",
        "",
        "🔥 <b>مهم‌ترین جریان روز:</b>",
        f"<blockquote>{persian_polish(html.escape(digest.top_story_highlight))}</blockquote>"
    ]

    if digest.gaming_highlights:
        lines.append("\n🎮 <b>نبض دنیای گیمینگ:</b>")
        for g in digest.gaming_highlights[:3]:
            lines.append(f"• {persian_polish(html.escape(g))}")

    if digest.tech_hardware_highlights:
        lines.append("\n💻 <b>تکنولوژی، هوش مصنوعی و سخت‌افزار:</b>")
        for t in digest.tech_hardware_highlights[:3]:
            lines.append(f"• {persian_polish(html.escape(t))}")

    if digest.entertainment_culture_highlights:
        lines.append("\n🎬 <b>سینما و فرهنگ اینترنتی:</b>")
        for ec in digest.entertainment_culture_highlights[:2]:
            lines.append(f"• {persian_polish(html.escape(ec))}")

    if digest.editorial_takeaway:
        lines.append(f"\n🧭 <b>چشم‌انداز فردا:</b> {persian_polish(html.escape(digest.editorial_takeaway))}")

    lines.append(f"\n🏷 #مرور_روزانه #جمع_بندی #گیمینگ #تکنولوژی{CHANNEL_SIGNATURE}")
    final_digest = fix_bidi_persian("\n".join(lines))

    try:
        await bot.send_message(chat_id=TARGET_CHANNEL, text=final_digest, parse_mode="HTML")
        set_metadata("last_digest_date", today_str)
    except Exception as e:
        print(f"⚠️ خطا در ارسال مرور روزانه: {e}")

# ================= ۱۰. هندلرهای تلگرام (/status, /correct, دکمه لایک) =================
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

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    already = c.fetchone() is not None
    if already:
        c.execute("DELETE FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        toast = "لایک شما برداشته شد."
    else:
        c.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, user_id))
        toast = "❤️ ممنون از همراهی شما!"
    c.execute("SELECT COUNT(*) FROM post_likes WHERE post_id = ?", (post_id,))
    total_likes = c.fetchone()[0]
    conn.commit()
    conn.close()

    await query.answer(toast)
    try:
        old_markup = query.message.reply_markup
        if old_markup and old_markup.inline_keyboard:
            new_rows = []
            for row in old_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    if btn.callback_data == query.data:
                        new_row.append(InlineKeyboardButton(f"❤️ پسندیدن ({total_likes})", callback_data=btn.callback_data))
                    else:
                        new_row.append(btn)
                new_rows.append(new_row)
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        pass

async def handle_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_USER_ID and update.effective_user.id != ADMIN_USER_ID:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news_items WHERE status = 'published' AND published_at >= datetime('now', '-24 hours')")
    pub_24h = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM news_items WHERE status = 'pending'")
    pending_cnt = c.fetchone()[0]
    conn.close()

    report = (
        f"📊 <b>وضعیت ربات تحریریه @jazebestore</b>\n"
        f"• اخبار منتشرشده در ۲۴ ساعت اخیر: <b>{pub_24h}</b>\n"
        f"• اخبار در صف بررسی: <b>{pending_cnt}</b>\n"
        f"• حالت چرخه عادی: هر ۱ ساعت (حداکثر {MAX_NEWS_PER_CYCLE} خبر باکیفیت)\n"
        f"• آخرین میم ارسالی: {get_metadata('last_meme_ts', 'ثبت نشده')}"
    )
    await update.message.reply_text(fix_bidi_persian(report), parse_mode="HTML")

async def handle_correct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال اصلاحیه رسمی برای یک خبر منتشرشده توسط ادمین"""
    if ADMIN_USER_ID and update.effective_user.id != ADMIN_USER_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("فرمت دستور:\n/correct <news_id> <متن اصلاحیه>")
        return
    news_id = context.args[0]
    correction_text = " ".join(context.args[1:])
    msg_id_str = get_metadata(f"news_msg_{news_id}", "")
    reply_id = int(msg_id_str) if msg_id_str.isdigit() else None

    post_text = fix_bidi_persian(
        f"📝 <b>اصلاحیه تحریریه</b>\n\n"
        f"<blockquote>{persian_polish(html.escape(correction_text))}</blockquote>"
        f"{CHANNEL_SIGNATURE}"
    )
    await bot.send_message(
        chat_id=TARGET_CHANNEL,
        text=post_text,
        parse_mode="HTML",
        reply_to_message_id=reply_id
    )
    await update.message.reply_text("✅ اصلاحیه در کانال منتشر شد.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    err_msg = str(err)
    if isinstance(err, (NetworkError, TimedOut)):
        print(f"🌐 نوسان موقت اتصال به سرور تلگرام: {err_msg[:120]}")
    elif "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام جایگزینی کانتینر در Railway...")
    else:
        print(f"⚠️ هشدار تلگرام: {err_msg[:160]}")

# ================= ۱۱. حلقه اصلی ۲۴ ساعته و راه‌اندازی ایمن =================
async def background_news_loop():
    init_db()
    last_regular_ts = 0.0
    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    async with aiohttp.ClientSession(connector=connector) as shared_session:
        while True:
            try:
                now_ts = datetime.now().timestamp()
                await collect_all_feeds(shared_session)

                # بررسی خبر فوری
                await process_and_publish_batch(shared_session, breaking_only=True)

                # چرخه ۱ ساعته: حداکثر ۳ خبر باکیفیت + میم کاربران
                if now_ts - last_regular_ts >= REGULAR_CYCLE_SECONDS:
                    await process_and_publish_batch(shared_session, breaking_only=False)
                    await publish_community_meme_if_due(shared_session)
                    last_regular_ts = now_ts

                # پست صبحگاهی تقویم و شعر سعدی + مرور تحلیلی شبانه
                await publish_daily_calendar_post_if_due(shared_session)
                await publish_daily_digest_if_due()
            except Exception as loop_err:
                print(f"⚠️ خطا در حلقه اصلی ربات: {loop_err}")

            await asyncio.sleep(BREAKING_CHECK_INTERVAL_SECONDS)

async def post_init(application: Application):
    global bot
    bot = application.bot
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    asyncio.create_task(background_news_loop())

def main():
    print("Waiting 15 seconds for old container to shut down cleanly...")
    time.sleep(15)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connection_pool_size(16)
        .connect_timeout(30.0)
        .read_timeout(45.0)
        .write_timeout(45.0)
        .pool_timeout(30.0)
        .http_version("1.1")
        .get_updates_http_version("1.1")
        .post_init(post_init)
        .build()
    )
    app.add_handler(CallbackQueryHandler(handle_like_callback, pattern=r"^like_\d+$"))
    app.add_handler(CommandHandler("status", handle_status_command))
    app.add_handler(CommandHandler("correct", handle_correct_command))
    app.add_error_handler(error_handler)

    print("🚀 ربات تحریریه @jazebestore با موفقیت راه‌اندازی شد...")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=False,
        bootstrap_retries=-1,
        close_loop=False
    )

if __name__ == "__main__":
    main()