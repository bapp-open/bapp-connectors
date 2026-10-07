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


def test_a_list_is_not_a_note():
    """Gomag tine sub `note` istoricul comentariilor interne. `str([])` ar fi intors
    textul "[]" ca observatie a clientului pe fiecare comanda — s-a si intimplat."""
    assert customer_note_from({"note": []}, "note") == ""
    assert customer_note_from({"note": [{"comment": "intern"}]}, "note") == ""
    assert customer_note_from({"note": {"comment": "intern"}}, "note") == ""


def test_falls_through_a_structured_key_to_a_real_one():
    payload = {"note": [{"comment": "intern"}], "observation": "sunati inainte"}
    assert customer_note_from(payload, "note", "observation") == "sunati inainte"


def test_staff_notes_read_as_who_wrote_what():
    from bapp_connectors.providers.shop.notes import staff_notes_from

    entries = [
        {"comment": "Comanda plasata telefonic", "user": "Alina", "time": 1791277326},
        {"comment": "Proforma trimisa", "user": "Mihai", "time": 1791277609},
    ]
    assert staff_notes_from(entries) == "Alina: Comanda plasata telefonic\nMihai: Proforma trimisa"


def test_staff_notes_survive_the_shapes_a_shop_can_send():
    from bapp_connectors.providers.shop.notes import staff_notes_from

    assert staff_notes_from([]) == ""
    assert staff_notes_from(None) == ""
    assert staff_notes_from("nu e lista") == ""
    assert staff_notes_from([{"comment": "  "}, "junk", {"user": "fara comentariu"}]) == ""
    assert staff_notes_from([{"comment": "fara autor"}]) == "fara autor"
