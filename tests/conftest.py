"""Fixtures partagées."""

from pathlib import Path

import pytest
from PIL import Image as PILImage
from reportlab.lib.styles import StyleSheet1

from reportlab_layout import PDFMaker, make_stylesheet


@pytest.fixture
def stylesheet() -> StyleSheet1:
    """Une feuille de styles neuve, isolée des autres tests."""
    return make_stylesheet()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "sortie.pdf"


@pytest.fixture
def doc(out: Path, stylesheet: StyleSheet1) -> PDFMaker:
    return PDFMaker(out, stylesheet=stylesheet)


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    """Une image 200x100 pixels, rouge unie."""
    path = tmp_path / "image.png"
    PILImage.new("RGB", (200, 100), (255, 0, 0)).save(path)
    return path
