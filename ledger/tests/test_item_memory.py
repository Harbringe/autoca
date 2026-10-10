"""Remembering what a party's lines usually say. Pure: no database."""

from ledger import item_memory as memory

BATCH = [
    {"read_description": "FPPUSLH1880000 ULTRATECH SUPER PPC 120 Bags LM HDPE/PP UT SUPER", "description": "Ultratech Super PPC Cement",
     "hsn_sac": "2523", "unit": "Bag", "quantity": "60"},
]


def test_a_confirmed_line_teaches_description_hsn_unit_and_usual_quantity():
    products = memory.learn([BATCH, BATCH, [{**BATCH[0], "quantity": "120"}]])
    (product,) = products
    assert product["description"] == "Ultratech Super PPC Cement"
    assert product["hsn_sac"] == "2523" and product["unit"] == "Bag"
    assert product["usual_quantity"] == "60"  # twice 60, once 120


def test_the_next_invoice_with_a_different_batch_code_is_recognised():
    products = memory.learn([BATCH])
    lines = [{"description": "FPPUSLH9990001 ULTRATECH SUPER PPC 120 Bags LM HDPE/PP UT SUPER", "hsn_sac": "", "unit": "", "quantity": ""}]
    (line,) = memory.apply(lines, products)
    assert line["description"] == "Ultratech Super PPC Cement"
    assert line["read_description"].startswith("FPPUSLH9990001")
    assert (line["hsn_sac"], line["unit"], line["quantity"]) == ("2523", "Bag", "60")
    assert line["remembered"] is True


def test_what_the_page_printed_is_never_overwritten():
    products = memory.learn([BATCH])
    lines = [{"description": "ULTRATECH SUPER PPC 120 Bags HDPE", "hsn_sac": "25232910", "unit": "MT", "quantity": "6.0"}]
    (line,) = memory.apply(lines, products)
    assert (line["hsn_sac"], line["unit"], line["quantity"]) == ("25232910", "MT", "6.0")
    assert line["usual_quantity"] == "60"  # still offered as a hint


def test_a_different_product_is_left_alone():
    products = memory.learn([BATCH])
    (line,) = memory.apply([{"description": "Sun Flower Oil 13 Kg tin", "quantity": ""}], products)
    assert line["description"] == "Sun Flower Oil 13 Kg tin" and "remembered" not in line


def test_nothing_is_learned_from_a_line_without_a_confirmed_description():
    assert memory.learn([[{"read_description": "", "description": ""}]]) == []
