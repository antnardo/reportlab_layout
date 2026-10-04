"""Shared fixtures."""

import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

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
def doc(out: Path, stylesheet: StyleSheet1) -> Iterator[PDFMaker]:
    document = PDFMaker(out, stylesheet=stylesheet)
    yield document
    # A PDFMaker holds reportlab's process-wide ASCII85 switch while it is open,
    # and pytest keeps a fixture's value alive until after teardown: a document
    # the test never saved has to give the switch back here.
    document._release_ascii85()


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    """A flat red 200x100 pixel image."""
    path = tmp_path / "image.png"
    PILImage.new("RGB", (200, 100), (255, 0, 0)).save(path)
    return path


class Ink(NamedTuple):
    """The bounding box of the ink on a page, as canvas coordinates in points."""

    left: float
    bottom: float
    right: float
    top: float


@pytest.fixture
def ink(tmp_path: Path) -> Callable[..., Ink | None]:
    """Measure where the ink of a PDF page lands, by rasterising it.

    Gives a function ``measure(path, page=1, dpi=INK_DPI)`` that returns the
    ``Ink`` of that page, or ``None`` when nothing is drawn on it. The ink is
    what the eye sees: it checks the placement and the font metrics together,
    where reading positions back out of the PDF only checks the arithmetic.
    Needs ``pdftoppm`` (poppler), which draws the standard fonts with what the
    system has: Apple's own on macOS, where the measurements in the
    documentation were made, and the URW clones on Linux.

    A whole page at 1200 dpi is a 140-megapixel image: measure the edges of a
    page-sized layout at a lower ``dpi``, whose pixel is ``72 / dpi`` points.
    """
    if shutil.which("pdftoppm") is None:
        pytest.skip("pdftoppm (poppler) is not installed")

    def measure(path: Path, page: int = 1, dpi: int = INK_DPI) -> Ink | None:
        stem = tmp_path / f"{path.stem}-{page}-ink"
        pages = ["-f", str(page), "-l", str(page)]
        command = ["pdftoppm", "-r", str(dpi), "-gray", *pages, "-singlefile", str(path), str(stem)]
        subprocess.run(command, check=True, capture_output=True)
        with PILImage.open(stem.with_suffix(".pgm")) as image:
            box = image.point(lambda value: 255 if value <= 250 else 0).getbbox()
        if box is None:
            return None
        left, top, right, bottom = box
        page_height = float(PdfReader(path).pages[page - 1].mediabox.height)
        scale = dpi / 72
        return Ink(left / scale, page_height - bottom / scale, right / scale, page_height - top / scale)

    return measure


def fill_rgb(canvas) -> tuple[float, float, float]:
    """The canvas fill colour as a plain RGB triple.

    reportlab stores a tuple for ``setFillColorRGB`` and a ``Color`` for
    ``setFillColor``; this hides the difference.
    """
    fill = canvas._fillColorObj
    return tuple(fill) if isinstance(fill, tuple) else fill.rgb()


@pytest.fixture(autouse=True)
def _ascii85_switch_released():
    """No test may leave reportlab's process-wide ASCII85 switch held.

    Every PDFMaker holds it off while open, since ascii85=False is the default.
    A document still referenced after its test would make the next test's PDFs
    binary whatever it asked for, and hide a release that never happens. No
    garbage collection is needed: a PDFMaker holds no reference cycle, so one
    that goes out of scope is freed, and its hold released, at once.
    """
    from reportlab import rl_config

    from reportlab_layout.document import _Ascii85Switch

    before = rl_config.useA85
    yield
    assert _Ascii85Switch._holders == 0, "a test left a PDFMaker open"
    assert rl_config.useA85 == before, "a test left rl_config.useA85 changed"
