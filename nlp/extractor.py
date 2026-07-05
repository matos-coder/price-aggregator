import os
import json
import asyncio
import logging
from dotenv import load_dotenv
from groq import AsyncGroq, RateLimitError, APIError

# Setup Logging
logger = logging.getLogger("Extractor")

load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    # Fail fast with a clear message — supervisord/docker will surface this.
    raise RuntimeError("CRITICAL: GROQ_API_KEY missing in .env")

# Async client so LLM calls never block the Telethon/FastAPI event loop.
client = AsyncGroq(api_key=API_KEY)

MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Sanity bounds for an ETB price. Anything outside is almost certainly a
# phone number (09xxxxxxxx), an IMEI, or extraction noise.
MIN_PRICE = 100
MAX_PRICE = 50_000_000

MAX_RETRIES = 3

PROMPT_TEMPLATE = """You are an e-commerce data extraction API.
Analyze the following Amharic/English Telegram message from an Ethiopian shop channel.
Extract the main product name, the price in Ethiopian Birr (ETB), and the location.

Rules:
- product_name: concise but specific — keep brand, model and key specs
  (e.g. "MacBook Pro M2 16GB 512GB", not just "laptop"). Use English.
- price: the selling price as an integer (no commas, no currency letters).
  - Interpret "80k" as 80000. "ዋጋ" means price.
  - NEVER use phone numbers (start with 09 or +251), IMEI numbers, or delivery fees as the price.
  - If a price range is given, use the lower value.
  - If there is no clear selling price, return null.
- location: the neighborhood/city where the item is sold (e.g. "Bole", "Piassa").
  Use English spelling. If not stated, return "Unknown".
- If there are multiple products, pick the main one.

Output strictly in this JSON format:
{{"product_name": "string", "price": "integer or null", "location": "string"}}

Message:
{text}"""


async def extract_entities(raw_payload: dict) -> dict | None:
    """
    Takes the raw Telegram payload, uses an LLM to extract Product, Price, and Location,
    and returns a clean dictionary ready for Meilisearch (or None to drop the message).
    """
    text_to_analyze = raw_payload.get("original_text", "")
    if not text_to_analyze.strip():
        return None

    extracted_data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a product extraction API that only outputs JSON."},
                    {"role": "user", "content": PROMPT_TEMPLATE.format(text=text_to_analyze[:4000])},
                ],
                response_format={"type": "json_object"},  # Ensures valid JSON
                temperature=0.1,
            )
            extracted_data = json.loads(response.choices[0].message.content)
            break
        except RateLimitError:
            wait = 5 * attempt
            logger.warning(f"Groq rate limit hit (attempt {attempt}/{MAX_RETRIES}). Sleeping {wait}s...")
            await asyncio.sleep(wait)
        except (APIError, json.JSONDecodeError) as e:
            logger.warning(f"Groq extraction attempt {attempt}/{MAX_RETRIES} failed for {raw_payload.get('id')}: {e}")
            await asyncio.sleep(attempt)
        except Exception as e:
            logger.error(f"Extraction failed for {raw_payload.get('id')}: {e}")
            return None

    if not extracted_data:
        return None

    # Reject payloads without a price — they are never indexed.
    if not extracted_data.get("price"):
        logger.debug(f"Skipping {raw_payload.get('id')}: no price extracted.")
        return None

    try:
        price = int(str(extracted_data["price"]).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

    if not (MIN_PRICE <= price <= MAX_PRICE):
        logger.debug(f"Skipping {raw_payload.get('id')}: price {price} outside sanity bounds.")
        return None

    product_name = (extracted_data.get("product_name") or "").strip()
    if not product_name:
        return None

    final_product_data = {
        "id": raw_payload["id"],
        "channel_username": raw_payload["channel_username"],
        "message_id": raw_payload["message_id"],
        "original_text": raw_payload["original_text"],
        "timestamp": raw_payload["timestamp"],
        "product_name": product_name,
        "price": price,
        "location": (extracted_data.get("location") or "Unknown").strip() or "Unknown",
    }

    logger.info(f"Extracted: {final_product_data['product_name']} | {final_product_data['price']} ETB")
    return final_product_data
