"""The helper every shop mapper reads the customer's note through."""

from bapp_connectors.providers.shop.notes import customer_note_from


def test_takes_the_first_key_that_holds_text():
    assert customer_note_from({"note": "ridicam noi"}, "observation", "note") == "ridicam noi"
    assert (
        customer_note_from({"observation": "sunati inainte", "note": "altceva"}, "observation", "note")
        == "sunati inainte"
    )


def test_skips_a_key_the_shop_filled_with_nothing():
    """Shops disagree on how to say "no note": `None`, `""`, or spaces."""
    payload = {"observation": None, "observations": "   ", "note": "la receptie"}
    assert customer_note_from(payload, "observation", "observations", "note") == "la receptie"


def test_is_empty_when_the_shop_has_no_note():
    assert customer_note_from({"observation": None}, "observation") == ""
    assert customer_note_from({}, "note") == ""
    assert customer_note_from(None, "note") == ""


def test_reads_only_the_keys_it_was_given():
    """No generic sniffing: a key that means something else elsewhere cannot leak in."""
    assert customer_note_from({"internal_note": "nu e a clientului"}, "customer_note") == ""


def test_keeps_the_text_as_the_customer_wrote_it_bar_the_edges():
    assert customer_note_from({"note": "  Multumesc!  "}, "note") == "Multumesc!"


def test_a_number_still_comes_back_as_text():
    assert customer_note_from({"note": 1234}, "note") == "1234"
