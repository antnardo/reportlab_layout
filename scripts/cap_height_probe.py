"""Vérifie les hauteurs de capitale par rastérisation.

reportlab n'expose pas la hauteur de capitale des polices PostScript standard.
:data:`reportlab_layout.metrics.STANDARD_CAP_HEIGHTS` la reprend de leurs
fichiers AFM ; ce script la remesure sur le rendu réel pour contrôler la table.

    uv run python scripts/cap_height_probe.py

Demande ``pdftoppm`` (poppler) sur le PATH.

Lecture des résultats : poppler ne possède pas les polices Adobe et leur
substitue les clones URW. Ceux-ci sont compatibles en **chasse**, pas forcément
en hauteur de capitale. Helvetica tombe à 0,4 ‰ et Times-Roman à 1,2 ‰ de la
table, ce qui la valide ; Courier (+18 ‰) et les variantes de Times affichent
l'écart du clone, pas une erreur de la table — poppler rend d'ailleurs les
quatre Times avec la même valeur, signe qu'il substitue une seule fonte.
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
    """Rend ``text`` et mesure l'encre, en millièmes de cadratin au-dessus de la ligne de base."""
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
        print(f"{'police':<24} {'table':>7} {'mesuré':>8} {'écart':>8}")
        for font, published in STANDARD_CAP_HEIGHTS.items():
            measured, _ = measure(font, "H", folder)
            gap = measured - published
            worst = max(worst, abs(gap))
            print(f"{font:<24} {published:>7} {measured:>8.1f} {gap:>+8.1f}")
    print(f"\nÉcart maximal : {worst:.1f} ‰ de cadratin (voir l'en-tête du script)")
    return 0 if worst < 25 else 1


if __name__ == "__main__":
    sys.exit(main())
