"""Unit tests for extraction/nodes/cache_match.py's pure heuristics - deciding
whether a follow-up query is already fully answered by what's been persisted, so
the full LLM/retrieval pipeline doesn't re-run on every query, while never silently
dropping part of a multi-field query that isn't cached yet.
"""

from extraction.nodes.cache_match import _field_match_score, _is_fully_covered


def test_field_fully_covered_by_query_words():
    query_words = {"what", "is", "the", "property", "address"}
    assert _field_match_score("property_address", query_words) == 1.0


def test_field_not_mentioned_in_query_scores_zero():
    query_words = {"what", "is", "the", "client", "name"}
    assert _field_match_score("property_address", query_words) == 0.0


def test_field_with_no_words_scores_zero():
    assert _field_match_score("", {"anything"}) == 0.0


def test_single_field_query_fully_covered_by_matching_field():
    query_words = {"what", "is", "the", "client", "name"}
    assert _is_fully_covered(query_words, ["client_name"])


def test_multi_field_query_only_partially_cached_is_not_fully_covered():
    # "client name" is cached, but "cap rate" isn't - must NOT be served from cache,
    # or the cap rate ask would silently disappear
    query_words = {"what", "is", "the", "client", "name", "and", "cap", "rate"}
    assert not _is_fully_covered(query_words, ["client_name"])


def test_multi_field_query_fully_covered_when_every_field_is_cached():
    query_words = {"client", "name", "and", "property", "address"}
    assert _is_fully_covered(query_words, ["client_name", "property_address"])


def test_query_with_only_stopwords_is_never_considered_covered():
    assert not _is_fully_covered({"what", "is", "the"}, ["client_name"])
