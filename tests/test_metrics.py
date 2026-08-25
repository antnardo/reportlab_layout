"""Font metrics -- where vertical centring is pinned down."""

import pytest
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import getAscentDescent

from reportlab_layout.metrics import (
    TextMetrics,
    baseline_offset,
    cap_height,
    font_ascent,
    font_descent,
    font_height,
    string_width,
)


@pytest.fixture
def normal(stylesheet):
    return stylesheet["Normal"]


class TestTextMetrics:
    def test_font_size_follows_scale(self, normal):
        assert TextMetrics(normal, 0.5).font_size == pytest.approx(normal.fontSize * 0.5)

    def test_descent_is_negative(self, normal):
        assert TextMetrics(normal).descent < 0

    def test_height_is_ascent_minus_descent(self, normal):
        metrics = TextMetrics(normal)
        assert metrics.height == pytest.approx(metrics.ascent - metrics.descent)

    def test_metrics_scale_linearly(self, normal):
        full, half = TextMetrics(normal), TextMetrics(normal, 0.5)
        assert half.height == pytest.approx(full.height / 2)
        assert half.ascent == pytest.approx(full.ascent / 2)
        assert half.width("Hello") == pytest.approx(full.width("Hello") / 2)

    def test_baseline_offset_is_half_the_em_box_center(self, normal):
        ascent, descent = getAscentDescent(normal.fontName, normal.fontSize)
        assert baseline_offset(normal) == pytest.approx((ascent + descent) / 2)

    def test_baseline_offset_differs_from_half_height(self, normal):
        """The historical bug: centring on height/2 drops the text by |descent|."""
        metrics = TextMetrics(normal)
        assert metrics.height / 2 - metrics.baseline_offset == pytest.approx(-metrics.descent)

    def test_middle_anchor_centers_the_em_box(self, normal):
        """The 'middle' anchor: the em box centre lands exactly on y."""
        metrics = TextMetrics(normal)
        baseline = metrics.baseline(200, "middle")
        box_bottom = baseline + metrics.descent
        assert box_bottom + metrics.height / 2 == pytest.approx(200)

    def test_middle_anchor_centers_at_any_scale(self, normal):
        metrics = TextMetrics(normal, 0.4)
        baseline = metrics.baseline(200, "middle")
        assert baseline + metrics.descent + metrics.height / 2 == pytest.approx(200)

    def test_baseline_anchor_leaves_y_untouched(self, normal):
        assert TextMetrics(normal).baseline(100, "baseline") == pytest.approx(100)

    def test_top_anchor_drops_by_the_ascent(self, normal):
        metrics = TextMetrics(normal)
        assert metrics.baseline(100, "top") == pytest.approx(100 - metrics.ascent)

    def test_bottom_anchor_lifts_by_the_descent(self, normal):
        metrics = TextMetrics(normal)
        assert metrics.baseline(100, "bottom") == pytest.approx(100 - metrics.descent)

    def test_unknown_valign_raises(self, normal):
        with pytest.raises(ValueError, match="valign"):
            TextMetrics(normal).baseline(0, "milieu")

    @pytest.mark.parametrize(
        "halign,expected_shift",
        [("left", 0), ("center", -0.5), ("right", -1.0)],
    )
    def test_left_edge_anchors(self, normal, halign, expected_shift):
        metrics = TextMetrics(normal)
        width = metrics.width("Hello")
        assert metrics.left_edge(100, "Hello", halign) == pytest.approx(100 + expected_shift * width)

    def test_unknown_halign_raises(self, normal):
        with pytest.raises(ValueError, match="halign"):
            TextMetrics(normal).left_edge(0, "x", "middle")


class TestModuleHelpers:
    def test_helpers_match_the_class(self, normal):
        metrics = TextMetrics(normal, 0.75)
        assert string_width("abc", normal, 0.75) == pytest.approx(metrics.width("abc"))
        assert font_ascent(normal, 0.75) == pytest.approx(metrics.ascent)
        assert font_descent(normal, 0.75) == pytest.approx(metrics.descent)
        assert font_height(normal, 0.75) == pytest.approx(metrics.height)


class TestCapHeight:
    def test_helvetica_cap_height_equals_its_ascent(self, stylesheet):
        """Measured by rasterisation: Helvetica's cap height equals its ascent."""
        metrics = TextMetrics(ParagraphStyle("h", fontName="Helvetica", fontSize=100))
        assert metrics.cap_height == pytest.approx(metrics.ascent)

    def test_times_cap_height_is_below_its_ascent(self):
        """For Times, ascent and cap height differ."""
        metrics = TextMetrics(ParagraphStyle("t", fontName="Times-Roman", fontSize=100))
        assert metrics.cap_height == pytest.approx(66.2)
        assert metrics.cap_height < metrics.ascent

    def test_unknown_font_falls_back_to_the_ascent(self):
        metrics = TextMetrics(ParagraphStyle("z", fontName="ZapfDingbats", fontSize=100))
        assert metrics.cap_height == pytest.approx(metrics.ascent)

    def test_cap_height_follows_scale(self, normal):
        assert TextMetrics(normal, 0.5).cap_height == pytest.approx(TextMetrics(normal).cap_height / 2)

    def test_cap_anchor_centres_the_capital_box(self, normal):
        metrics = TextMetrics(normal)
        baseline = metrics.baseline(200, "cap")
        assert baseline + metrics.cap_height / 2 == pytest.approx(200)

    def test_cap_sits_lower_than_the_em_box_middle(self, normal):
        """Em centring reserves descender room and lifts the text."""
        metrics = TextMetrics(normal)
        assert metrics.baseline(200, "cap") < metrics.baseline(200, "middle")

    def test_cap_height_helper_matches_the_class(self, normal):
        assert cap_height(normal, 0.75) == pytest.approx(TextMetrics(normal, 0.75).cap_height)
