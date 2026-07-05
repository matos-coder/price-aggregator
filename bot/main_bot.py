import os
import sys
import html
import logging
import asyncio
import secrets
import subprocess
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import meilisearch
from fastapi import FastAPI
import uvicorn

from nlp.query_parser import parse_user_query

# -------------------------
# Production Logging Setup
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("MainBot")

# -------------------------
# Load & Validate ENV
# -------------------------
load_dotenv()

API_ID = os.getenv("TELEGRAM_APP_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MEILI_HOST = os.getenv("MEILI_HOST")
MEILI_KEY = os.getenv("MEILI_MASTER_KEY")

if not all([API_ID, API_HASH, BOT_TOKEN]):
    logger.error("CRITICAL: Telegram API credentials missing in .env")
    exit(1)

# -------------------------
# Initialize Infrastructure
# -------------------------
def connect_meilisearch(max_retries: int = 10, delay_seconds: int = 3):
    """Meilisearch may still be booting inside the container — retry instead of dying."""
    client = meilisearch.Client(MEILI_HOST, MEILI_KEY)
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            client.health()
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Meilisearch not ready at {MEILI_HOST} ({attempt}/{max_retries}), retrying in {delay_seconds}s...")
            import time
            time.sleep(delay_seconds)
    else:
        logger.error(f"Failed to connect to Meilisearch: {last_error}")
        exit(1)

    try:
        client.get_index("products")
        logger.info("Found existing 'products' index.")
    except meilisearch.errors.MeilisearchApiError as e:
        if e.code == "index_not_found":
            logger.info("Index 'products' not found. Creating an empty one now...")
            client.create_index("products", {"primaryKey": "id"})
        else:
            raise
    idx = client.index("products")
    # Safety net: if the index was ever wiped/recreated, filters must still work.
    idx.update_filterable_attributes(['price', 'location'])
    logger.info("Successfully connected to Meilisearch.")
    return idx

index = connect_meilisearch()

# Intentionally an empty StringSession: the bot logs in fresh via BOT_TOKEN on
# every restart, which avoids "user vs bot" session conflicts (see README).
bot = TelegramClient(StringSession(""), int(API_ID), API_HASH)

# Initialize FastAPI for Hugging Face health checks
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Ethio Price Radar Bot is Running"}

# -------------------------
# Keep-Alive Endpoint
# -------------------------
@app.get("/ping")
async def ping():
    """External cron jobs will hit this to keep HF awake."""
    logger.info("💓 Health ping received. Space is awake.")
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# -------------------------
# On-Demand Seeder Endpoint
# -------------------------
_seeder_process: subprocess.Popen | None = None

@app.get("/seed")
async def trigger_seeder(token: str = ""):
    """
    Trigger the historical scraper remotely.
    Usage: https://your-hf-url.hf.space/seed?token=YOUR_BOT_TOKEN
    """
    global _seeder_process

    # 🔒 Constant-time comparison so the token can't be guessed via timing.
    if not token or not secrets.compare_digest(token, BOT_TOKEN):
        logger.warning("🚨 Unauthorized seed attempt blocked.")
        return {"error": "Unauthorized. Invalid token."}

    # Only one seeder at a time — repeated hits must not stack subprocesses.
    if _seeder_process is not None and _seeder_process.poll() is None:
        return {"status": "A seeding run is already in progress. Check HF logs."}

    logger.info("🚀 Manual seed triggered via API.")
    try:
        _seeder_process = subprocess.Popen([sys.executable, "-m", "db.seeder"])
        return {"status": "Historical seeding started in the background. Check HF logs."}
    except Exception as e:
        logger.error(f"Failed to start seeder: {e}")
        return {"error": str(e)}

# -------------------------
# Result Formatting
# -------------------------
def format_age(timestamp: int | None) -> str:
    """Human-readable freshness of a listing, e.g. 'today' or '12d ago'."""
    if not timestamp:
        return ""
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if age.days <= 0:
        return "today"
    if age.days == 1:
        return "yesterday"
    return f"{age.days}d ago"

def format_listing(hit: dict) -> str:
    name = html.escape(str(hit.get('product_name') or 'Unknown'))
    price = hit.get('price') or 0
    loc = html.escape(str(hit.get('location') or 'Unknown'))
    link = f"https://t.me/{hit.get('channel_username')}/{hit.get('message_id')}"
    age = format_age(hit.get('timestamp'))
    age_part = f" | 🕒 {age}" if age else ""
    return (
        f"<b>{name}</b>\n"
        f"💰 {price:,} ETB | 📍 {loc}{age_part}\n"
        f"🔗 <a href='{link}'>View Original Post</a>\n"
    )

# -------------------------
# Bot Handlers
# -------------------------
@bot.on(events.NewMessage(pattern=r'^/start$'))
async def cmd_start(event):
    """Handles the /start command."""
    logger.info(f"User {event.sender_id} started the bot.")
    welcome_text = (
        "👋 <b>Welcome to the Ethio Price Radar!</b>\n\n"
        "I monitor top Telegram shops in real-time to find you the best deals.\n\n"
        "🔍 <b>Just type what you are looking for.</b>\n"
        "<i>Examples:</i>\n"
        "• <i>iPhone 13</i>\n"
        "• <i>macbook m2 16gb under 120k</i>\n"
        "• <i>samsung a25 under 30000 in bole</i>\n\n"
        "Send /help anytime for tips."
    )
    await event.respond(welcome_text, parse_mode='html')

@bot.on(events.NewMessage(pattern=r'^/help$'))
async def cmd_help(event):
    help_text = (
        "🧭 <b>How to search</b>\n\n"
        "Type the product with any specs you care about — brand, model, RAM, storage.\n\n"
        "You can also add:\n"
        "• A budget: <i>'under 50000'</i> or <i>'under 50k'</i>\n"
        "• A location: <i>'in bole'</i>, <i>'piassa'</i>, ...\n\n"
        "I'll reply with the market's lowest/highest/average price, the best deal, "
        "and links to the original seller posts."
    )
    await event.respond(help_text, parse_mode='html')

@bot.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def handle_search_query(event):
    """Captures user text, queries Meilisearch, and calculates Price Intelligence."""
    raw_query = event.text.strip()
    if not raw_query:
        return

    async with bot.action(event.chat_id, 'typing'):
        query, max_price, location = await parse_user_query(raw_query)

        logger.info(f"Search | User:{event.sender_id} | Query:{query!r} | MaxPrice:{max_price} | Location:{location}")

        if not query and not max_price:
            await event.respond(
                "🤔 I couldn't find a product in that message.\n"
                "Try something like <i>'macbook m2 under 120k'</i>.",
                parse_mode='html'
            )
            return

        try:
            filters = []
            if max_price:
                filters.append(f"price <= {max_price}")
            if location:
                filters.append(f"location = '{location}'")
            filter_str = " AND ".join(filters) if filters else None

            async def run_search(matching_strategy, limit):
                params = {
                    "limit": limit,
                    "matchingStrategy": matching_strategy,
                    "showRankingScore": True,
                }
                if filter_str:
                    params["filter"] = filter_str
                if not query:
                    # Budget-only search ("anything under 5000"): cheapest first.
                    params["sort"] = ["price:asc"]
                # meilisearch client is synchronous — keep it off the event loop
                result = await asyncio.to_thread(index.search, query, params)
                return result.get("hits", [])

            # Tier 1: strict match — every word in the query must be present
            # (e.g. "samsung a25" only matches listings mentioning BOTH terms).
            hits = await run_search("all", 30)

            # Tier 2: top up with close/related matches (e.g. "samsung a24") if the
            # strict match is thin, but drop anything too weakly related so a bare
            # "samsung" match doesn't creep back in. RELEVANCE_THRESHOLD is tunable.
            if len(hits) < 5:
                RELEVANCE_THRESHOLD = 0.35
                seen_ids = {hit["id"] for hit in hits}
                for hit in await run_search("last", 50):
                    if hit["id"] not in seen_ids and hit.get("_rankingScore", 0) >= RELEVANCE_THRESHOLD:
                        hits.append(hit)
                        seen_ids.add(hit["id"])

            display_query = html.escape(query or raw_query)

            if not hits:
                suggestion = ""
                if max_price or location:
                    suggestion = "\n💡 Try removing the budget/location filter, or check the spelling."
                await event.respond(
                    f"🚫 No results found for <b>'{display_query}'</b>.{suggestion}",
                    parse_mode='html'
                )
                return

            priced_hits = [h for h in hits if h.get("price")]
            if not priced_hits:
                await event.respond(f"No clear prices listed for <b>'{display_query}'</b>.", parse_mode='html')
                return

            prices = [h["price"] for h in priced_hits]
            min_price = min(prices)
            maximum_price = max(prices)
            avg_price = sum(prices) // len(prices)

            cheapest_hits = sorted(priced_hits, key=lambda x: x["price"])
            best_deal = cheapest_hits[0]

            response = f"📊 <b>Price Intelligence for '{display_query}'</b>\n"
            response += f"({len(priced_hits)} listings found)\n"
            response += f"📉 Lowest: {min_price:,} ETB\n"
            response += f"📈 Highest: {maximum_price:,} ETB\n"
            response += f"⚖️ Average: {avg_price:,} ETB\n\n"

            response += "🔥 <b>BEST DEAL RIGHT NOW</b>\n"
            response += format_listing(best_deal) + "\n"

            if len(cheapest_hits) > 1:
                response += "🛒 <b>Other Top Options:</b>\n\n"
                for idx, hit in enumerate(cheapest_hits[1:5], 1):
                    response += f"{idx}. " + format_listing(hit) + "\n"

            # link_preview=False replaces disable_web_page_preview=True
            await event.respond(response, parse_mode='html', link_preview=False)
            logger.info(f"Successfully served {len(priced_hits)} results for '{query}'")

        except Exception as e:
            logger.error(f"Search failure for '{query}': {e}", exc_info=True)
            await event.respond("⚠️ Sorry, the search engine is currently down. Please try again in a few minutes.")

# -------------------------
# Main Execution
# -------------------------
async def start_telegram_logic():
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Telegram Bot is online and listening!")
    await bot.run_until_disconnected()

async def run_all():
    config = uvicorn.Config(app, host="0.0.0.0", port=7860, loop="asyncio")
    server = uvicorn.Server(config)

    # Run Web Server and Telegram Bot concurrently
    await asyncio.gather(
        server.serve(),
        start_telegram_logic()
    )

if __name__ == "__main__":
    asyncio.run(run_all())
