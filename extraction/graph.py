"""The stage-3 LangGraph StateGraph: retrieve -> propose_extractions -> verify_citations
-> tag_epistemic_status -> review_proposals -> detect_conflicts -> persist.

If verify_citations rejects more than half of what got proposed, the graph loops
back to propose_extractions once (same retrieved context) before continuing on to
tag/detect/persist regardless of how the retry goes.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from core.db import session_scope
from extraction.guidance import build_guidance
from extraction.nodes.cache_match import find_cached_matches
from extraction.nodes.detect_conflicts import detect_conflicts
from extraction.nodes.persist import persist
from extraction.nodes.propose_extractions import propose_extractions
from extraction.nodes.retrieve import retrieve
from extraction.nodes.review_proposals import review_proposals
from extraction.nodes.tag_epistemic_status import tag_epistemic_status
from extraction.nodes.verify_citations import verify_citations
from progress.events import publish_step

MAX_RETRIES = 1
REJECT_RETRY_THRESHOLD = 0.5


class ExtractionState(TypedDict, total=False):
    job_id: str
    tenant_id: str
    batch_id: str
    query: str
    force: bool
    retrieved_context: list[dict]
    proposals: list[dict]
    missing_fields: list[dict]
    tagged_proposals: list[dict]
    conflicted_fields: set
    retry_count: int
    created_extraction_ids: list[str]
    result_kind: str
    guidance: dict
    _served_from_cache: bool
    _cached_extraction_ids: list[str]


def _step(job_id: str, name: str):
    """Small helper so every node gets a started/done pair without repeating boilerplate."""

    def decorator(fn):
        def wrapped(state: ExtractionState) -> dict:
            publish_step("extraction_job", job_id, step=name, status="started")
            try:
                result = fn(state)
            except Exception as exc:
                publish_step("extraction_job", job_id, step=name, status="failed", detail=str(exc))
                raise
            publish_step("extraction_job", job_id, step=name, status="done")
            return result

        return wrapped

    return decorator


def build_graph(job_id: str):
    graph = StateGraph(ExtractionState)

    @_step(job_id, "check_cache")
    def check_cache_node(state: ExtractionState) -> dict:
        if state.get("force"):
            return {}
        with session_scope() as db:
            matched_ids = find_cached_matches(db, state["tenant_id"], state["batch_id"], state["query"])
        return {"_served_from_cache": bool(matched_ids), "_cached_extraction_ids": matched_ids}

    @_step(job_id, "serve_cached")
    def serve_cached_node(state: ExtractionState) -> dict:
        return {"result_kind": "EXTRACTION", "created_extraction_ids": state.get("_cached_extraction_ids", [])}

    @_step(job_id, "retrieve")
    def retrieve_node(state: ExtractionState) -> dict:
        with session_scope() as db:
            context = retrieve(db, state["tenant_id"], state["batch_id"], state["query"])
        return {"retrieved_context": context}

    @_step(job_id, "guidance")
    def guidance_node(state: ExtractionState) -> dict:
        with session_scope() as db:
            guidance = build_guidance(db, state["tenant_id"], state["batch_id"])
        return {"result_kind": "GUIDANCE", "guidance": guidance}

    @_step(job_id, "propose_extractions")
    def propose_node(state: ExtractionState) -> dict:
        def on_progress(file_index: int, total_files: int) -> None:
            publish_step(
                "extraction_job",
                job_id,
                step="propose_extractions",
                status="started",
                detail=f"reading file {file_index}/{total_files}",
            )

        proposals, missing_fields = propose_extractions(
            state["query"], state.get("retrieved_context", []), on_progress=on_progress
        )
        return {"proposals": proposals, "missing_fields": missing_fields}

    @_step(job_id, "verify_citations")
    def verify_node(state: ExtractionState) -> dict:
        with session_scope() as db:
            verified = verify_citations(db, state["tenant_id"], state["batch_id"], state.get("proposals", []))
        return {"proposals": verified}

    @_step(job_id, "tag_epistemic_status")
    def tag_node(state: ExtractionState) -> dict:
        tagged = tag_epistemic_status(state.get("proposals", []))
        return {"tagged_proposals": tagged}

    @_step(job_id, "review_proposals")
    def review_node(state: ExtractionState) -> dict:
        reviewed, newly_missing = review_proposals(
            state.get("tagged_proposals", []), state.get("retrieved_context", []), state["query"]
        )
        return {
            "tagged_proposals": reviewed,
            "missing_fields": state.get("missing_fields", []) + newly_missing,
        }

    @_step(job_id, "detect_conflicts")
    def detect_node(state: ExtractionState) -> dict:
        with session_scope() as db:
            tagged, conflicted = detect_conflicts(
                db, state["tenant_id"], state["batch_id"], state.get("tagged_proposals", [])
            )
        return {"tagged_proposals": tagged, "conflicted_fields": conflicted}

    @_step(job_id, "persist")
    def persist_node(state: ExtractionState) -> dict:
        created = persist(
            state["tenant_id"],
            state["batch_id"],
            state.get("tagged_proposals", []),
            state.get("conflicted_fields", set()),
        )
        return {"created_extraction_ids": created}

    def needs_guidance(state: ExtractionState) -> str:
        # no query, or the query matched nothing in the batch: show guidance
        # instead of an empty result
        if not state["query"].strip():
            return "guidance"
        if not state.get("retrieved_context"):
            return "guidance"
        return "extract"

    def should_retry(state: ExtractionState) -> str:
        proposals = state.get("proposals", [])
        retry_count = state.get("retry_count", 0)
        if not proposals or retry_count >= MAX_RETRIES:
            return "continue"

        rejected = sum(1 for p in proposals if not (p.get("_citation_verification") or {}).get("verified", False))
        if rejected / len(proposals) > REJECT_RETRY_THRESHOLD:
            return "retry"
        return "continue"

    def bump_retry(state: ExtractionState) -> dict:
        return {"retry_count": state.get("retry_count", 0) + 1}

    def needs_full_pipeline(state: ExtractionState) -> str:
        return "cached" if state.get("_served_from_cache") else "run"

    def nothing_came_of_it(state: ExtractionState) -> str:
        # falls back to guidance if the run produced neither extractions nor
        # missing-field reports
        if state.get("created_extraction_ids") or state.get("missing_fields"):
            return "done"
        return "guidance"

    graph.add_node("check_cache", check_cache_node)
    graph.add_node("serve_cached", serve_cached_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("guidance", guidance_node)
    graph.add_node("propose_extractions", propose_node)
    graph.add_node("verify_citations", verify_node)
    graph.add_node("bump_retry", bump_retry)
    graph.add_node("tag_epistemic_status", tag_node)
    graph.add_node("review_proposals", review_node)
    graph.add_node("detect_conflicts", detect_node)
    graph.add_node("persist", persist_node)

    graph.set_entry_point("check_cache")
    graph.add_conditional_edges(
        "check_cache",
        needs_full_pipeline,
        {"cached": "serve_cached", "run": "retrieve"},
    )
    graph.add_edge("serve_cached", END)
    graph.add_conditional_edges(
        "retrieve",
        needs_guidance,
        {"guidance": "guidance", "extract": "propose_extractions"},
    )
    graph.add_edge("guidance", END)
    graph.add_edge("propose_extractions", "verify_citations")
    graph.add_conditional_edges(
        "verify_citations",
        should_retry,
        {"retry": "bump_retry", "continue": "tag_epistemic_status"},
    )
    graph.add_edge("bump_retry", "propose_extractions")
    graph.add_edge("tag_epistemic_status", "review_proposals")
    graph.add_edge("review_proposals", "detect_conflicts")
    graph.add_edge("detect_conflicts", "persist")
    graph.add_conditional_edges(
        "persist",
        nothing_came_of_it,
        {"done": END, "guidance": "guidance"},
    )

    return graph.compile()


def run(job_id: str, tenant_id: str, batch_id: str, query: str, force: bool = False) -> dict:
    app = build_graph(job_id)
    try:
        final_state = app.invoke(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "query": query,
                "force": force,
                "retry_count": 0,
            }
        )
    except Exception as exc:
        # the frontend's terminal check looks for a step literally named "done"
        publish_step("extraction_job", job_id, step="done", status="failed", detail=str(exc))
        raise

    publish_step("extraction_job", job_id, step="done", status="done")

    return {
        "created_extraction_ids": final_state.get("created_extraction_ids", []),
        "result_kind": final_state.get("result_kind", "EXTRACTION"),
        "guidance": final_state.get("guidance"),
        "missing_fields": final_state.get("missing_fields", []),
    }
