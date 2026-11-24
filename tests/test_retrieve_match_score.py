"""Unit tests for retrieve._match_score - the fuzzy header-to-query matcher that
decides which spreadsheet cells get pulled into a query's retrieved context.
Recall matters here: this is deliberately loose (verify_citations is the real
gate), but it still needs to actually fire on realistic header/query pairs.
"""

from extraction.nodes.retrieve import _match_score, _WORD_RE


def _score(query: str, header: str) -> float:
    return _match_score(query.lower(), set(_WORD_RE.findall(query.lower())), header.lower())


def test_exact_substring_header_scores_perfectly():
    assert _score("what is the cap rate for this property?", "Cap Rate") == 1.0


def test_all_header_words_present_scores_perfectly():
    assert _score("what is the property address", "Property Address") == 1.0


def test_partial_word_overlap_scores_partial():
    # 2 of the header's 3 words ("cap", "rate") show up in the query, "assumption" doesn't
    score = _score("what is the cap rate for this deal", "Cap Rate Assumption")
    assert abs(score - 2 / 3) < 1e-6


def test_unrelated_header_scores_zero():
    assert _score("what is the client name", "Market Note") == 0.0


def test_minor_spelling_variation_still_matches():
    # "Valution" (typo) in the query should still fuzzy-match "Valuation" in the header
    score = _score("what is the valution date", "Valuation Date")
    assert score > 0.0
