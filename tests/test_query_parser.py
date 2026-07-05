from nlp.query_parser import parse_user_query_fallback


def test_full_query_with_specs_budget_and_location():
    query, max_price, location = parse_user_query_fallback(
        "I want a macbook m2 16gb under 120k in bole"
    )
    assert query == "macbook m2 16gb"
    assert max_price == 120000
    assert location == "bole"


def test_comma_separated_budget():
    query, max_price, location = parse_user_query_fallback("iphone 13 under 50,000")
    assert query == "iphone 13"
    assert max_price == 50000
    assert location is None


def test_budget_synonyms():
    for phrase in ["below 70000", "less than 70000", "max 70000", "up to 70000"]:
        _, max_price, _ = parse_user_query_fallback(f"laptop {phrase}")
        assert max_price == 70000, phrase


def test_bare_product_query():
    query, max_price, location = parse_user_query_fallback("samsung a25")
    assert query == "samsung a25"
    assert max_price is None
    assert location is None


def test_location_only_word_boundaries():
    # 'a25' must not trip the 'a' filler word; 'piassa' is a known location
    query, _, location = parse_user_query_fallback("samsung a25 piassa")
    assert query == "samsung a25"
    assert location == "piassa"


def test_filler_words_stripped():
    query, _, _ = parse_user_query_fallback("I'm looking for the price of hp elitebook")
    assert query == "hp elitebook"
