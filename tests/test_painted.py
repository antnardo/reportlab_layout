"""A flowable of one's own, drawn with the painters, and the reportlab names the package hands on."""

import inspect

import pytest
import reportlab.graphics.shapes
import reportlab.lib.colors
import reportlab.lib.styles
import reportlab.lib.units
import reportlab.platypus
from PIL import Image as PILImage
from pypdf import PdfReader

import reportlab_layout
from reportlab_layout import Box, PaintedFlowable, PDFMaker


class Gauge(PaintedFlowable):
    """A bar and its value, the kind of row a report of marks draws."""

    def __init__(self, fraction, label):
        super().__init__()
        self.fraction, self.label = fraction, label
        self.boxes = []

    def wrap(self, available_width, available_height):
        self.width, self.height = available_width, 20
        return self.width, self.height

    def paint(self):
        self.boxes.append(
            self.shapes.round_rect(0, 6, 200 * self.fraction, 8, radius=4, fill="#1565c0", stroke=None)
        )
        self.boxes.append(
            self.text.draw(self.label, self.width, 10, halign="right", valign="cap", outline=0.3)
        )


class TestPaintedFlowable:
    def test_paints_in_its_own_coordinates_and_returns_boxes(self, out):
        gauge = Gauge(0.7, "14 / 20")
        with PDFMaker(out) as doc:
            box = doc.draw(gauge)
        assert box.height == 20
        bar, label = gauge.boxes
        assert bar == Box(0, 6, pytest.approx(140), 8)
        assert label.right == pytest.approx(box.width)
        assert "14 / 20" in PdfReader(str(out)).pages[0].extract_text()

    def test_state_does_not_leak_into_what_follows(self, out):
        with PDFMaker(out) as doc:
            doc.draw(Gauge(0.5, "x"))
            assert tuple(doc.canvas._fillColorObj) == (0, 0, 0)
            assert doc.canvas._lineWidth != 0.3

    def test_draws_an_image_in_memory(self, out):
        class Stamp(PaintedFlowable):
            def wrap(self, available_width, available_height):
                return 40, 20

            def paint(self):
                self.box = self.image(PILImage.new("RGBA", (80, 40), (200, 0, 0, 128)), 0, 0, width=40)

        stamp = Stamp()
        with PDFMaker(out) as doc:
            doc.draw(stamp)
        assert stamp.box == Box(0, 0, 40, 20)
        assert PdfReader(str(out)).pages[0].images

    def test_style_names_resolve_against_its_stylesheet(self, out, stylesheet):
        class Labelled(PaintedFlowable):
            def wrap(self, available_width, available_height):
                return 100, 20

            def paint(self):
                self.size = self.text.metrics("Small").font_size

        labelled = Labelled()
        labelled.stylesheet = stylesheet
        with PDFMaker(out) as doc:
            doc.draw(labelled)
        assert labelled.size == stylesheet["Small"].fontSize

    def test_a_subclass_without_paint_says_so(self, out):
        class Bare(PaintedFlowable):
            def wrap(self, available_width, available_height):
                return 10, 10

        with PDFMaker(out) as doc, pytest.raises(NotImplementedError, match="Bare"):
            doc.draw(Bare())


@pytest.mark.parametrize(
    ("name", "module"),
    [
        ("ParagraphStyle", reportlab.lib.styles),
        ("StyleSheet1", reportlab.lib.styles),
        ("Color", reportlab.lib.colors),
        ("Flowable", reportlab.platypus),
        ("Drawing", reportlab.graphics.shapes),
        ("mm", reportlab.lib.units),
        ("cm", reportlab.lib.units),
        ("inch", reportlab.lib.units),
    ],
)
def test_reportlab_names_are_reportlabs_own_objects(name, module):
    assert getattr(reportlab_layout, name) is getattr(module, name)


def public_signatures():
    for _, member in inspect.getmembers(reportlab_layout):
        callables = [member, *(f for _, f in inspect.getmembers(member, inspect.isfunction))]
        for function in callables:
            if callable(function) and getattr(function, "__module__", "").startswith("reportlab_layout"):
                try:
                    yield str(inspect.signature(function))
                except (TypeError, ValueError):
                    continue


@pytest.mark.parametrize("name", ["ParagraphStyle", "StyleSheet1", "Color", "Flowable", "Drawing"])
def test_each_type_handed_on_appears_in_a_public_signature(name):
    """The rule for re-exporting: what you build to call the package, or what it returns."""
    assert any(name in signature for signature in public_signatures())


def test_the_units_handed_on_stand_for_the_unit_of_a_document():
    assert inspect.signature(PDFMaker.__init__).parameters["unit"].default == reportlab_layout.mm
