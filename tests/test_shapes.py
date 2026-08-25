"""Geometric primitives."""

import pytest
from reportlab.pdfgen import canvas

from reportlab_layout.colors import to_color
from reportlab_layout.shapes import ShapePainter


@pytest.fixture
def painter(tmp_path):
    return ShapePainter(canvas.Canvas(str(tmp_path / "shapes.pdf")))


class TestShapePainter:
    def test_line_returns_its_bounding_box(self, painter):
        box = painter.line(10, 20, 40, 60)
        assert tuple(box) == pytest.approx((10, 20, 30, 40))

    def test_rect_returns_the_requested_box(self, painter):
        assert tuple(painter.rect(5, 5, 100, 50)) == pytest.approx((5, 5, 100, 50))

    def test_round_rect_clamps_an_oversized_radius(self, painter):
        """A radius larger than half the side folds the path back on itself."""
        assert tuple(painter.round_rect(0, 0, 20, 10, radius=50)) == pytest.approx((0, 0, 20, 10))

    def test_drawing_does_not_leak_the_stroke_colour(self, painter):
        before = painter._canvas._strokeColorObj
        painter.rect(0, 0, 10, 10, stroke=(1, 0, 0))
        assert painter._canvas._strokeColorObj == before

    def test_drawing_does_not_leak_the_line_width(self, painter):
        before = painter._canvas._lineWidth
        painter.rect(0, 0, 10, 10, line_width=8)
        assert painter._canvas._lineWidth == before


class TestToColor:
    def test_triplet(self):
        assert to_color((1, 0, 0)).rgb() == (1, 0, 0)

    def test_hex_string(self):
        assert to_color("#00ff00").rgb() == (0, 1, 0)

    def test_css_name(self):
        assert to_color("blue").rgb() == (0, 0, 1)

    def test_alpha_quadruplet(self):
        assert to_color((0, 0, 0, 0.5)).alpha == pytest.approx(0.5)

    def test_none_passes_through(self):
        assert to_color(None) is None

    def test_wrong_length_tuple_is_rejected(self):
        with pytest.raises(ValueError, match="3 or 4"):
            to_color((1, 2))
