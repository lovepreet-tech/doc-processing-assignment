"""Parses a plain-text or Markdown file into DocumentBlock rows.

Markdown headings (`#`..`######`) become `heading` blocks and set the section
breadcrumb for subsequent blocks. Everything else is split into paragraphs on
blank lines.
"""

from core.models import DocumentBlock

MAX_SECTION_PATH_LENGTH = 255


def parse_text(db, file) -> list[DocumentBlock]:
    from storage.object_store import read

    data = read(file.storage_uri)
    text = data.decode("utf-8", errors="replace")

    blocks: list[DocumentBlock] = []
    reading_order = 0
    section_path = None

    for raw_paragraph in _split_paragraphs(text):
        heading_text = _as_heading(raw_paragraph)
        block_type = "heading" if heading_text is not None else "paragraph"
        block_text = heading_text if heading_text is not None else raw_paragraph

        block = DocumentBlock(
            file_id=file.id,
            tenant_id=file.tenant_id,
            page_number=None,
            block_type=block_type,
            bbox=None,
            text=block_text,
            table_data=None,
            reading_order=reading_order,
            ocr_confidence=None,
            needs_vlm_review=False,
            source_section_path=section_path,
        )
        db.add(block)
        blocks.append(block)
        reading_order += 1

        if block_type == "heading":
            section_path = block_text.strip()[:MAX_SECTION_PATH_LENGTH]

    db.flush()  # get block.id's assigned before embed_chunks needs them
    return blocks


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return [p for p in paragraphs if p]


def _as_heading(paragraph: str) -> str | None:
    # only a single-line "# Heading" counts - a multi-line paragraph that merely
    # starts with '#' (e.g. a hashtag list) isn't a markdown heading
    if "\n" in paragraph:
        return None
    stripped = paragraph.lstrip("#")
    hashes = len(paragraph) - len(stripped)
    if 1 <= hashes <= 6 and stripped.startswith(" "):
        return stripped.strip()
    return None
