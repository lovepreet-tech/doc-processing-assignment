"""Parses a Word (.docx) file into DocumentBlock rows.

Walks the document body in true reading order (paragraphs interleaved with
tables, not all paragraphs then all tables) so section headings still apply to
the right blocks. A paragraph using a "Heading" style becomes a `heading`
block and sets the section breadcrumb for what follows; a table becomes one
`table` block with its rows in `table_data`; everything else is a `paragraph`
block, skipping blank paragraphs.
"""

import io

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from core.models import DocumentBlock

MAX_SECTION_PATH_LENGTH = 255


def parse_docx(db, file) -> list[DocumentBlock]:
    from storage.object_store import read

    data = read(file.storage_uri)
    document = Document(io.BytesIO(data))

    blocks: list[DocumentBlock] = []
    reading_order = 0
    section_path = None

    for item in _iter_block_items(document):
        if isinstance(item, Table):
            table_data = _rows_from_table(item)
            if not table_data["rows"]:
                continue
            block = DocumentBlock(
                file_id=file.id,
                tenant_id=file.tenant_id,
                page_number=None,
                block_type="table",
                bbox=None,
                text="\n".join(" ".join(row) for row in table_data["rows"]),
                table_data=table_data,
                reading_order=reading_order,
                ocr_confidence=None,
                needs_vlm_review=False,
                source_section_path=section_path,
            )
            db.add(block)
            blocks.append(block)
            reading_order += 1
            continue

        paragraph_text = item.text.strip()
        if not paragraph_text:
            continue

        is_heading = item.style is not None and item.style.name.lower().startswith("heading")
        block_type = "heading" if is_heading else "paragraph"

        block = DocumentBlock(
            file_id=file.id,
            tenant_id=file.tenant_id,
            page_number=None,
            block_type=block_type,
            bbox=None,
            text=paragraph_text,
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
            section_path = paragraph_text[:MAX_SECTION_PATH_LENGTH]

    db.flush()  # get block.id's assigned before embed_chunks needs them
    return blocks


def _rows_from_table(table: Table) -> dict:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            rows.append(cells)
    return {"rows": rows}


def _iter_block_items(document: Document):
    """Yields each top-level Paragraph/Table in the body in true document order.

    python-docx exposes .paragraphs and .tables as two separate flat lists with
    no shared ordering, so reading them one after the other would silently move
    every table to the end of the document regardless of where it actually sits
    - this walks the underlying XML body instead to preserve real order.
    """
    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)
