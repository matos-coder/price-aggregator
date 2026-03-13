import os
import logging
import asyncio
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
    query = message.text.strip()
    logger.info(f"Search initiated | User: {message.from_user.id} | Query: '{query}'")

    try:
        # 1. Search Meilisearch (Grab up to 15 results for a better average)
        search_results = index.search(query, {"limit": 15,"sort": ["price:asc"]})
        hits = search_results.get("hits", [])

        if not hits:
            logger.info(f"No results found for '{query}'.")
            await message.answer(f"🚫 No results found for <b>'{query}'</b>. Try using a broader keyword!")
            return

        # 2. Price Intelligence Math
        # Extract valid prices from the search hits
        prices = [hit["price"] for hit in hits if hit.get("price")]
        
        if not prices:
            await message.answer(f"Found mentions of <b>'{query}'</b>, but no clear prices were listed in those posts.")
            return

        min_price = min(prices)
        max_price = max(prices)
        avg_price = sum(prices) // len(prices)

        # 3. Format the Output
        response = f"📊 <b>Price Intelligence for '{query}'</b>\n"
        response += f"📉 Lowest: {min_price:,} Birr\n"
        response += f"📈 Highest: {max_price:,} Birr\n"
        response += f"⚖️ Average: {avg_price:,} Birr\n\n"
        response += "🛒 <b>Top Available Options:</b>\n\n"

        # 4. Append Top 5 Individual Products
        for idx, hit in enumerate(hits[:5], 1):
            product_name = hit.get('product_name', 'Unknown')
            price = hit.get('price', 0)
            location = hit.get('location', 'Unknown')
            channel = hit.get('channel_username', 'Unknown')
            msg_id = hit.get('message_id', '')
            
            # Create a deep link directly to the Telegram post
            post_link = f"https://t.me/{channel}/{msg_id}"
            
            response += f"{idx}. <b>{product_name}</b>\n"
            response += f"💰 {price:,} Birr | 📍 {location}\n"
            response += f"🔗 <a href='{post_link}'>View Original Post</a>\n\n"

        # Send the final compiled message (disable web preview so the chat doesn't get cluttered with link previews)
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