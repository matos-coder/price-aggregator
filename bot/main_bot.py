import os
import logging
import asyncio
import re
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import meilisearch
from fastapi import FastAPI
import uvicorn

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

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MEILI_HOST = os.getenv("MEILI_HOST")
MEILI_KEY = os.getenv("MEILI_MASTER_KEY")
# Provide an empty string if you don't have a generated session string yet.
# Telethon will create a stateless in-memory session using the bot token.
BOT_STRING = os.getenv("BOT_SESSION_STRING") 

if not all([API_ID, API_HASH, BOT_TOKEN]):
    logger.error("CRITICAL: Telegram API credentials missing in .env")
    exit(1)

# -------------------------
# Initialize Infrastructure
# -------------------------
try:
    meili_client = meilisearch.Client(MEILI_HOST, MEILI_KEY)
    index = meili_client.index("products")
    logger.info("Successfully connected to Meilisearch.")
except Exception as e:
    logger.error(f"Failed to connect to Meilisearch: {e}")
    exit(1)

# Initialize Bot Client
bot = TelegramClient(StringSession(BOT_STRING), int(API_ID), API_HASH)

# Initialize FastAPI for Hugging Face health checks
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Ethio Price Radar Bot is Running"}

# -------------------------
# Query Understanding
# -------------------------
def parse_user_query(user_text: str):
    text = user_text.lower()
    max_price = None
    location = None

    price_match = re.search(r"(under|below|less than)\s*(\d+)", text)
    if price_match:
        max_price = int(price_match.group(2))
        text = text.replace(price_match.group(0), "")

    possible_locations = ["bole", "megenagna", "piassa", "4kilo", "sarbet"]
    for loc in possible_locations:
        if loc in text:
            location = loc
            text = text.replace(loc, "")

    query = text.strip()
    return query, max_price, location

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
        "<i>Example: 'iPhone 13' or 'Macbook M1'</i>"
    )
    await event.respond(welcome_text, parse_mode='html')

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def handle_search_query(event):
    """Captures user text, queries Meilisearch, and calculates Price Intelligence."""
    raw_query = event.text.strip()
    query, max_price, location = parse_user_query(raw_query)
    
    logger.info(f"Search | User:{event.sender_id} | Query:{query} | MaxPrice:{max_price} | Location:{location}")
    
    try:
        search_params = {"limit": 50}
        filters = []

        if max_price:
            filters.append(f"price <= {max_price}")
        if location:
            filters.append(f"location = '{location}'")

        if filters:
            search_params["filter"] = " AND ".join(filters)
            
        search_results = index.search(query, search_params)
        hits = search_results.get("hits", [])

        if not hits:
            await event.respond(f"🚫 No results found for <b>'{query}'</b>.", parse_mode='html')
            return

        prices = [hit["price"] for hit in hits if hit.get("price")]
        
        if not prices:
            await event.respond(f"No clear prices listed for <b>'{query}'</b>.", parse_mode='html')
            return

        min_price = min(prices)
        maximum_price = max(prices)
        avg_price = sum(prices) // len(prices)

        cheapest_hits = sorted([h for h in hits if h.get("price")], key=lambda x: x["price"])
        best_deal = cheapest_hits[0]

        response = f"📊 <b>Price Intelligence for '{query}'</b>\n"
        response += f"📉 Lowest: {min_price:,} ETB\n"
        response += f"📈 Highest: {maximum_price:,} ETB\n"
        response += f"⚖️ Average: {avg_price:,} ETB\n\n"
        
        response += "🔥 <b>BEST DEAL RIGHT NOW</b>\n"
        response += f"<b>{best_deal.get('product_name')}</b>\n"
        response += f"💰 {best_deal.get('price'):,} ETB | 📍 {best_deal.get('location')}\n"
        response += f"🔗 <a href='https://t.me/{best_deal.get('channel_username')}/{best_deal.get('message_id')}'>View Original Post</a>\n\n"

        response += "🛒 <b>Other Top Options:</b>\n\n"

        for idx, hit in enumerate(cheapest_hits[1:5], 1):
            product_name = hit.get('product_name', 'Unknown')
            price = hit.get('price', 0)
            loc = hit.get('location', 'Unknown')
            post_link = f"https://t.me/{hit.get('channel_username')}/{hit.get('message_id')}"
            
            response += f"{idx}. <b>{product_name}</b>\n"
            response += f"💰 {price:,} ETB | 📍 {loc}\n"
            response += f"🔗 <a href='{post_link}'>View Post</a>\n\n"

        # link_preview=False replaces disable_web_page_preview=True
        await event.respond(response, parse_mode='html', link_preview=False)
        logger.info(f"Successfully served results for '{query}'")

    except Exception as e:
        logger.error(f"Search failure for '{query}': {e}", exc_info=True)
        await event.respond("⚠️ Sorry, the search engine is currently down. Please try again in a few minutes.")

# -------------------------
# Main Execution
# -------------------------
async def start_telegram_logic():
    # bot_token acts as the fallback if BOT_SESSION_STRING is empty
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