"""Unit tests for the semantic review step's deterministic half (applying keep/
rename/drop decisions), the never-conflict rule for LOGIC fields, wider date
parsing, and cross-sheet formula evaluation."""

from extraction.nodes.detect_conflicts import _try_parse_date, _values_equal, is_logic_category
from extraction.nodes.persist import _headline_priority
from extraction.nodes.review_proposals import CandidateReview, apply_reviews
from ingestion.formula_eval import evaluate


def _p(field_name, value, category="property_detail"):
    return {"field_name": field_name, "field_category": category, "value": value, "source_ref": {}}


def test_apply_reviews_assigns_fact_names_and_drops_unsupported():
    proposals = [
        _p("Property Area", "20,000 sq ft"),
        _p("Property Area", "31,400 sq ft"),
        _p("Usable Letting Space", "20,000 sq ft"),
        _p("Methodology", "This amount is the adopted market value.", "valuation_info"),
    ]
    reviews = {
        "C1": CandidateReview(candidate_id="C1", decision="keep", fact_name="Net Lettable Area", reason="x"),
        "C2": CandidateReview(candidate_id="C2", decision="keep", fact_name="Site Parcel Area", reason="x"),
        "C3": CandidateReview(candidate_id="C3", decision="keep", fact_name="Net Lettable Area", reason="x"),
        "C4": CandidateReview(candidate_id="C4", decision="drop", reason="not a methodology"),
    }
    kept, missing = apply_reviews(proposals, reviews)
    assert [p["field_name"] for p in kept] == ["Net Lettable Area", "Site Parcel Area", "Net Lettable Area"]
    assert [m["field_name"] for m in missing] == ["Methodology"]


def test_reviewer_cannot_drop_spreadsheet_backed_or_figure_bearing_values():
    cell = {**_p("Capitalization Rate Applied", "0.1", "valuation_info"), "source_ref": {"citation_type": "spreadsheet_cell"}}
    formula = {**_p("Assessed Value Logic", "NOI / cap rate", "logic"), "source_ref": {"citation_type": "formula_edge_path"}}
    site = {**_p("Property Area", "31,400 sq ft"), "source_ref": {"citation_type": "document_block"}}
    sentence = {**_p("Methodology", "This amount is the adopted market value."), "source_ref": {"citation_type": "document_block"}}
    reviews = {f"C{i}": CandidateReview(candidate_id=f"C{i}", decision="drop", reason="x") for i in range(1, 5)}
    kept, _ = apply_reviews([cell, formula, site, sentence], reviews)
    assert [p["field_name"] for p in kept] == ["Capitalization Rate Applied", "Assessed Value Logic", "Property Area"]


def test_apply_reviews_never_reports_a_dropped_logic_candidate_as_missing():
    proposals = [_p("Valuation Logic", "The schedule is filed with the working papers.", "logic")]
    reviews = {"C1": CandidateReview(candidate_id="C1", decision="drop", reason="pointer only")}
    kept, missing = apply_reviews(proposals, reviews)
    assert kept == [] and missing == []


def test_apply_reviews_does_not_report_missing_when_another_candidate_survives():
    proposals = [_p("Methodology", "Direct capitalization"), _p("Methodology", "This amount is the adopted value.")]
    reviews = {
        "C1": CandidateReview(candidate_id="C1", decision="keep", reason="x"),
        "C2": CandidateReview(candidate_id="C2", decision="drop", reason="x"),
    }
    kept, missing = apply_reviews(proposals, reviews)
    assert len(kept) == 1 and missing == []


def test_apply_reviews_keeps_candidates_with_no_review():
    kept, missing = apply_reviews([_p("Client Name", "Emberline Logistics Pvt Ltd")], {})
    assert len(kept) == 1 and missing == []


def test_long_form_dates_parse_and_compare_equal():
    assert _try_parse_date("30 September 2026") is not None
    assert _try_parse_date("30th Sept 2026") is not None
    assert _values_equal("30 September 2026", "2026-09-30")
    assert _values_equal("The valuation is effective 30 September 2026.", "30 September 2026")


def test_a_bare_number_is_not_a_date():
    assert _try_parse_date("60") is None


def test_logic_categories():
    assert is_logic_category("logic")
    assert is_logic_category("Methodology")
    assert not is_logic_category("valuation_info")


def test_narrative_logic_is_preferred_as_headline_over_formula_description():
    narrative = {"field_category": "logic", "epistemic_status": "explicit", "source_ref": {"citation_type": "document_block"}}
    formula = {"field_category": "logic", "epistemic_status": "explicit", "source_ref": {"citation_type": "formula_edge_path"}}
    assert min([formula, narrative], key=_headline_priority) is narrative


