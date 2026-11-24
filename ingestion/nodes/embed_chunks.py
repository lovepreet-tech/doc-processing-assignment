"""Embeds each parsed DocumentBlock's text directly onto its own `embedding`
column (pgvector), queried later via cosine_distance (see
extraction/nodes/retrieve.py).

Best-effort: if OPENAI_API_KEY isn't set or langchain_openai isn't installed,
logs a warning and skips rather than failing the whole ingest.

Spreadsheet cells are not embedded; retrieve.py's _search_cells finds them via
structural header-text fuzzy matching instead.
"""

import logging

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_embedder():
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set - skipping embedding for this file")
        return None
    try:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            timeout=settings.openai_request_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("could not init embeddings client, skipping: %s", exc)
        return None


def embed_chunks(file, blocks: list | None = None, cells: list | None = None) -> None:
    # cells is accepted for call-site compatibility but is unused - see module docstring
    embedder = _get_embedder()
    if embedder is None:
        return

    textful_blocks = [block for block in blocks or [] if block.text]
    if not textful_blocks:
        return
    try:
        vectors = embedder.embed_documents([block.text for block in textful_blocks])
    except Exception as exc:
        logger.warning("embedding call failed for %d blocks, skipping: %s", len(textful_blocks), exc)
        return
    for block, vector in zip(textful_blocks, vectors):
        block.embedding = vector
