"""Cheap pre-filters that run BEFORE the LLM, so we never spend Groq quota
on messages that obviously aren't product listings."""
import re

# Formats seen in Ethiopian shop channels: 80000, 80,000, 80k, 80000 birr/br/ETB, ዋጋ 80000
_PRICE_PATTERNS = [
    re.compile(r"\b\d{4,7}\b"),
    re.compile(r"\b\d{2,4}\s?k\b", re.IGNORECASE),
    re.compile(r"\b\d[\d,]*\s?(birr|br|etb|ብር)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,3}(,\d{3})+\b"),
]

# Ethiopian phone numbers look like prices to the naive digit patterns above.
_PHONE_RE = re.compile(r"(\+?251|0)9\d{8}")


def contains_price(text: str) -> bool:
    """True if the text plausibly contains a price (not just a phone number)."""
    stripped = _PHONE_RE.sub(" ", text)
    return any(p.search(stripped) for p in _PRICE_PATTERNS)


def is_valid_product_message(text: str) -> bool:
    if not text or not text.strip():
        return False
    return contains_price(text)