def test_explicit_still_beats_narrative_that_is_undetermined():
    narrative = {"field_category": "logic", "epistemic_status": "undetermined", "source_ref": {"citation_type": "document_block"}}
    formula = {"field_category": "logic", "epistemic_status": "explicit", "source_ref": {"citation_type": "formula_edge_path"}}
    assert min([narrative, formula], key=_headline_priority) is formula


def test_formula_eval_resolves_cross_sheet_refs_and_round():
    cells = {"Bridge!D10": 120_000_000, "Inputs!D8": 0.05}
    lookup = lambda ref: cells.get(ref)  # noqa: E731
    assert evaluate("=ROUND(Bridge!D10/100000,0)*100000", lookup) == (120_000_000.0, True)
    assert evaluate("=1-'Inputs'!D8", lookup) == (0.95, True)


def test_formula_eval_excel_round_is_half_away_from_zero():
    assert evaluate("=ROUND(2.5,0)", lambda ref: None) == (3.0, True)
    assert evaluate("=ROUND(-2.5,0)", lambda ref: None) == (-3.0, True)


def test_spreadsheet_numbers_keep_their_units():
    from extraction.nodes.propose_extractions import _attach_units

    cells = [
        ("Bridge!D7 | Net operating income INR/year: 12000000", "12000000"),
        ("Operating Inputs!D8 | Vacancy allowance rate: 0.05", "0.05"),
        ("Operating Inputs!D6 | Net lettable area sq ft: 20000", "20000"),
        ("Desk View!D6 | Adopted market value INR: 120000000", "120000000"),
    ]
    context = [{"spreadsheet_cell_id": str(i), "text": t, "cached_value": v} for i, (t, v) in enumerate(cells)]
    # the model's own renderings vary; the cell's number and unit win
    model_values = ["12000000", "5 percent", "20000", "120,000,000 INR (adopted market value)"]
    proposals = [
        {"field_category": "valuation_info", "value": v, "source_ref": {"spreadsheet_cell_id": str(i)}}
        for i, v in enumerate(model_values)
    ]
    _attach_units(proposals, context)
    assert [p["value"] for p in proposals] == ["INR 12,000,000 per year", "5%", "20,000 sq ft", "INR 120,000,000"]


def test_model_formatted_amounts_compare_equal():
    assert _values_equal("INR 12 crore", "120,000,000 INR (adopted market value)")
    assert _values_equal("INR 1.68 million", "1,680,000 INR/year")
    assert _values_equal("INR 60 per sq ft per month", "60 INR/sq ft/mo")
    assert not _values_equal("INR 12 crore", "INR 11 crore")


def test_percent_and_text_containment_compare_equal():
    assert _values_equal("10%", "0.1")
    assert not _values_equal("10%", "0.11")
    assert _values_equal("Direct capitalization", "Apply direct capitalization.")


def test_evidence_types_distinguish_inputs_outputs_and_narrative_logic():
    from extraction.nodes.persist import _classify_evidence_type

    data = {"field_category": "valuation_info"}
    logic = {"field_category": "logic", "epistemic_status": "explicit"}
    assert _classify_evidence_type(data, "formula_edge_path") == "calculated_output"
    assert _classify_evidence_type(data, "spreadsheet_cell") == "supporting_input"
    assert _classify_evidence_type(data, "document_block") is None
    assert _classify_evidence_type(logic, "formula_edge_path") == "formula_trace"
    assert _classify_evidence_type(logic, "document_block") == "narrative_rule"


def test_identical_reference_codes_under_different_names_share_one_name():
    from extraction.nodes.review_proposals import unify_identical_codes

    proposals = [
        _p("Valuation Reference", "VAL-2617", "valuation_info"),
        _p("Valuation Reference", "VAL-2617", "valuation_info"),
        _p("Report Reference", "VAL-2617", "valuation_info"),
        _p("Client Name", "Some Client Ltd", "client_info"),
    ]
    names = [p["field_name"] for p in unify_identical_codes(proposals)]
    assert names == ["Valuation Reference", "Valuation Reference", "Valuation Reference", "Client Name"]


def test_amounts_and_dates_are_not_treated_as_codes():
    from extraction.nodes.review_proposals import unify_identical_codes

    proposals = [_p("A", "2026-09-30", "valuation_info"), _p("B", "2026-09-30", "valuation_info")]
    assert [p["field_name"] for p in unify_identical_codes(proposals)] == ["A", "B"]
