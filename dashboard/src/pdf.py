import os

from fpdf import FPDF

SENDER_NAME = os.getenv("SENDER_NAME", "")
SENDER_EMAIL = os.getenv("SMTP_USER", "")


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

    if SENDER_NAME or SENDER_EMAIL:
        if SENDER_NAME:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, sanitize(SENDER_NAME), new_x="LMARGIN", new_y="NEXT")
        if SENDER_EMAIL:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, sanitize(SENDER_EMAIL), new_x="LMARGIN", new_y="NEXT")
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
