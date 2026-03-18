import os
import json
import logging
from dotenv import load_dotenv
from groq import Groq

# Setup Logging
logger = logging.getLogger("Extractor")

# Load ENV and Configure Gemini
load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    logger.error("CRITICAL: GROQ_API_KEY missing in .env")
    exit(1)

# Initialize the Groq client
client = Groq(api_key=API_KEY)

# Define the model ID
MODEL_NAME = "llama-3.3-70b-versatile"

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
        # Use Groq client instead of Gemini 'model'
        # Groq's Python SDK is synchronous by default; 
        # for a scraper, this is usually fine.
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a product extraction API that only outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}, # Ensures valid JSON
            temperature=0.1
        )
        
        # Get the text content from the Groq response
        extracted_text = response.choices[0].message.content
        extracted_data = json.loads(extracted_text)
        
        # If the LLM couldn't find a price, we reject the payload. 
        if not extracted_data.get("price"):
            logger.debug(f"Skipping. No valid price extracted from: {raw_payload['id']}")
            return None

        # Ensure price is an integer (Groq might return "500" as a string)
        try:
            extracted_data["price"] = int(str(extracted_data["price"]).replace(',', ''))
        except:
            return None

        # Merge the extracted data
        final_product_data = {
            "id": raw_payload["id"],
            "channel_username": raw_payload["channel_username"],
            "message_id": raw_payload["message_id"],
            "original_text": raw_payload["original_text"],
            "timestamp": raw_payload["timestamp"],
            "product_name": extracted_data.get("product_name"),
            "price": extracted_data.get("price"),
            "location": extracted_data.get("location", "Unknown")
        }
        
        logger.info(f"Extracted: {final_product_data['product_name']} | {final_product_data['price']} ETB")
        return final_product_data

    except Exception as e:
        logger.error(f"Extraction failed for {raw_payload.get('id')}: {e}")
        return None
