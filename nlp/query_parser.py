"""Turns a free-text buyer message ("I want a macbook m2 16gb under 120k in bole")
into a structured search: (search_query, max_price, location).

Primary path is a fast Groq call; if the LLM is unavailable, slow, or returns
garbage, we fall back to a pure-regex parser so the bot always answers.
"""
import os
import re
import json
import asyncio
import logging

from dotenv import load_dotenv

logger = logging.getLogger("QueryParser")

load_dotenv()

_groq_client = None
if os.getenv("GROQ_API_KEY"):
    try:
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    except Exception as e:  # never let query parsing take the bot down
        logger.warning(f"Groq unavailable for query parsing, using regex fallback only: {e}")

MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_TIMEOUT_SECONDS = 6

# Addis Ababa areas commonly named in shop listings.
KNOWN_LOCATIONS = [
    "bole", "megenagna", "piassa", "piazza", "4kilo", "arat kilo", "6kilo",
    "sarbet", "mexico", "kazanchis", "gerji", "cmc", "ayat", "lebu", "jemo",
    "summit", "stadium", "merkato", "lideta", "gotera", "saris", "kality",
    "hayahulet", "kera", "gurd shola", "tor hailoch", "addis ababa",
]

_FILLER_RE = re.compile(
    r"\b(i want|i need|i am looking for|i'm looking for|looking for|do you have|"
    r"can i get|please find( me)?|find me|search( for)?|show me|buy|price of|"
    r"how much is|what is the price of|please|a|an|the)\b",
    re.IGNORECASE,
)

_MAX_PRICE_RE = re.compile(
    r"\b(?:under|below|less than|max(?:imum)?|budget(?: of)?|up to|not more than|within)\s*"
    r"(\d[\d,]*)\s*(k)?\s*(?:birr|br|etb|ብር)?\b",
    re.IGNORECASE,
)


def _normalize_price(number: str, k_suffix: str | None) -> int:
    value = int(number.replace(",", ""))
    if k_suffix:
        value *= 1000
    return value


def parse_user_query_fallback(user_text: str) -> tuple[str, int | None, str | None]:
    """Pure-regex parser. Always available, no network calls."""
    text = user_text.lower()
    max_price = None
    location = None

    price_match = _MAX_PRICE_RE.search(text)
    if price_match:
        max_price = _normalize_price(price_match.group(1), price_match.group(2))
        text = text.replace(price_match.group(0), " ")

    for loc in KNOWN_LOCATIONS:
        if re.search(rf"\b{re.escape(loc)}\b", text):
            location = loc
            text = re.sub(rf"\b(in|at|around|near)?\s*{re.escape(loc)}\b", " ", text)
            break

    text = _FILLER_RE.sub(" ", text)
    query = re.sub(r"[^\w\s+.-]", " ", text)
    query = re.sub(r"\s+", " ", query).strip()
    return query, max_price, location


_LLM_PROMPT = """You convert a buyer's message into a product search for an Ethiopian marketplace.

The buyer wrote (Amharic or English):
{text}

Return JSON with exactly these keys:
- "search_query": the product terms to search — brand, model and specs only
  (e.g. "macbook pro m2 16gb"). Drop conversational filler, price limits and
  locations. English, lowercase. If the message is not a product request, return "".
- "max_price": the maximum price in ETB as an integer ("120k" means 120000), or null if none given.
- "location": the Addis Ababa area mentioned (lowercase English, e.g. "bole"), or null.

Output only the JSON object."""


async def parse_user_query(user_text: str) -> tuple[str, int | None, str | None]:
    """LLM-first parse with regex fallback. Returns (search_query, max_price, location)."""
    if _groq_client is not None:
        try:
            response = await asyncio.wait_for(
                _groq_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a search-query parsing API that only outputs JSON."},
                        {"role": "user", "content": _LLM_PROMPT.format(text=user_text[:1000])},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            data = json.loads(response.choices[0].message.content)

            query = str(data.get("search_query") or "").strip().lower()
            max_price = data.get("max_price")
            if max_price is not None:
                max_price = int(str(max_price).replace(",", ""))
                if max_price <= 0:
                    max_price = None
            location = data.get("location")
            if location:
                location = str(location).strip().lower() or None

            if query:
                return query, max_price, location
            # LLM says it's not a product request — trust the fallback to try anyway.
        except Exception as e:
            logger.warning(f"LLM query parse failed, using regex fallback: {e}")

    return parse_user_query_fallback(user_text)
