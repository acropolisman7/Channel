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
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

# ================= ۱. تنظیمات اصلی و کلیدها =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

TARGET_CHANNEL = '@jazebestore'                    # آیدی کانال مقصد شما
CHANNEL_SIGNATURE = "\n\n🎮 @jazebestore"          # امضای انتهای پست
CHECK_INTERVAL_SECONDS = 3600                      # بررسی سایت‌ها هر ۱ ساعت
STORE_URL = "https://jazebestore.com"              # آدرس فروشگاه شما
PRODUCTS_PER_HOUR = 3                              # تعداد محصولات رندوم در هر ساعت

# لیست فیدهای RSS معتبر گیمینگ و تکنولوژی
SOURCE_RSS_URLS = [
    'https://feeds.feedburner.com/ign/games-all',
    'https://www.videogameschronicle.com/feed/',
    'https://www.theverge.com/rss/index.xml',
    'https://feeds.macrumors.com/MacRumors-All',
    'https://9to5mac.com/feed/',
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
    c.execute('''CREATE TABLE IF NOT EXISTS post_likes 
                 (post_id TEXT PRIMARY KEY, 
                  like_count INTEGER DEFAULT 0)''')
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        async with aiohttp.ClientSession(headers=headers) as session:
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
                    'link': link,
                    'text': cleaned_body,
                    'image_url': img_url
                })
        except Exception as e:
            print(f"Error checking RSS {url}: {e}")

# ================= ۶. پردازش هوشمند و انتشار اخبار در کانال =================
async def process_and_publish_batch():
    global pending_news_buffer
    if not pending_news_buffer:
        return

    current_batch = pending_news_buffer.copy()
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
    2. Translate/edit into fluent journalistic Persian (final_persian_text). Wrap ONLY the news title at the very beginning inside HTML bold tags like <b>Title here</b>, followed by double line breaks and the summary. Length under 850 chars.
    3. CRITICAL: Do NOT translate proper nouns, game titles, hardware models, or company names (keep PlayStation, iPhone, God of War, Steam, Sony, NVIDIA, etc. in original English form).
    4. Provide a 1-sentence English topic_fingerprint.
    """

    result_data = None
    max_retries = 3
    delay = 10

    for attempt in range(1, max_retries + 1):
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchProcessResult,
                    temperature=0.3
                )
            )
            result_data = json.loads(response.text)
            break
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "ResourceExhausted" in error_str or "ServiceUnavailable" in error_str or "503" in error_str:
                print(f"خطای شلوغی سرور یا لیمیت (تلاش {attempt} از {max_retries}): {e}")
            else:
                print(f"خطای پردازش جمنای (تلاش {attempt}): {e}")

            if attempt == max_retries:
                print("تلاش‌ها به اتمام رسید. پردازش این دسته به سیکل بعدی موکول شد.")
                return
            await asyncio.sleep(delay)
            delay *= 2

    if not result_data:
        return

    try:
        selected_items = result_data.get("selected_news", [])
        batch_map = {item['id']: item for item in current_batch}

        for sel in selected_items:
            orig_item = batch_map.get(sel['selected_id'])
            if not orig_item:
                continue

            final_caption = sel['final_persian_text'].strip() + CHANNEL_SIGNATURE
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
        print(f"Error publishing to channel: {e}")

# ================= ۶.۵ بخش جدید: دریافت و انتشار محصولات موجود سایت =================
async def fetch_random_in_stock_products(count=3):
    """دریافت محصولات فعال و دارای موجودی از jazebestore.com"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    in_stock_products = []

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # روش اول: استفاده از API عمومی فروشگاه ووکامرس (دقیق‌ترین روش برای تشخیص موجودی)
            api_url = f"{STORE_URL}/wp-json/wc/store/v1/products?per_page=100"
            async with session.get(api_url, timeout=20) as resp:
                if resp.status == 200:
                    products_data = await resp.json()
                    for p in products_data:
                        # بررسی فعال بودن و موجودی کالا
                        if p.get('is_in_stock') is True and p.get('is_purchasable', True):
                            name = clean_raw_text(p.get('name', ''))
                            permalink = p.get('permalink', STORE_URL)
                            
                            # استخراج قیمت
                            prices = p.get('prices', {})
                            raw_price = prices.get('price', '')
                            currency_minor_unit = prices.get('currency_minor_unit', 0)
                            formatted_price = ""
                            if raw_price and raw_price.isdigit():
                                val = int(raw_price) // (10 ** currency_minor_unit)
                                if val > 0:
                                    formatted_price = f"{val:,} تومان"

                            # استخراج تصویر شاخص محصول
                            images = p.get('images', [])
                            img_url = images[0].get('src') if images else None

                            # استخراج توضیح کوتاه
                            short_desc = clean_raw_text(p.get('short_description', ''))
                            if len(short_desc) > 250:
                                short_desc = short_desc[:247] + "..."

                            in_stock_products.append({
                                'id': p.get('id', random.randint(1000, 9999)),
                                'name': name,
                                'price': formatted_price,
                                'link': permalink,
                                'image_url': img_url,
                                'short_desc': short_desc
                            })

            # روش دوم (جایگزین): اگر API در دسترس نبود، اسکرپ صفحه فروشگاه
            if not in_stock_products:
                shop_url = f"{STORE_URL}/shop/"
                async with session.get(shop_url, timeout=20) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        for item in soup.select('li.product.instock'):
                            title_el = item.select_one('.woocommerce-loop-product__title, h2, h3')
                            link_el = item.select_one('a[href]')
                            img_el = item.select_one('img')
                            price_el = item.select_one('.price')

                            if title_el and link_el:
                                in_stock_products.append({
                                    'id': random.randint(1000, 9999),
                                    'name': title_el.get_text(strip=True),
                                    'price': clean_raw_text(price_el.get_text()) if price_el else "",
                                    'link': link_el['href'],
                                    'image_url': img_el.get('data-src') or img_el.get('src') if img_el else None,
                                    'short_desc': ""
                                })

    except Exception as e:
        print(f"Error fetching products from {STORE_URL}: {e}")

    if not in_stock_products:
        return []

    return random.sample(in_stock_products, min(count, len(in_stock_products)))

