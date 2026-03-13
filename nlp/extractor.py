import os
import json
import logging
import google.generativeai as genai
from dotenv import load_dotenv

# Setup Logging
logger = logging.getLogger("Extractor")

# Load ENV and Configure Gemini
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    logger.error("CRITICAL: GEMINI_API_KEY missing in .env")
    exit(1)

genai.configure(api_key=API_KEY)

# Use the fast Flash model for sub-second extraction
# We force the model to output strict JSON
model = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config={
        "response_mime_type": "application/json",
        "temperature": 0.1, # Keep it strictly factual, no creative guessing
    }
)

async def extract_entities(raw_payload: dict) -> dict:
    """
    Takes the raw Telegram payload, uses an LLM to extract Product, Price, and Location,
    and returns a clean dictionary ready for Meilisearch.
    """
    text_to_analyze = raw_payload.get("original_text", "")
    
    prompt = f"""
    You are an e-commerce data extraction API. 
    Analyze the following Amharic/English Telegram message.
    Extract the product name, the price (convert to integer, remove commas/letters), and the location.
    
    Rules:
    - If there are multiple products, pick the main one.
    - If you cannot find a price, return null for price.
    - If you cannot find a location, return "Unknown".
    
    Output strictly in this JSON format:
    {{"product_name": "string", "price": "integer or null", "location": "string"}}
    
    Message:
    {text_to_analyze}
    """
    
    try:
        # Call Gemini asynchronously
        response = await model.generate_content_async(prompt)
        extracted_data = json.loads(response.text)
        
        # If the LLM couldn't find a price, we reject the payload. 
        # A commerce aggregator is useless without prices.
        if not extracted_data.get("price") or not isinstance(extracted_data["price"], int):
            logger.debug(f"Skipping. No valid price extracted from: {raw_payload['id']}")
            return None

        # Merge the LLM's extracted data with our original Telegram payload
        final_product_data = {
            "id": raw_payload["id"],
            "channel_username": raw_payload["channel_username"],
            "message_id": raw_payload["message_id"],
            "original_text": raw_payload["original_text"],
            "timestamp": raw_payload["timestamp"],
            # Extracted fields:
            "product_name": extracted_data["product_name"],
            "price": extracted_data["price"],
            "location": extracted_data["location"]
        }
        
        logger.info(f"Extracted: {final_product_data['product_name']} | {final_product_data['price']} ETB")
        return final_product_data

    except Exception as e:
        logger.error(f"Extraction failed for {raw_payload.get('id')}: {e}")
        return None