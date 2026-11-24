"""Unit tests for verify_citations.quote_matches - a scanned PDF page is stored as a
single OCR block with its own line breaks, so a correct quote must still verify
despite whitespace differences and small OCR noise, while an absent quote fails.
"""

from extraction.nodes.verify_citations import quote_matches

# real OCR text of 03_appraisal_working_papers_scan.pdf page 2, as stored
SCAN_PAGE_2 = (
    "WORKING PAPERS / WAREHOUSE APPRAISAL VAL-2617\n\ni\n\nIncome calculation notes\n\nIncome assumptions\n\n"
    "Use 12 months of market rent on the net lettable area, then deduct 5% for vacancy.\n\n"
    "Deduct annual operating expenses of INR 1.68 million from effective gross income to obtain net\n"
    "operating income.\n\nRate selection\n\nOccupancy equals 100% less vacancy. Use a 10% capitalization "
    "rate when occupancy is at least\n95%. Use 11% below 95%.\n\nValue method\n\nApply direct capitalization. "
    "Divide annual net operating income by the applicable capitalization rate\nand round to the nearest INR "
    "100,000.\n\nThe adopted market value is issued separately.\n\nSYNTHETIC RECORD | INTERNAL FILE COPY Page 2 of 2"
)


def test_quote_spanning_an_ocr_line_break_matches():
    quote = "Occupancy equals 100% less vacancy. Use a 10% capitalization rate when occupancy is at least 95%. Use 11% below 95%."
    assert quote_matches(quote, SCAN_PAGE_2)[0]


def test_quote_spanning_heading_and_body_matches():
    quote = (
        "Value method\nApply direct capitalization. Divide annual net operating income by the applicable "
        "capitalization rate and round to the nearest INR 100,000."
    )
    assert quote_matches(quote, SCAN_PAGE_2)[0]


def test_quote_with_ocr_typo_inside_a_long_page_matches():
    quote = "Divide annual net operatlng income by the appIicable capitalization rate and round to the nearest INR 100,000."
    assert quote_matches(quote, SCAN_PAGE_2)[0]


def test_absent_quote_still_fails():
    quote = "Use a 7% capitalization rate for all occupancy levels and add a 3% annual growth allowance."
    matched, ratio = quote_matches(quote, SCAN_PAGE_2)
    assert not matched
    assert ratio < 0.8


def test_empty_quote_fails():
    assert not quote_matches("   ", SCAN_PAGE_2)[0]
