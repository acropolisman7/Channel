import asyncio
import sqlite3
import re
import os
import json
import random
from urllib.parse import urljoin, urlparse
import aiohttp
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

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

CHECK_INTERVAL_SECONDS = 3600   # اجرای چرخه هر ۱ ساعت
MAX_NEWS_PER_HOUR = 10          # حداکثر ۱۰ خبر برتر در هر ساعت
MAX_CANDIDATES_FOR_AI = 65      # حداکثر ۶۵ خبر خام ارسالی به AI
PRODUCTS_PER_HOUR = 3           # انتشار ۳ محصول رندوم موجود در هر ساعت

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

# ================= ۲. راه‌اندازی دیتابیس و کلاینت‌ها =================
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
    c.execute('''CREATE TABLE IF NOT EXISTS post_likes 
                 (post_id TEXT PRIMARY KEY, 
                  like_count INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recent_products 
                 (product_id TEXT PRIMARY KEY, 
                  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

def get_recently_sent_product_ids():
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("DELETE FROM recent_products WHERE sent_at <= datetime('now', '-24 hours')")
    conn.commit()
    c.execute("SELECT product_id FROM recent_products")
    ids = {row[0] for row in c.fetchall()}
    conn.close()
    return ids

def mark_product_sent(product_id):
    conn = sqlite3.connect('rss_news_history.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO recent_products (product_id, sent_at) VALUES (?, CURRENT_TIMESTAMP)", (str(product_id),))
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

class BatchProcessResult(BaseModel):
    selected_news: list[SelectedNewsItem]

# ================= ۵. موتور پردازش چندگانه AI (Multi-Key & Multi-Provider) =================
async def generate_news_with_fallback(prompt: str) -> dict | None:
    # ۱. تست تمام کلیدها و مدل‌های جمنای
    for key_idx, api_key in enumerate(GEMINI_API_KEYS, start=1):
        temp_client = genai.Client(api_key=api_key)
        for model_name in GEMINI_MODELS:
            try:
                print(f"تلاش با جمنای (کلید #{key_idx} | مدل: {model_name})...")
                response = temp_client.models.generate_content(
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
      ]
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

# ================= ۷. پردازش هوشمند و انتشار اخبار در کانال =================
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
    You are the Chief Editor for a popular Persian Telegram channel covering Gaming, Tech, Hardware, Crypto, Entertainment, and World News.
    
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
    """

    result_data = await generate_news_with_fallback(prompt)

    if not result_data:
        print("❌ تمامی کلیدها و سرویس‌های AI با خطا یا محدودیت مواجه شدند. این چرخه خبری رد شد.")
        pending_news_buffer.clear()
        return

    try:
        selected_items = result_data.get("selected_news", [])[:MAX_NEWS_PER_HOUR]
        batch_map = {item['id']: item for item in current_batch}

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
            final_caption = f"{sel['final_persian_text'].strip()}\n\n🏷 {hashtags_line}{CHANNEL_SIGNATURE}"
            save_published_topic(sel['topic_fingerprint'])

            news_link = orig_item.get('link', 'https://t.me/jazebestore')
            keyboard = [
                [
                    InlineKeyboardButton("❤️ 0", callback_data=f"like_{orig_item['id']}"),
                    InlineKeyboardButton("🔗 متن کامل خبر", url=news_link)
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

        pending_news_buffer.clear()

    except Exception as e:
        print(f"Error publishing news to channel: {e}")
        pending_news_buffer.clear()

# ================= ۸. بخش فروشگاه: دریافت هوشمند محصولات از Sitemap و HTML =================
async def discover_product_urls_from_site(session) -> list[str]:
    """یافتن لینک صفحات محصولات از طریق Sitemap و صفحات عمومی سایت"""
    product_urls = set()
    product_keywords = ['/product/', '/products/', '/p/', '/item/', '/shop/']

    # ۱. بررسی نقشه سایت (Sitemap)
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

    # بررسی زیرمجموعه‌های سایت‌مپ (اگر وجود داشت)
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

    # ۲. اسکرپ لینک‌های صفحه اصلی و صفحه فروشگاه در صورت خالی بودن سایت‌مپ
    if len(product_urls) < 10:
        for page_url in [STORE_URL, f"{STORE_URL}/shop/", f"{STORE_URL}/products/"]:
            try:
                async with session.get(page_url, timeout=15, ssl=False) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        for a_tag in soup.find_all('a', href=True):
                            full_url = urljoin(STORE_URL, a_tag['href']).split('#')[0].split('?')[0]
                            if full_url.startswith(STORE_URL) and any(kw in full_url.lower() for kw in product_keywords):
                                if full_url.rstrip('/') not in [STORE_URL, f"{STORE_URL}/shop", f"{STORE_URL}/products"]:
                                    product_urls.add(full_url)
            except Exception:
                continue

    return list(product_urls)

async def parse_single_product_page(session, url: str) -> dict | None:
    """استخراج اطلاعات محصول و بررسی موجودی از متادیتا و متن صفحه"""
    try:
        async with session.get(url, timeout=15, ssl=False) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text(" ", strip=True)

        # بررسی ناموجود بودن کالا از طریق متاتگ‌ها و عبارات فارسی
        og_avail = soup.find('meta', property='og:availability') or soup.find('meta', property='product:availability')
        if og_avail and og_avail.get('content', '').lower() in ['out of stock', 'oos', 'outofstock']:
            return None

        out_of_stock_phrases = ['ناموجود', 'اتمام موجودی', 'موجود نیست', 'به زودی']
        # بررسی در محدوده دکمه‌های خرید یا وضعیت محصول
        status_area = " ".join([el.get_text(" ", strip=True) for el in soup.select('.stock, .availability, .single_add_to_cart_button, button')])
        if any(phrase in status_area for phrase in out_of_stock_phrases):
            return None

        # استخراج عنوان محصول
        title_tag = soup.find('meta', property='og:title')
        h1_tag = soup.find('h1')
        name = ""
        if h1_tag and len(h1_tag.get_text(strip=True)) > 3:
            name = h1_tag.get_text(strip=True)
        elif title_tag and title_tag.get('content'):
            name = title_tag['content'].split('|')[0].split('-')[0].strip()

        if not name:
            return None

        # استخراج تصویر محصول
        img_tag = soup.find('meta', property='og:image')
        img_url = img_tag['content'] if img_tag and img_tag.get('content') else None
        if img_url and not img_url.startswith('http'):
            img_url = urljoin(STORE_URL, img_url)

        # استخراج قیمت از متادیتا یا متن صفحه
        formatted_price = ""
        price_meta = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
        if price_meta and price_meta.get('content'):
            raw_val = re.sub(r'[^\d]', '', price_meta['content'])
            if raw_val and int(raw_val) > 1000:
                formatted_price = f"{int(raw_val):,} تومان"

        if not formatted_price:
            # جستجوی الگوی قیمت فارسی در صفحه (مثلاً 12,500,000 تومان)
            price_match = re.search(r'([\d,،٬]{4,15})\s*(?:تومان|ریال)', page_text)
            if price_match:
                formatted_price = f"{price_match.group(1)} تومان"

        # استخراج توضیح کوتاه
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
    except Exception as e:
        print(f"Error parsing product page {url}: {e}")
        return None

async def fetch_random_in_stock_products(count=3):
    """انتخاب ۳ محصول تصادفی و موجود از بین لینک‌های کشف‌شده سایت"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8'
    }
    recently_sent_ids = get_recently_sent_product_ids()
    selected_products = []

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            all_urls = await discover_product_urls_from_site(session)
            print(f"تعداد {len(all_urls)} لینک محصول در سایت {STORE_URL} شناسایی شد.")

            # فیلتر کردن محصولاتی که در ۲۴ ساعت اخیر ارسال نشده‌اند
            candidate_urls = [u for u in all_urls if u not in recently_sent_ids]
            if not candidate_urls:
                candidate_urls = all_urls

            random.shuffle(candidate_urls)

            # بررسی حداکثر ۱۵ لینک تصادفی تا رسیدن به ۳ محصول موجود و کامل
            for prod_url in candidate_urls[:15]:
                if len(selected_products) >= count:
                    break
                prod_data = await parse_single_product_page(session, prod_url)
                if prod_data:
                    selected_products.append(prod_data)
                await asyncio.sleep(1)

    except Exception as e:
        print(f"Error in store product discovery: {e}")

    return selected_products

async def publish_random_store_products():
    """انتشار ۳ محصول رندوم به همراه دکمه شیشه‌ای خرید اقساطی"""
    products = await fetch_random_in_stock_products(count=PRODUCTS_PER_HOUR)
    if not products:
        print("⚠️ محصولی از سایت استخراج نشد (احتمالاً ساختار لینک‌ها یا دسترسی سایت محدود است).")
        return

    print(f"Publishing {len(products)} random in-stock products to {TARGET_CHANNEL}...")

    for prod in products:
        caption_parts = [f"🔥 <b>{prod['name']}</b>"]
        
        if prod['short_desc']:
            caption_parts.append(f"\n📝 {prod['short_desc']}")
            
        if prod['price']:
            caption_parts.append(f"\n💰 قیمت: <b>{prod['price']}</b>")
            
        caption_parts.append("\n✅ موجود و آماده ارسال | امکان خرید اقساطی")
        caption_parts.append("\n🏷 #فروشگاه #خرید_اقساطی")
        final_caption = "\n".join(caption_parts) + CHANNEL_SIGNATURE

        keyboard = [
            [
                InlineKeyboardButton("💳 خرید اقساطی", url=prod['link'])
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            safe_filename = f"prod_{abs(hash(prod['id']))}.jpg"
            if prod['image_url']:
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

# ================= ۹. مدیریت کلیک روی دکمه‌های شیشه‌ای (لایک) =================
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("like_"):
        try:
            current_text = query.message.reply_markup.inline_keyboard[0][0].text
            count = int(current_text.split(" ")[1]) + 1
        except Exception:
            count = 1
            
        link_button = query.message.reply_markup.inline_keyboard[0][1]
        new_keyboard = [
            [
                InlineKeyboardButton(f"❤️ {count}", callback_data=data),
                link_button
            ]
        ]
        
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
        except Exception as e:
            print(f"Error updating like button UI: {e}")

# ================= ۱۰. حلقه اصلی اجرا و راه‌اندازی ایمن ربات =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err_msg = str(context.error)
    if "Conflict" in err_msg:
        print("⚠️ تداخل موقت هنگام راه‌اندازی کانتینر جدید (نسخه قبلی در حال بسته شدن است)...")
    else:
        print(f"Telegram network/update warning: {err_msg}")

async def background_news_loop(app_bot):
    init_db()
    print("RSS News & Store Bot worker is running...")
    tehran_tz = ZoneInfo("Asia/Tehran")

    await asyncio.sleep(15)

    while True:
        try:
            now_tehran = datetime.now(tehran_tz)
            current_hour = now_tehran.hour

            if 9 <= current_hour < 23:
                print(f"[{now_tehran.strftime('%H:%M')}] Fetching RSS feeds concurrently...")
                await fetch_rss_sources()
                print(f"Collected {len(pending_news_buffer)} new candidate items. Processing top {MAX_NEWS_PER_HOUR}...")
                await process_and_publish_batch()
                
                # دریافت و انتشار ۳ محصول رندوم موجود از سایت
                await publish_random_store_products()
            else:
                print(f"Outside active hours (Tehran time hour: {current_hour}). Bot is resting...")

        except Exception as e:
            print(f"Error in background loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(button_click_handler))
    application.add_error_handler(error_handler)

    async def post_init(app: Application):
        await app.bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
