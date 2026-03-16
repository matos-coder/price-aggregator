import os
import logging
import asyncio
import re
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import meilisearch

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
BOT_TOKEN = os.getenv("BOT_TOKEN")
MEILI_HOST = os.getenv("MEILI_HOST")
MEILI_KEY = os.getenv("MEILI_MASTER_KEY")

if not BOT_TOKEN:
    logger.error("CRITICAL: BOT_TOKEN is missing in .env")
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

# Initialize Bot with default HTML parse mode for clean formatting
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# -------------------------
# Query Understanding
# -------------------------

def parse_user_query(user_text: str):
    """
    Extract search query, max price, and location from user input.
    Example:
    'laptop under 70000 bole'
    """

    text = user_text.lower()

    max_price = None
    location = None

    # Detect price
    price_match = re.search(r"(under|below|less than)\s*(\d+)", text)
    if price_match:
        max_price = int(price_match.group(2))
        text = text.replace(price_match.group(0), "")

    # Detect simple location words (can expand later)
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

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Handles the /start command."""
    logger.info(f"User {message.from_user.id} started the bot.")
    welcome_text = (
        "👋 <b>Welcome to the Ethio Price Radar!</b>\n\n"
        "I monitor top Telegram shops in real-time to find you the best deals.\n\n"
        "🔍 <b>Just type what you are looking for.</b>\n"
        "<i>Example: 'iPhone 13' or 'Macbook M1'</i>"
    )
    await message.answer(welcome_text)


@dp.message(F.text)
async def handle_search_query(message: Message):
    """Captures user text, queries Meilisearch, and calculates Price Intelligence."""
    # query = message.text.strip()
    # logger.info(f"Search initiated | User: {message.from_user.id} | Query: '{query}'")
    raw_query = message.text.strip()
    query, max_price, location = parse_user_query(raw_query)
    logger.info(
        f"Search | User:{message.from_user.id} | Query:{query} | MaxPrice:{max_price} | Location:{location}"
    )
    
    try:
        # 1. Search Meilisearch (Grab up to 50 results for TRUE market math, no sorting here)
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
            await message.answer(f"🚫 No results found for <b>'{query}'</b>.")
            return

        # 2. Price Intelligence Math (True Market Average)
        prices = [hit["price"] for hit in hits if hit.get("price")]
        
        if not prices:
            await message.answer(f"No clear prices listed for <b>'{query}'</b>.")
            return

        min_price = min(prices)
        max_price = max(prices)
        avg_price = sum(prices) // len(prices)

        # 3. Sort hits in Python to get the cheapest options for display
        cheapest_hits = sorted([h for h in hits if h.get("price")], key=lambda x: x["price"])
        best_deal = cheapest_hits[0]

        # 4. Format the Output
        response = f"📊 <b>Price Intelligence for '{query}'</b>\n"
        response += f"📉 Lowest: {min_price:,} ETB\n"
        response += f"📈 Highest: {max_price:,} ETB\n"
        response += f"⚖️ Average: {avg_price:,} ETB\n\n"
        
        # Add the Best Deal highlight you commented out!
        response += "🔥 <b>BEST DEAL RIGHT NOW</b>\n"
        response += f"<b>{best_deal.get('product_name')}</b>\n"
        response += f"💰 {best_deal.get('price'):,} ETB | 📍 {best_deal.get('location')}\n"
        response += f"🔗 <a href='https://t.me/{best_deal.get('channel_username')}/{best_deal.get('message_id')}'>View Original Post</a>\n\n"

        response += "🛒 <b>Other Top Options:</b>\n\n"

        # Append next 4 cheapest products (skipping index 0 since it's the Best Deal)
        for idx, hit in enumerate(cheapest_hits[1:5], 1):
            product_name = hit.get('product_name', 'Unknown')
            price = hit.get('price', 0)
            location = hit.get('location', 'Unknown')
            post_link = f"https://t.me/{hit.get('channel_username')}/{hit.get('message_id')}"
            
            response += f"{idx}. <b>{product_name}</b>\n"
            response += f"💰 {price:,} ETB | 📍 {location}\n"
            response += f"🔗 <a href='{post_link}'>View Post</a>\n\n"

        await message.answer(response, disable_web_page_preview=True)
        logger.info(f"Successfully served results for '{query}'")

    except Exception as e:
        logger.error(f"Search failure for '{query}': {e}", exc_info=True)
        await message.answer("⚠️ Sorry, the search engine is currently down. Please try again in a few minutes.")

# -------------------------
# Main Execution
# -------------------------
async def main():
    logger.info("Starting Telegram User Bot...")
    # Drop any pending updates so the bot doesn't spam users with old messages upon restart
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())