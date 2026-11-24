"""Parses a PDF (native or scanned) into DocumentBlock rows using PyMuPDF, with
heuristic heading/table detection off its text blocks.

A page with no extractable native text is OCR'd (pytesseract); if OCR isn't
available or finds nothing, the page gets a low-confidence stub block instead
of being dropped.
"""

import io

import fitz  # PyMuPDF

from core.models import DocumentBlock

# body text is usually ~10-12pt - anything noticeably bigger we call a heading
HEADING_SIZE_THRESHOLD = 13.5
SCAN_STUB_OCR_CONFIDENCE = 0.2
OCR_DPI = 300
# below this (0-1 scale), the OCR text is kept (still useful for retrieval) but
# flagged for VLM/human review rather than trusted outright
OCR_LOW_CONFIDENCE_THRESHOLD = 0.6


def parse_pdf(db, file) -> list[DocumentBlock]:
    """Reads the file off disk, extracts blocks per page, persists them, returns the rows."""
    from storage.object_store import read

    data = read(file.storage_uri)
    doc = fitz.open(stream=data, filetype="pdf")

    blocks: list[DocumentBlock] = []
    reading_order = 0
    section_path = None  # last seen heading, used as breadcrumb for subsequent blocks

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_dict = page.get_text("dict")
        page_spans = list(_iter_spans(page_dict))

        if not page_spans:
            # no extractable native text at all - this is a scanned page, OCR it
            ocr_text, ocr_confidence = _ocr_page(page)
            if ocr_text:
                block = DocumentBlock(
                    file_id=file.id,
                    tenant_id=file.tenant_id,
                    page_number=page_index + 1,
                    block_type="ocr_text",
                    bbox=list(page.rect),
                    text=ocr_text,
                    table_data=None,
                    reading_order=reading_order,
                    ocr_confidence=ocr_confidence,
                    needs_vlm_review=(ocr_confidence is None or ocr_confidence < OCR_LOW_CONFIDENCE_THRESHOLD),
                    source_section_path=section_path,
                )
            else:
                # OCR unavailable or found nothing: stub the page rather than drop it
                block = DocumentBlock(
                    file_id=file.id,
                    tenant_id=file.tenant_id,
                    page_number=page_index + 1,
                    block_type="scanned_page",
                    bbox=list(page.rect),
                    text=None,
                    table_data=None,
                    reading_order=reading_order,
                    ocr_confidence=SCAN_STUB_OCR_CONFIDENCE,
                    needs_vlm_review=True,
                    source_section_path=section_path,
                )
            db.add(block)
            blocks.append(block)
            reading_order += 1
            continue

        for span_text, bbox, max_size, is_table_like in page_spans:
            block_type = "heading" if max_size >= HEADING_SIZE_THRESHOLD else "paragraph"
            table_data = None

            if is_table_like:
                block_type = "table"
                table_data = _rows_from_text(span_text)

            block = DocumentBlock(
                file_id=file.id,
                tenant_id=file.tenant_id,
                page_number=page_index + 1,
                block_type=block_type,
                bbox=list(bbox),
                text=span_text,
                table_data=table_data,
                reading_order=reading_order,
                ocr_confidence=None,  # native text, not OCR'd
                needs_vlm_review=False,
                source_section_path=section_path,
            )
            db.add(block)
            blocks.append(block)
            reading_order += 1

            if block_type == "heading":
                section_path = span_text.strip()[:255]

    doc.close()
    db.flush()  # get block.id's assigned before embed_chunks needs them
    return blocks


def _ocr_page(page) -> tuple[str | None, float | None]:
    """Best-effort OCR for a page with no extractable native text. Returns
    (text, confidence 0-1); either may be None if pytesseract isn't installed,
    rendering fails, or OCR finds nothing."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return None, None

    try:
        pixmap = page.get_pixmap(dpi=OCR_DPI)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        text = pytesseract.image_to_string(image).strip()
        if not text:
            return None, None
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
        confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else None
        return text, confidence
    except Exception:
        return None, None


def _iter_spans(page_dict):
    """Yields (text, bbox, max_font_size, looks_like_table) per text block on the page."""
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue  # skip image blocks

        lines = block.get("lines", [])
        texts = []
        max_size = 0.0
        numeric_lines = 0

        for line in lines:
            line_text_parts = []
            for span in line.get("spans", []):
                line_text_parts.append(span.get("text", ""))
                max_size = max(max_size, span.get("size", 0.0))
            line_text = "".join(line_text_parts)
            if line_text.strip():
                texts.append(line_text)
                # crude table heuristic: lots of digits/short tokens per line
                tokens = line_text.split()
                if tokens and sum(1 for t in tokens if _looks_numeric(t)) >= max(2, len(tokens) // 2):
                    numeric_lines += 1

        full_text = "\n".join(texts).strip()
        if not full_text:
            continue

        looks_like_table = len(lines) >= 3 and numeric_lines >= max(2, len(lines) // 2)
        yield full_text, block.get("bbox", [0, 0, 0, 0]), max_size, looks_like_table


def _looks_numeric(token: str) -> bool:
    cleaned = token.strip("$%,()").replace(",", "")
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _rows_from_text(text: str) -> dict:
    """Naive table serialization: one row per line, cells split on runs of whitespace."""
    rows = []
    for line in text.split("\n"):
        cells = [c for c in line.split() if c]
        if cells:
            rows.append(cells)
    return {"rows": rows}
