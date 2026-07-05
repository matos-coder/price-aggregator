import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from nlp.extractor import extract_entities
from db.database import ProductDatabase
from scraper.filters import is_valid_product_message


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
BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "30"))

if not all([API_ID, API_HASH, STRING_SESSION, CHANNELS_ENV]):
    logger.error("Missing required environment variables")
    exit(1)

TARGET_CHANNELS = [c.strip() for c in CHANNELS_ENV.split(",") if c.strip()]

# -------------------------
# Telegram Client
# -------------------------
client = TelegramClient(StringSession(STRING_SESSION), int(API_ID), API_HASH)

# -------------------------
# Database
# -------------------------
db = ProductDatabase()


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
    logger.info(f"Scraping @{channel}")
    stats = {"seen": 0, "indexed": 0, "skipped_existing": 0}
    try:
        entity = await client.get_entity(channel)
        cutoff = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)
        channel_username = getattr(entity, "username", None) or "unknown"

        async for message in client.iter_messages(entity):
            if message.date < cutoff:
                logger.info(f"Reached {BACKFILL_DAYS}-day limit for {channel}. Stopping.")
                break

            if not message.message:
                continue

            stats["seen"] += 1
            text = message.message.strip()

            if not is_valid_product_message(text):
                continue

            payload = build_payload(channel_username, message)

            # 💸 Dedupe BEFORE the LLM call: re-running the seeder must not
            # re-spend Groq quota on messages that are already indexed.
            if db.document_exists(payload["id"]):
                stats["skipped_existing"] += 1
                continue

            # 🛡️ EXCEPTION FILTER FOR THE LLM — a single bad message must not
            # abort the whole backfill.
            try:
                extracted_payload = await extract_entities(payload)
                if extracted_payload:
                    db.add_product(extracted_payload)
                    stats["indexed"] += 1
                    logger.info(f"✅ Indexed: {extracted_payload['id']}")
            except Exception as llm_error:
                logger.error(f"❌ Failed to extract/index msg {message.id}: {llm_error}")

            # 🛡️ ANTI-BAN pacing: only throttle messages we actually processed —
            # iterating over the already-fetched batch costs no Telegram calls.
            await asyncio.sleep(1.5)

    except FloodWaitError as e:
        logger.warning(f"⚠️ RATE LIMIT! Telegram demands we sleep for {e.seconds}s.")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logger.error(f"❌ Critical error scraping {channel}: {e}")

    logger.info(
        f"Done with @{channel}: {stats['indexed']} indexed, "
        f"{stats['skipped_existing']} already indexed, {stats['seen']} text messages seen."
    )


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
