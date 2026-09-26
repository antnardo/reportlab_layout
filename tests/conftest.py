"""Shared fixtures."""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader
from reportlab.lib.styles import StyleSheet1

from reportlab_layout import PDFMaker, make_stylesheet

#: Resolution of the ink measurements. A pixel is 0.06 pt: the edges of the ink
#: are known to that, and its middle to half as much.
INK_DPI = 1200


@pytest.fixture
def stylesheet() -> StyleSheet1:
    """A fresh stylesheet, isolated from the other tests."""
    return make_stylesheet()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "output.pdf"


@pytest.fixture
def doc(out: Path, stylesheet: StyleSheet1) -> PDFMaker:
    return PDFMaker(out, stylesheet=stylesheet)


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    """A flat red 200x100 pixel image."""
    path = tmp_path / "image.png"
    PILImage.new("RGB", (200, 100), (255, 0, 0)).save(path)
    return path


@pytest.fixture
def ink(tmp_path: Path) -> Callable[[Path], tuple[float, float]]:
    """Measure where the ink of a PDF's first page lands, by rasterising it.

    Gives a function that returns the ``(bottom, top)`` of the ink, as canvas
    ordinates in points. The ink is what the eye centres: it checks the
    placement and the font metrics together, where reading positions back out
    of the PDF only checks the arithmetic. Needs ``pdftoppm`` (poppler), which
    renders the standard fonts with whatever clone the system has; the
    measurements in the documentation were made with the same tool.
    """
    if shutil.which("pdftoppm") is None:
        pytest.skip("pdftoppm (poppler) is not installed")

    def measure(path: Path) -> tuple[float, float]:
        stem = tmp_path / f"{path.stem}-ink"
        command = ["pdftoppm", "-r", str(INK_DPI), "-gray", "-singlefile", str(path), str(stem)]
        subprocess.run(command, check=True, capture_output=True)
        with PILImage.open(stem.with_suffix(".pgm")) as page:
            _, top, _, bottom = page.point(lambda value: 255 if value <= 250 else 0).getbbox()
        page_height = float(PdfReader(path).pages[0].mediabox.height)
        scale = INK_DPI / 72
        return page_height - bottom / scale, page_height - top / scale

    return measure


def fill_rgb(canvas) -> tuple[float, float, float]:
    """The canvas fill colour as a plain RGB triple.

    reportlab stores a tuple for ``setFillColorRGB`` and a ``Color`` for
    ``setFillColor``; this hides the difference.
    """
    fill = canvas._fillColorObj
    return tuple(fill) if isinstance(fill, tuple) else fill.rgb()
