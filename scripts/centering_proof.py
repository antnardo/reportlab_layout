"""Visual and numeric proof of vertical text centring.

Draws the same string in a box three ways: with the formula this package used to
get wrong (``y - height/2``), with ``valign="middle"`` (em box), and with
``valign="cap"`` (cap box). Each box is ruled through its exact middle, so you
can see where the ink actually lands.

    uv run python scripts/centering_proof.py

To regenerate the figure used by the documentation::

    pdftoppm -r 200 -png -singlefile centering.pdf docs/img/centering
"""

from pathlib import Path

from reportlab.lib.units import mm

from reportlab_layout import PDFMaker, make_stylesheet
from reportlab_layout.metrics import TextMetrics

BOX = (52 * mm, 15 * mm)
COLUMNS = [
    ("old formula", None),
    ('valign="middle"', "middle"),
    ('valign="cap"', "cap"),
]
ROWS = [
    ("Hxpg 24", 1.0, "with descenders"),
    ("ITEM 24", 0.6, "no descenders, 0.6 scale"),
]


def build(path: Path) -> Path:
    styles = make_stylesheet()
    doc = PDFMaker(path, stylesheet=styles, pagesize=(200 * mm, 78 * mm), left=10, top=10)
    style = styles["Heading2"]

    for row, (text, scale, note) in enumerate(ROWS):
        y_center = doc.height - 24 * mm - row * 28 * mm
        for column, (legend, valign) in enumerate(COLUMNS):
            x = doc.x_left + column * 58 * mm
            doc.draw_rect(x, y_center - BOX[1] / 2, *BOX, stroke="#bbbbbb")
            doc.draw_line(x, y_center, x + BOX[0], y_center, stroke="#e05252", line_width=0.4)
            if valign is None:
                # What the original code did: an offset of height/2, with the
                # metrics read at the nominal size whatever the drawing scale.
                nominal = TextMetrics(style, 1.0)
                doc.apply_style(style, scale)
                doc.canvas.drawString(
                    x + BOX[0] / 2 - nominal.width(text) / 2,
                    y_center - nominal.height / 2,
                    text,
                )
            else:
                doc.draw_string(
                    text,
                    x + BOX[0] / 2,
                    y_center,
                    style=style,
                    scale=scale,
                    halign="center",
                    valign=valign,
                )
            doc.draw_string(legend, x, y_center - BOX[1] / 2 - 4.5 * mm, style="Small", color="#777777")
        doc.draw_string(
            note,
            doc.x_left,
            y_center + BOX[1] / 2 + 2.5 * mm,
            style="Small",
            scale=0.9,
            color="#999999",
        )

    metrics = TextMetrics(style)
    print(f"{'anchor':<16} {'baseline offset':>16} {'vs old formula':>16}")
    old = metrics.height / 2
    print(f"{'old formula':<16} {old:>15.2f}p {0.0:>15.2f}p")
    for name, offset in (("middle", metrics.baseline_offset), ("cap", metrics.cap_offset)):
        print(f"{name:<16} {offset:>15.2f}p {old - offset:>+15.2f}p")

    doc.save()
    return path


if __name__ == "__main__":
    print(build(Path("centering.pdf")))
