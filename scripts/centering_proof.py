"""Preuve visuelle et chiffrée du centrage vertical du texte.

Trace la même chaîne dans une case, une fois avec l'ancienne formule
(``y - hauteur/2``) et une fois avec l'ancrage ``valign="middle"`` du paquet.
La case est barrée en son milieu : le texte correct doit être coupé au tiers
supérieur des minuscules, pas plus bas.

    uv run python scripts/centering_proof.py
"""

from pathlib import Path

from reportlab.lib.units import mm

from reportlab_layout import PDFMaker, make_stylesheet
from reportlab_layout.metrics import TextMetrics

TEXT = "Hxpg 24"
CASE = (60 * mm, 16 * mm)


def build(path: Path) -> Path:
    styles = make_stylesheet()
    doc = PDFMaker(path, stylesheet=styles, pagesize=(150 * mm, 80 * mm), left=10, top=10)
    style = styles["Heading2"]

    for row, (label, scale) in enumerate([("corps nominal", 1.0), ("corps × 0,5", 0.5)]):
        metrics = TextMetrics(style, scale)
        y_center = doc.height - 25 * mm - row * 26 * mm

        for column, legend in enumerate(["ancienne formule", "valign='middle'"]):
            x = doc.x_left + column * 65 * mm
            doc.draw_rect(x, y_center - CASE[1] / 2, *CASE, stroke="#bbbbbb")
            doc.draw_line(x, y_center, x + CASE[0], y_center, stroke="#e05252", line_width=0.4)
            if column == 0:
                # Ce que faisait le code d'origine : décalage de height/2, et
                # métriques lues au corps nominal quelle que soit l'échelle.
                nominal = TextMetrics(style, 1.0)
                doc.apply_style(style, scale)
                doc.canvas.drawString(
                    x + CASE[0] / 2 - nominal.width(TEXT) / 2,
                    y_center - nominal.height / 2,
                    TEXT,
                )
            else:
                doc.draw_string(
                    TEXT,
                    x + CASE[0] / 2,
                    y_center,
                    style=style,
                    scale=scale,
                    halign="center",
                    valign="middle",
                )
            doc.draw_string(legend, x, y_center - CASE[1] / 2 - 4 * mm, style="Small", color="#777777")

        error = metrics.height / 2 - metrics.baseline_offset
        print(f"{label:>14} : erreur verticale de l'ancienne formule = {error:6.2f} pt")

    doc.save()
    return path


if __name__ == "__main__":
    print(build(Path("centrage.pdf")))
    # Pour régénérer l'illustration de la documentation :
    #   pdftoppm -r 200 -png -singlefile centrage.pdf docs/img/centrage
