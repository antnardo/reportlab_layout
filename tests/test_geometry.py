"""Géométrie de page et conversions de repères."""

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from reportlab_layout.geometry import Margins, PageGeometry, resolve_pagesize


class TestResolvePagesize:
    def test_named_format(self):
        assert resolve_pagesize("A4") == pytest.approx(A4)

    def test_lowercase_named_format(self):
        assert resolve_pagesize("letter")[0] == pytest.approx(612)

    def test_landscape_swaps_sides(self):
        width, height = resolve_pagesize("A4", landscape=True)
        assert width > height

    def test_explicit_tuple_passes_through(self):
        assert resolve_pagesize((100, 200)) == (100.0, 200.0)

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Format de page inconnu"):
            resolve_pagesize("A4bis")


class TestMargins:
    def test_build_converts_from_unit(self):
        margins = Margins.build(left=10, unit=mm)
        assert margins.left == pytest.approx(10 * mm)


class TestPageGeometry:
    @pytest.fixture
    def geometry(self):
        return PageGeometry.build("A4", left=15, right=15, top=20, bottom=10)

    def test_content_width_removes_side_margins(self, geometry):
        assert geometry.content_width == pytest.approx(A4[0] - 30 * mm)

    def test_content_height_removes_top_and_bottom(self, geometry):
        assert geometry.content_height == pytest.approx(A4[1] - 30 * mm)

    def test_y_top_is_below_the_top_margin(self, geometry):
        assert geometry.y_top == pytest.approx(A4[1] - 20 * mm)

    def test_depth_and_y_are_inverse(self, geometry):
        assert geometry.y_to_depth(geometry.depth_to_y(123.0)) == pytest.approx(123.0)

    def test_bottom_depth_matches_y_bottom(self, geometry):
        assert geometry.depth_to_y(geometry.bottom_depth) == pytest.approx(geometry.y_bottom)

    def test_content_box_is_the_active_rectangle(self, geometry):
        x, y, width, height = geometry.content_box
        assert (x, y) == pytest.approx((geometry.x_left, geometry.y_bottom))
        assert (width, height) == pytest.approx((geometry.content_width, geometry.content_height))
