from fpdf import FPDF

import library


def sanitize(text: str) -> str:
    replacements = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
        "\u2022": "-", "\u200b": "",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf(text: str, title: str, company: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # The sender is a setting now, so it is read per build rather than from this
    # container's environment — editing it in Settings changes the next PDF.
    app_settings = library.settings()
    sender_name = app_settings.get("SENDER_NAME") or ""
    sender_email = app_settings.get("SMTP_USER") or ""

    if sender_name or sender_email:
        if sender_name:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, sanitize(sender_name), new_x="LMARGIN", new_y="NEXT")
        if sender_email:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, sanitize(sender_email), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, sanitize(f"{title} - {company}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, sanitize(text))

    return bytes(pdf.output())
