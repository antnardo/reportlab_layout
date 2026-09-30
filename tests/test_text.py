"""Drawing anchored strings."""

import pytest
from reportlab.pdfgen import canvas

from conftest import fill_rgb
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


def ink_colour(painter, **kwargs) -> tuple[float, float, float]:
    """The fill colour in force at the moment the string is actually drawn.

    draw() saves and restores the canvas, so reading the colour afterwards
    would always give the colour from before the call.
    """
    canvas = painter._canvas
    captured = []
    original = canvas.drawString

    def record(*args, **kw):
        captured.append(fill_rgb(canvas))
        return original(*args, **kw)

    canvas.drawString = record
    try:
        painter.draw("Hello", 100, 200, **kwargs)
    finally:
        canvas.drawString = original
    return captured[0]


class TestDefaultColour:
    """A previous rectangle must not tint the text drawn after it."""

    def test_text_is_black_even_after_a_white_fill(self, painter):
        painter._canvas.setFillColorRGB(1, 1, 1)
        assert ink_colour(painter) == (0, 0, 0)

    def test_explicit_colour_still_wins(self, painter):
        assert ink_colour(painter, color=(1, 0, 0)) == (1, 0, 0)

    def test_colour_none_keeps_the_current_fill(self, painter):
        painter._canvas.setFillColorRGB(0, 0, 1)
        assert ink_colour(painter, color=None) == (0, 0, 1)


class TestOutline:
    """A faux bold: the glyphs are stroked as well as filled."""

    def render_mode(self, painter, **kwargs) -> int:
        """The text render mode in force when the string is drawn.

        drawString goes through a text object too, at mode 0 -- fill only.
        """
        modes = []
        original = painter._canvas.drawText

        def record(text_object):
            modes.append(text_object._textRenderMode)
            return original(text_object)

        painter._canvas.drawText = record
        painter.draw("Hello", 10, 10, **kwargs)
        return modes[0]

    def test_without_outline_the_glyphs_are_only_filled(self, painter):
        assert self.render_mode(painter) == 0

    def test_outline_selects_fill_and_stroke(self, painter):
        assert self.render_mode(painter, outline=0.4) == 2

    def test_outline_sets_the_line_width(self, painter):
        widths = []
        original = painter._canvas.drawText
        painter._canvas.drawText = lambda t: widths.append(painter._canvas._lineWidth) or original(t)
        painter.draw("Hello", 10, 10, outline=0.7)
        assert widths == [0.7]

    def test_the_stroke_takes_the_text_colour(self, painter):
        strokes = []
        original = painter._canvas.drawText
        painter._canvas.drawText = lambda t: strokes.append(fill_rgb(painter._canvas)) or original(t)
        painter.draw("Hello", 10, 10, color=(1, 0, 0), outline=0.4)
        assert strokes == [(1, 0, 0)]

    def test_the_box_stays_the_metric_box(self, painter):
        plain = painter.draw("Hello", 10, 10)
        bold = painter.draw("Hello", 10, 10, outline=0.6)
        assert tuple(bold) == pytest.approx(tuple(plain))

    def test_outline_does_not_leak_the_line_width(self, painter):
        before = painter._canvas._lineWidth
        painter.draw("Hello", 10, 10, outline=0.6)
        assert painter._canvas._lineWidth == before
