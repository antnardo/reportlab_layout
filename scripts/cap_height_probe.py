"""Check the cap-height table by rasterisation.

reportlab does not expose the cap height of the standard PostScript fonts.
:data:`reportlab_layout.metrics.STANDARD_CAP_HEIGHTS` takes it from their AFM
files; this script measures it again on the actual rendering to check the table.

    uv run python scripts/cap_height_probe.py

Needs ``pdftoppm`` (poppler) on the PATH.

Reading the results: poppler does not have the Adobe fonts and substitutes the
URW clones. Those match in **advance width**, not necessarily in cap height.
Helvetica lands within 0.4 per mille of the table and Times-Roman within 1.2,
which validates it; Courier (+18) and the Times variants show the clone's
deviation, not an error in the table -- poppler in fact renders all four Times
faces with the same value, which means it substitutes a single font.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from reportlab.pdfgen import canvas

from reportlab_layout.metrics import STANDARD_CAP_HEIGHTS

DPI = 600
SIZE = 100.0
BASELINE = 200.0
PAGE = (900, 400)


def measure(font: str, text: str, folder: Path) -> tuple[float, float]:
    """Render ``text`` and measure the ink, in thousandths of an em above the baseline."""
    pdf = folder / "probe.pdf"
    stem = folder / "probe"
    page = canvas.Canvas(str(pdf), pagesize=PAGE)
    page.setFont(font, SIZE)
    page.drawString(50, BASELINE, text)
    page.save()
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-png", "-singlefile", "-gray", str(pdf), str(stem)],
        check=True,
        capture_output=True,
    )
    image = Image.open(stem.with_suffix(".png"))
    scale = DPI / 72.0
    _, top, _, bottom = image.point(lambda v: 0 if v > 250 else 255).getbbox()
    return (
        (PAGE[1] - top / scale - BASELINE) / SIZE * 1000,
        (PAGE[1] - bottom / scale - BASELINE) / SIZE * 1000,
    )


def main() -> int:
    worst = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        print(f"{'font':<24} {'table':>7} {'measured':>9} {'gap':>7}")
        for font, published in STANDARD_CAP_HEIGHTS.items():
            measured, _ = measure(font, "H", folder)
            gap = measured - published
            worst = max(worst, abs(gap))
            print(f"{font:<24} {published:>7} {measured:>9.1f} {gap:>+7.1f}")
    print(f"\nLargest gap: {worst:.1f} per mille of an em (see the module docstring)")
    return 0 if worst < 25 else 1


if __name__ == "__main__":
    sys.exit(main())
