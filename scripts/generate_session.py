"""Generate a fresh TELEGRAM_STRING_SESSION for the listener/historical scraper.

Run this interactively on your own machine (it will ask for your phone number
and the login code Telegram sends you):

    python -m scripts.generate_session

Then paste the printed string into the TELEGRAM_STRING_SESSION secret on
Hugging Face and restart the Space.

IMPORTANT: a string session may only be used from ONE place at a time.
Using the same session locally while the Space is running gets the key
permanently revoked by Telegram (AuthKeyDuplicatedError).
"""
import os

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

api_id = int(os.getenv("TELEGRAM_APP_ID") or input("TELEGRAM_APP_ID: "))
api_hash = os.getenv("TELEGRAM_API_HASH") or input("TELEGRAM_API_HASH: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nYour new TELEGRAM_STRING_SESSION (copy the whole line):\n")
    print(client.session.save())
