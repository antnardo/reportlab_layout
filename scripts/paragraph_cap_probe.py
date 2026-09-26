"""Measure by rasterisation where a centred paragraph's capitals land.

``valign="middle"`` centres a paragraph's block, ``valign="cap"`` its capitals:
from the cap height of the first line down to the baseline of the last. This
script centres the same paragraph both ways on a page, renders the page, and
measures how far the middle of the ink lands from the target, for several fonts
and leadings.

    uv run python scripts/paragraph_cap_probe.py

Needs ``pdftoppm`` (poppler) on the PATH.

Reading the results: the text is in capitals that neither overshoot nor
descend, so its ink runs exactly from the last baseline to the cap height of
the first line, and ``cap`` should land on the target to the resolution of the
measurement, 0.015 pt. The ``predicted`` column is the gap the rule works out
for ``middle``: ``(leading + cap height) / 2 - size``, negative when the
capitals sit low. The last row, in lower case, shows what descenders do: they
pull the ink down, and ``cap`` leaves them out on purpose, as it does for a
label.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle

from reportlab_layout import PDFMaker, TextMetrics

DPI = 2400
PAGE = (250, 120)
CAPITALS = "THE FILM KIT HELIX TIME EXIT MYTH ITEM LIFE THEME TILE"
LOWER_CASE = "Please be wrapped, centered horizontally and vertically!!"
CASES = [
    ("Helvetica", 15, 15, CAPITALS),
    ("Helvetica", 10, 12, CAPITALS),
    ("Helvetica", 12, 18, CAPITALS),
    ("Helvetica", 11, 9, CAPITALS),
    ("Helvetica-Bold", 20, 22, CAPITALS),
    ("Times-Roman", 14, 14, CAPITALS),
    ("Times-Roman", 12, 16, CAPITALS),
    ("Helvetica", 15, 15, LOWER_CASE),
]


def centre(pdf: Path, style: ParagraphStyle, text: str, valign: str) -> int:
    """Centre ``text`` on the middle of the page, and return its number of lines."""
    with PDFMaker(pdf, pagesize=PAGE, unit=1, left=10, right=10, top=5, bottom=5) as doc:
        box = doc.draw_paragraph(
            text,
            style,
            x=doc.x_left,
            y=PAGE[1] / 2,
            width=doc.content_width,
            absolute=True,
            valign=valign,
        )
    return round(box.height / style.leading)


def ink_middle(pdf: Path) -> float:
    """Canvas ordinate of the middle of the ink, in points."""
    stem = pdf.with_suffix("")
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-gray", "-singlefile", str(pdf), str(stem)],
        check=True,
        capture_output=True,
    )
    with Image.open(stem.with_suffix(".pgm")) as image:
        _, top, _, bottom = image.point(lambda value: 255 if value <= 250 else 0).getbbox()
    return PAGE[1] - (top + bottom) / 2 / (DPI / 72)


def main() -> int:
    worst = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "probe.pdf"
        print(f"{'style':<32} {'lines':>5} {'middle':>8} {'cap':>8} {'predicted':>10}")
        for font, size, leading, text in CASES:
            style = ParagraphStyle(
                "probe", fontName=font, fontSize=size, leading=leading, alignment=TA_CENTER
            )
            errors = {}
            for valign in ("middle", "cap"):
                lines = centre(pdf, style, text, valign)
                errors[valign] = ink_middle(pdf) - PAGE[1] / 2
            if text is CAPITALS:
                worst = max(worst, abs(errors["cap"]))
            predicted = (leading + TextMetrics(style).cap_height) / 2 - size
            label = f"{font} {size}/{leading}" + ("" if text is CAPITALS else ", lower case")
            print(
                f"{label:<32} {lines:>5} {errors['middle']:>+8.2f} {errors['cap']:>+8.2f} {predicted:>+10.2f}"
            )
    print(f"\nLargest error of cap on capitals: {worst:.3f} pt")
    return 0 if worst < 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