async def publish_random_store_products():
    """انتشار ۳ محصول رندوم به همراه دکمه شیشه‌ای خرید اقساطی"""
    products = await fetch_random_in_stock_products(count=PRODUCTS_PER_HOUR)
    if not products:
        print("هیچ محصول موجودی از سایت دریافت نشد.")
        return

    print(f"Publishing {len(products)} random in-stock products to {TARGET_CHANNEL}...")

    for prod in products:
        caption_parts = [f"🔥 <b>{prod['name']}</b>"]
        
        if prod['short_desc']:
            caption_parts.append(f"\n📝 {prod['short_desc']}")
            
        if prod['price']:
            caption_parts.append(f"\n💰 قیمت: <b>{prod['price']}</b>")
            
        caption_parts.append("\n✅ موجود و آماده ارسال | امکان خرید اقساطی")
        final_caption = "\n".join(caption_parts) + CHANNEL_SIGNATURE

        # دکمه شیشه‌ای خرید اقساطی متصل به صفحه محصول
        keyboard = [
            [
                InlineKeyboardButton("💳 خرید اقساطی", url=prod['link'])
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if prod['image_url']:
                img_path = await download_image_from_url(prod['image_url'], f"prod_{prod['id']}.jpg")
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
        except Exception as e:
            print(f"Error sending product '{prod['name']}': {e}")

        await asyncio.sleep(5)

# ================= ۷. مدیریت کلیک روی دکمه‌های شیشه‌ای (لایک) =================
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

# ================= ۸. حلقه اصلی اجرا و راه‌اندازی ربات =================
async def background_news_loop(app_bot):
    init_db()
    print("RSS News & Store Bot worker is running...")
    tehran_tz = ZoneInfo("Asia/Tehran")

    await asyncio.sleep(5)

    while True:
        try:
            now_tehran = datetime.now(tehran_tz)
            current_hour = now_tehran.hour

            if 9 <= current_hour < 23:
                # ۱. دریافت و انتشار اخبار
                await fetch_rss_sources()
                await process_and_publish_batch()
                
                # ۲. دریافت و انتشار ۳ محصول رندوم موجود از سایت
                await publish_random_store_products()
            else:
                print(f"Outside active hours (Tehran time hour: {current_hour}). Bot is resting...")

        except Exception as e:
            print(f"Error in background loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(button_click_handler))

    async def post_init(app: Application):
        asyncio.create_task(background_news_loop(app.bot))

    application.post_init = post_init

    print("Telegram Bot application started...")
    application.run_polling()

if __name__ == '__main__':
    main()
