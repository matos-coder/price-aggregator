import os
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from nlp.extractor import extract_entities
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

# Local import
from db.database import ProductDatabase


# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("HistoricalScraper")


# -------------------------
# Load ENV
# -------------------------
load_dotenv()

API_ID = os.getenv("TELEGRAM_APP_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
STRING_SESSION = os.getenv("TELEGRAM_STRING_SESSION")
CHANNELS_ENV = os.getenv("TARGET_CHANNELS")

if not all([API_ID, API_HASH, STRING_SESSION, CHANNELS_ENV]):
    logger.error("Missing required environment variables")
    exit(1)

TARGET_CHANNELS = [c.strip() for c in CHANNELS_ENV.split(",")]

# -------------------------
# Telegram Client
# -------------------------
client = TelegramClient(StringSession(STRING_SESSION), int(API_ID), API_HASH)

# -------------------------
# Database
# -------------------------
db = ProductDatabase()


# -------------------------
# Utility Filters
# -------------------------

def contains_price(text: str) -> bool:
    """
    Check if a message contains a price.
    Supports formats like:
    80000
    80,000
    80k
    80000 birr
    """
    price_patterns = [
        r"\b\d{4,7}\b",
        r"\b\d{2,3}k\b",
        r"\b\d{4,7}\s?(birr|br)\b",
        r"\b\d{1,3}(,\d{3})*\b"
    ]

    for pattern in price_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def is_valid_product_message(text: str) -> bool:
    """
    Final filter logic
    """

    if not contains_price(text):
        return False

    return True


# -------------------------
# Payload builder
# -------------------------

def build_payload(channel_username, message):
    return {
        "id": f"{channel_username}_{message.id}",
        "channel_username": channel_username,
        "message_id": message.id,
        "original_text": message.message,
        "timestamp": int(message.date.timestamp())
    }


# -------------------------
# Scraper
# -------------------------

async def scrape_channel(channel):
    """
    Scrape historical messages from one channel.
    """

    logger.info(f"Scraping @{channel}")

    try:
        entity = await client.get_entity(channel)

        # ------------------------------------------
        # TEST MODE
        # ------------------------------------------
        # Only scrape last 5 messages
        # messages = client.iter_messages(entity, limit=5)

        # ------------------------------------------
        # PRODUCTION MODE (UNCOMMENT LATER)
        # ------------------------------------------
        # Scrape last 1 month
        #
        # one_month_ago = datetime.utcnow() - timedelta(days=30)
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        messages = client.iter_messages(entity)
        

        async for message in messages:

            if not message.message:
                continue

            text = message.message.strip()

            # If production mode enabled
            if message.date < one_month_ago:
                break

            if not is_valid_product_message(text):
                continue

            channel_username = getattr(entity, "username", "unknown")

            payload = build_payload(channel_username, message)

            logger.info(
                f"Valid product found | {channel_username} | msg:{message.id}"
            )

            # Send to LLM extractor
            extracted_payload = await extract_entities(payload)
            
            # Only add to Meilisearch if the LLM successfully found a product and price
            if extracted_payload:
                db.add_product(extracted_payload)
                logger.info(f"Successfully indexed: {extracted_payload['id']}")

    except FloodWaitError as e:
        logger.warning(f"Rate limit hit. Sleeping {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        logger.error(f"Error scraping {channel}: {e}")


# -------------------------
# Main
# -------------------------

async def main():

    logger.info("Starting historical scraper")

    await client.start()

    logger.info("Telegram client connected")

    for channel in TARGET_CHANNELS:
        await scrape_channel(channel)

        # Avoid aggressive scraping
        await asyncio.sleep(2)

    logger.info("Historical scraping completed")


if __name__ == "__main__":
    asyncio.run(main())