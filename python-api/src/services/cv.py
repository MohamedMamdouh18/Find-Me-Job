import hashlib


def docx_text(doc) -> str:
    """python-docx keeps table cells out of `doc.paragraphs`, and CVs routinely put
    skills and dates in tables, so reading paragraphs alone silently drops them."""
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts)


_docx_text = docx_text


def cv_text_hash(cv_text: str) -> str:
    """The identity of a CV's content. Keywords are stored against it, so the pipeline
    and a manual keyword edit must hash the same way or the edit is re-extracted over."""
    return hashlib.sha256(cv_text.encode("utf-8")).hexdigest()
