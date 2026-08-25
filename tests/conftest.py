"""Shared fixtures."""

from pathlib import Path

import pytest
from PIL import Image as PILImage
from reportlab.lib.styles import StyleSheet1

from reportlab_layout import PDFMaker, make_stylesheet


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


def fill_rgb(canvas) -> tuple[float, float, float]:
    """The canvas fill colour as a plain RGB triple.

    reportlab stores a tuple for ``setFillColorRGB`` and a ``Color`` for
    ``setFillColor``; this hides the difference.
    """
    fill = canvas._fillColorObj
    return tuple(fill) if isinstance(fill, tuple) else fill.rgb()
