"""Une attestation d'une page : en-tête, corps en flux, encadré, pied de page.

    uv run python examples/attestation.py

Produit ``attestation.pdf`` dans le répertoire courant.
"""

from datetime import date
from pathlib import Path

from reportlab.lib.units import mm

from reportlab_layout import PDFMaker, add_style, make_stylesheet

styles = make_stylesheet()
add_style(styles, "Titre", parent="Heading1 Centered", fontSize=20, leading=24)
add_style(styles, "Mention", parent="Small", textColor="#555555")


def build(path: Path) -> Path:
    with PDFMaker(path, stylesheet=styles, top=25, bottom=20, auto_page_break=True) as doc:
        doc.set_metadata(author="Service scolarité", title="Attestation")
        doc.set_footer(doc.make_paragraph(f"Émis le {date.today():%d/%m/%Y}", "Right"))

        doc.draw_paragraph("Attestation de scolarité", "Titre")
        doc.draw_centered_line(wscale=0.4)
        doc.add_space(2)

        doc.draw_paragraph(
            "Je soussigné, chef d'établissement, atteste que l'élève dont le nom figure "
            "ci-dessous est régulièrement inscrit pour l'année scolaire en cours.",
            "Justify",
        )
        doc.add_space()

        doc.draw_table(
            [
                ["Nom", "HOPPER"],
                ["Prénom", "Grace"],
                ["Classe", "MP2"],
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

        # Un cartouche placé au point près : le canvas reste accessible.
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
        doc.draw_string(
            "Document sans valeur légale",
            *(doc.x_left + doc.content_width / 2, top - box_height / 2),
            style="Heading2",
            halign="center",
            valign="middle",
            color="#3b6ea5",
        )
        doc.advance(box_height)
        doc.add_space()

        doc.draw_paragraph(
            "Toute rature rend le présent document nul. Il ne peut être reproduit qu'intégralement.",
            "Mention",
        )
    return path


if __name__ == "__main__":
    print(build(Path("attestation.pdf")))
