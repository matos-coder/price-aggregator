import os
import asyncio
import logging
import re
from datetime import datetime, timedelta

from dotenv import load_dotenv
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
# Filtering rules
# -------------------------

# Words that usually mean advertisements or unrelated posts
AD_KEYWORDS = [
    "join",
    "subscribe",
    "follow",
    "promotion",
    "advert",
    "delivery service",
    "training",
    "course",
    "vacancy",
    "job",
    "apply",
    "discount code",
]

# Electronics keywords
PRODUCT_KEYWORDS = [
    "iphone",
    "samsung",
    "macbook",
    "laptop",
    "ipad",
    "tablet",
    "phone",
    "monitor",
    "pc",
    "computer",
    "camera",
    "printer",
    "router",
    "ssd",
    "hard drive",
    "keyboard",
    "mouse",
]


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
        r"\b\d{4,7}\s?(birr|br)\b"
    ]

    for pattern in price_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def looks_like_ad(text: str) -> bool:
    """
    Detect common advertisement posts.
    """
    text_lower = text.lower()

    for word in AD_KEYWORDS:
        if word in text_lower:
            return True

    return False


def looks_like_product(text: str) -> bool:
    """
    Detect if text contains electronics keywords.
    """
    text_lower = text.lower()

    for word in PRODUCT_KEYWORDS:
        if word in text_lower:
            return True

    return False


def is_valid_product_message(text: str) -> bool:
    """
    Final filter logic
    """
    if looks_like_ad(text):
        return False

    if not contains_price(text):
        return False

    if not looks_like_product(text):
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
        messages = client.iter_messages(entity, limit=5)

        # ------------------------------------------
        # PRODUCTION MODE (UNCOMMENT LATER)
        # ------------------------------------------
        # Scrape last 1 month
        #
        # one_month_ago = datetime.utcnow() - timedelta(days=30)
        # messages = client.iter_messages(entity)
        #

        async for message in messages:

            if not message.message:
                continue

            text = message.message.strip()

            # If production mode enabled
            # if message.date < one_month_ago:
            #     break

            if not is_valid_product_message(text):
                continue

            channel_username = getattr(entity, "username", "unknown")

            payload = build_payload(channel_username, message)

            logger.info(
                f"Valid product found | {channel_username} | msg:{message.id}"
            )

            # --------------------------------
            # Later send to LLM extractor
            # --------------------------------
            # extracted = await extract_entities(payload)
            # if extracted:
            #     db.add_product(extracted)

            # For now just store raw
            db.add_product(payload)

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