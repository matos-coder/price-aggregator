import os
import logging
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from db.database import ProductDatabase
from nlp.extractor import extract_entities


# 1. Production-Grade Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TelegramListener")

# 2. Load and Validate Environment Variables
load_dotenv()

API_ID = os.getenv('TELEGRAM_APP_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
CHANNELS_ENV = os.getenv('TARGET_CHANNELS')
STRING_SESSION = os.getenv('TELEGRAM_STRING_SESSION')

if not all([API_ID, API_HASH, CHANNELS_ENV, STRING_SESSION]):
    logger.error("CRITICAL: Missing TELEGRAM_APP_ID, TELEGRAM_API_HASH, TARGET_CHANNELS or TELEGRAM_STRING_SESSION in .env")
    exit(1)

# Convert the comma-separated string from .env into a Python list
TARGET_CHANNELS = [channel.strip() for channel in CHANNELS_ENV.split(',')]

# 3. Initialize the Telegram Client
client = TelegramClient(StringSession(STRING_SESSION), int(API_ID), API_HASH)

db = ProductDatabase()

# 4. The Event-Driven Listener
@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def handle_new_message(event):
    """
    This function triggers instantly the millisecond a new post hits a target channel.
    """
    try:
        # We only care about text. Ignore standalone images with no captions.
        raw_text = event.message.message
        if not raw_text:
            return

        channel_entity = await event.get_chat()
        channel_username = getattr(channel_entity, 'username', 'unknown_channel')
        message_id = event.message.id

        logger.info(f"New post detected in @{channel_username} (ID: {message_id})")

        # Create the payload blueprint
        raw_payload = {
            "channel_username": channel_username,
            "message_id": message_id,
            "raw_text": raw_text,
            "timestamp": int(event.message.date.timestamp())
        }

        # TODO in Phase 3: Send 'raw_payload' to nlp/extractor.py 
        extracted_json = await extract_entities(raw_payload)
        if extracted_json:
            db.add_product(extracted_json)
        
        # For now, just log the text snippet to verify it works
        logger.info(f"Snippet: {raw_text[:50]}...")

    except Exception as e:
        logger.error(f"Error processing message: {e}")

async def main():
    logger.info(f"Starting listener. Monitoring channels: {TARGET_CHANNELS}")
    await client.start()
    logger.info("Client connected. Listening for new inventory...")
    # This keeps the script running 24/7
    await client.run_until_disconnected()

if __name__ == '__main__':
    # Run the async event loop
    asyncio.run(main())