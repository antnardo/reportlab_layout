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

    def test_ellipse_is_centred_on_its_point(self, painter):
        assert tuple(painter.ellipse(50, 50, 30, 10)) == pytest.approx((20, 40, 60, 20))

    def test_circle_is_an_ellipse_with_equal_radii(self, painter):
        assert tuple(painter.circle(50, 50, 10)) == tuple(painter.ellipse(50, 50, 10, 10))

    @pytest.mark.parametrize("rx,ry", [(0, 10), (10, 0), (-1, 10), (10, -1)])
    def test_ellipse_rejects_a_non_positive_radius(self, painter, rx, ry):
        with pytest.raises(ValueError, match="radii must be positive"):
            painter.ellipse(0, 0, rx, ry)

    def test_circle_forwards_its_keywords(self, painter):
        """`fill` and friends must reach the ellipse, not be swallowed."""
        before = painter._canvas._fillColorObj
        painter.circle(10, 10, 5, fill=(1, 0, 0))
        assert painter._canvas._fillColorObj == before

    def test_polygon_returns_the_bounding_box_of_its_points(self, painter):
        box = painter.polygon([(0, 0), (30, 0), (30, 40), (10, 25)])
        assert tuple(box) == pytest.approx((0, 0, 30, 40))

    @pytest.mark.parametrize("points", [[], [(0, 0)], [(0, 0), (1, 1)]])
    def test_polygon_needs_three_points(self, painter, points):
        with pytest.raises(ValueError, match="at least 3 points"):
            painter.polygon(points)

    def test_polygon_accepts_an_open_path(self, painter):
        assert tuple(painter.polygon([(0, 0), (10, 0), (10, 10)], close=False)) == pytest.approx(
            (0, 0, 10, 10)
        )

    def test_regular_polygon_is_inscribed_in_its_circle(self, painter):
        box = painter.regular_polygon(50, 50, 10, vertices=4, start_angle=0)
        assert tuple(box) == pytest.approx((40, 40, 20, 20))

    def test_regular_polygon_starts_where_asked(self, painter):
        """start_angle=90 puts a vertex straight up, hence the box touching y+radius."""
        box = painter.regular_polygon(0, 0, 10, vertices=3, start_angle=90)
        assert box.top == pytest.approx(10)

    def test_pentagram_spans_the_full_circle(self, painter):
        """{5/2} visits the same five vertices as {5/1}, so the box is unchanged."""
        star = painter.regular_polygon(0, 0, 10, vertices=5, leap=2)
        convex = painter.regular_polygon(0, 0, 10, vertices=5, leap=1)
        assert tuple(star) == pytest.approx(tuple(convex))

    @pytest.mark.parametrize("vertices", [0, 1, 2])
    def test_regular_polygon_needs_three_vertices(self, painter, vertices):
        with pytest.raises(ValueError, match="at least 3 vertices"):
            painter.regular_polygon(0, 0, 10, vertices=vertices)

    @pytest.mark.parametrize("leap", [0, 5, 9])
    def test_regular_polygon_rejects_an_out_of_range_leap(self, painter, leap):
        with pytest.raises(ValueError, match="leap must be in"):
            painter.regular_polygon(0, 0, 10, vertices=5, leap=leap)

    @pytest.mark.parametrize("vertices,leap", [(6, 2), (6, 3), (8, 2), (9, 3)])
    def test_regular_polygon_rejects_a_path_that_closes_early(self, painter, vertices, leap):
        """{6/2} would trace a triangle, not the hexagram: two paths are needed."""
        with pytest.raises(ValueError, match="cannot draw it"):
            painter.regular_polygon(0, 0, 10, vertices=vertices, leap=leap)

    def test_polygon_does_not_leak_the_line_join(self, painter):
        before = painter._canvas._lineJoin
        painter.polygon([(0, 0), (10, 0), (5, 9)], line_join=1)
        assert painter._canvas._lineJoin == before

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


def spy(canvas, name):
    """Record the calls made to one canvas method, and let them through.

    reportlab keeps no readable trace of the dash pattern -- `_lineDash` stays
    None whatever you set -- so the call itself is what there is to check.
    """
    calls = []
    original = getattr(canvas, name)

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    setattr(canvas, name, record)
    return calls


class TestPen:
    """dash, line_cap and line_join, and the state they must not leave behind."""

    def test_dash_reaches_the_canvas(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.line(0, 0, 10, 0, dash=(2, 2), dash_phase=1)
        assert calls == [(([2, 2], 1), {})]

    def test_line_cap_is_set_while_drawing(self, painter):
        seen = []
        original = painter._canvas.line
        painter._canvas.line = lambda *a: seen.append(painter._canvas._lineCap) or original(*a)
        painter.line(0, 0, 10, 0, line_cap=1)
        assert seen == [1]

    def test_line_cap_does_not_leak(self, painter):
        before = painter._canvas._lineCap
        painter.line(0, 0, 10, 0, line_cap=1)
        assert painter._canvas._lineCap == before

    def test_dash_on_a_rectangle_outline(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.rect(0, 0, 10, 10, dash=(4, 3))
        assert calls == [(([4, 3], 0), {})]

    def test_dash_on_a_rounded_rectangle(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.round_rect(0, 0, 20, 10, dash=(1, 1))
        assert calls == [(([1, 1], 0), {})]

    def test_dash_on_an_ellipse(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.ellipse(10, 10, 5, 3, dash=(1, 2))
        assert calls == [(([1, 2], 0), {})]

    def test_an_open_polygon_takes_a_cap(self, painter):
        seen = []
        original = painter._canvas.drawPath
        painter._canvas.drawPath = lambda *a, **k: seen.append(painter._canvas._lineCap) or original(*a, **k)
        painter.polygon([(0, 0), (10, 0), (5, 8)], close=False, line_cap=1)
        assert seen == [1]

    def test_a_star_passes_the_pattern_through(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.regular_polygon(10, 10, 5, vertices=5, leap=2, dash=(2, 2))
        assert calls == [(([2, 2], 0), {})]

    def test_no_pattern_leaves_the_canvas_alone(self, painter):
        calls = spy(painter._canvas, "setDash")
        painter.rect(0, 0, 10, 10)
        assert calls == []
