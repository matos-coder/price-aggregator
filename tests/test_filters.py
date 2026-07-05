from scraper.filters import contains_price, is_valid_product_message


def test_plain_price_detected():
    assert contains_price("Macbook Pro M2 selling for 250000")


def test_comma_price_detected():
    assert contains_price("HP Elitebook 840 G5 — 45,000 birr")


def test_k_suffix_price_detected():
    assert contains_price("iPhone 13 128GB 80k")


def test_birr_suffix_detected():
    assert contains_price("Samsung A25 32000 br")


def test_amharic_birr_detected():
    assert contains_price("ዋጋ 25000 ብር")


def test_phone_number_alone_is_not_a_price():
    assert not contains_price("Call us 0911223344 or +251911223344")


def test_phone_number_plus_real_price_is_a_price():
    assert contains_price("iPhone 13 for 80,000. Call 0911223344")


def test_no_digits_is_not_a_price():
    assert not contains_price("New arrivals! DM for details")


def test_empty_message_invalid():
    assert not is_valid_product_message("")
    assert not is_valid_product_message("   ")
