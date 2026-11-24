"""Unit test for retrieve._cap_per_file - regression coverage for a real bug: the
old code capped retrieved spreadsheet-cell (and, separately, Qdrant) hits at TOP_K
across the WHOLE BATCH, so a batch with more than a handful of files let one file's
matches crowd out every other file's. A broad query ("extract everything") would
then silently come back empty-handed for most files, not because nothing matched,
but because the global top-K cutoff never even considered their hits.
"""

from extraction.nodes.retrieve import _cap_per_file, TOP_K


def _hit(file_id: str, score: float) -> dict:
    return {"file_id": file_id, "score": score}


def test_cap_applies_per_file_not_globally():
    # 3 files, each with more matches than TOP_K - every file must still contribute
    # up to TOP_K of its own hits, not share one batch-wide TOP_K budget
    hits = []
    for file_id in ("file-a", "file-b", "file-c"):
        hits.extend(_hit(file_id, score) for score in range(TOP_K + 5))

    capped = _cap_per_file(hits, TOP_K)

    assert len(capped) == 3 * TOP_K
    for file_id in ("file-a", "file-b", "file-c"):
        assert sum(1 for h in capped if h["file_id"] == file_id) == TOP_K


def test_cap_keeps_the_highest_scoring_hits_for_each_file():
    hits = [_hit("file-a", s) for s in [0.1, 0.9, 0.5, 0.3]]
    capped = _cap_per_file(hits, top_k=2)
    assert sorted(h["score"] for h in capped) == [0.5, 0.9]


def test_file_with_fewer_than_top_k_hits_keeps_them_all():
    hits = [_hit("file-a", 0.9)]
    assert _cap_per_file(hits, top_k=8) == hits
