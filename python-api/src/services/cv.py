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
