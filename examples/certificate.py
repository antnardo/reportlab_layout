"""A one-page certificate: header, flowing body, callout box, footer.

    uv run python examples/certificate.py

Writes ``certificate.pdf`` into the current directory.
"""

from datetime import date
from pathlib import Path

from reportlab.lib.units import mm

from reportlab_layout import PDFMaker, add_style, make_stylesheet

styles = make_stylesheet()
add_style(styles, "Banner", parent="Heading1 Centered", fontSize=20, leading=24)
add_style(styles, "Fineprint", parent="Small", textColor="#555555")


def build(path: Path) -> Path:
    with PDFMaker(path, stylesheet=styles, top=25, bottom=20, auto_page_break=True) as doc:
        doc.set_metadata(author="Registrar's office", title="Certificate of enrolment")
        doc.set_footer(doc.make_paragraph(f"Issued {date.today():%d %B %Y}", "Right"))

        doc.draw_paragraph("Certificate of enrolment", "Banner")
        doc.draw_centered_line(wscale=0.4)
        doc.add_space(2)

        doc.draw_paragraph(
            "The undersigned head of school certifies that the student named below is "
            "duly enrolled for the current academic year.",
            "Justify",
        )
        doc.add_space()

        doc.draw_table(
            [
                ["Surname", "HOPPER"],
                ["First name", "Grace"],
                ["Class", "MP2"],
            ],
            col_widths=[40 * mm, doc.content_width - 40 * mm],
            style=[
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, "#999999"),
                ("BACKGROUND", (0, 0), (0, -1), "#f2f2f2"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ],
        )
        doc.add_space(2)

        # A callout placed to the point: the canvas stays within reach.
        box_height = 26 * mm
        top = doc.geometry.depth_to_y(doc.cursor.depth)
        doc.draw_round_rect(
            doc.x_left,
            top - box_height,
            doc.content_width,
            box_height,
            radius=6,
            fill="#eef4fb",
            stroke="#3b6ea5",
        )
        # A short label centred in a box: "cap", not "middle".
        doc.draw_string(
            "Not a legal document",
            doc.x_left + doc.content_width / 2,
            top - box_height / 2,
            style="Heading2",
            halign="center",
            valign="cap",
            color="#3b6ea5",
        )
        doc.advance(box_height)
        doc.add_space()

        doc.draw_paragraph(
            "Any alteration voids this document. It may only be reproduced in full.",
            "Fineprint",
        )
    return path


if __name__ == "__main__":
    print(build(Path("certificate.pdf")))
