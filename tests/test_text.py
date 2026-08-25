"""Drawing anchored strings."""

import pytest
from reportlab.pdfgen import canvas

from reportlab_layout.text import TextPainter


@pytest.fixture
def painter(tmp_path, stylesheet):
    return TextPainter(canvas.Canvas(str(tmp_path / "text.pdf")), stylesheet)


class TestTextPainter:
    def test_left_baseline_anchor_is_the_drawing_origin(self, painter):
        box = painter.draw("Hello", 100, 200)
        metrics = painter.metrics(None)
        assert box.x == pytest.approx(100)
        assert box.y == pytest.approx(200 + metrics.descent)

    def test_centre_anchor_centres_horizontally(self, painter):
        box = painter.draw("Hello", 100, 200, halign="center")
        assert box.center[0] == pytest.approx(100)

    def test_middle_anchor_centres_vertically(self, painter):
        box = painter.draw("Hello", 100, 200, valign="middle")
        assert box.center[1] == pytest.approx(200)

    def test_centring_holds_at_reduced_scale(self, painter):
        """The historical bug: the metrics ignored the drawing scale."""
        box = painter.draw("Hello", 100, 200, halign="center", valign="middle", scale=0.4)
        assert box.center == pytest.approx((100, 200))

    def test_scale_shrinks_the_box(self, painter):
        full = painter.draw("Hello", 0, 0)
        half = painter.draw("Hello", 0, 0, scale=0.5)
        assert half.width == pytest.approx(full.width / 2)

    def test_offsets_shift_after_anchoring(self, painter):
        plain = painter.draw("Hello", 100, 200)
        shifted = painter.draw("Hello", 100, 200, dx=7, dy=-3)
        assert (shifted.x - plain.x, shifted.y - plain.y) == pytest.approx((7, -3))

    def test_rotation_restores_the_canvas_state(self, painter):
        painter.draw("Hello", 100, 200, angle=90)
        assert painter._canvas._currentMatrix == pytest.approx((1, 0, 0, 1, 0, 0))

    def test_colour_does_not_leak_to_the_next_draw(self, painter):
        before = painter._canvas._fillColorObj
        painter.draw("Hello", 0, 0, color=(1, 0, 0))
        assert painter._canvas._fillColorObj == before

    def test_named_style_is_resolved(self, painter, stylesheet):
        box = painter.draw("Hello", 0, 0, style="Small")
        assert box.width == pytest.approx(painter.metrics("Small").width("Hello"))
