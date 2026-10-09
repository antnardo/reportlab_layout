"""Annotations drawn like the page: movable, removable, and shown exactly as drawn."""

import re
import shutil
import subprocess

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader
from reportlab.lib.colors import CMYKColorSep, blue, red

from reportlab_layout import PDFMaker


def annotations(path, page=0):
    """The annotation dictionaries of a page, resolved."""
    return [ref.get_object() for ref in PdfReader(path).pages[page].get("/Annots", [])]


def page_content(path, page=0):
    return PdfReader(path).pages[page].get_contents().get_data()


class TestAnnotation:
    def test_stamp_carries_its_drawing_as_appearance(self, out):
        doc = PDFMaker(out)
        with doc.annotation(100, 600, 80, 30, contents="unit?", author="corrector") as box:
            doc.draw_rect(100, 600, 80, 30, fill="#fff3b0", stroke="#d4b106")
        doc.save()
        [stamp] = annotations(out)
        assert (stamp["/Subtype"], stamp["/Contents"], stamp["/T"]) == ("/Stamp", "unit?", "corrector")
        assert [float(value) for value in stamp["/Rect"]] == [100, 600, 180, 630]
        assert stamp["/F"] == 4  # printed with the page
        appearance = stamp["/AP"]["/N"].get_object()
        assert [float(value) for value in appearance["/BBox"]] == [100, 600, 180, 630]
        assert b" re" in appearance.get_data()
        assert b" re" not in page_content(out)  # on top of the page, not in it
        assert tuple(box) == (100, 600, 80, 30)

    def test_drawing_after_the_block_lands_on_the_page(self, out):
        with PDFMaker(out) as doc:
            with doc.annotation(100, 600, 80, 30):
                doc.draw_string("inside", 105, 610)
            doc.draw_string("outside", 300, 300)
        assert b"outside" in page_content(out)
        appearance = annotations(out)[0]["/AP"]["/N"].get_object()
        assert b"inside" in appearance.get_data() and b"outside" not in appearance.get_data()

    def test_an_image_inside_comes_with_its_resources(self, out, picture):
        with PDFMaker(out) as doc, doc.annotation(50, 50, 100, 50):
            doc.draw_image(picture, 100, 50, x=50, y=50, absolute=True)
        appearance = annotations(out)[0]["/AP"]["/N"].get_object()
        assert appearance["/Resources"]["/XObject"]

    def test_several_on_one_page_each_keep_their_own_drawing(self, out):
        with PDFMaker(out) as doc:
            for index, text in enumerate(["first", "second"]):
                with doc.annotation(100, 100 + 100 * index, 80, 30, contents=text):
                    doc.draw_string(text, 105, 110 + 100 * index)
        found = annotations(out)
        assert [stamp["/Contents"] for stamp in found] == ["first", "second"]
        drawn = [stamp["/AP"]["/N"].get_object().get_data() for stamp in found]
        assert b"first" in drawn[0] and b"second" in drawn[1] and b"second" not in drawn[0]

    def test_annotations_stay_on_their_own_page(self, out):
        with PDFMaker(out) as doc:
            with doc.annotation(100, 100, 50, 50, contents="page one"):
                doc.draw_rect(100, 100, 50, 50)
            doc.new_page()
            with doc.annotation(100, 100, 50, 50, contents="page two"):
                doc.draw_rect(100, 100, 50, 50)
        assert [a["/Contents"] for a in annotations(out, 0)] == ["page one"]
        assert [a["/Contents"] for a in annotations(out, 1)] == ["page two"]

    def test_a_failing_block_adds_nothing_and_the_page_goes_on(self, out):
        with PDFMaker(out) as doc:
            with pytest.raises(ZeroDivisionError), doc.annotation(100, 600, 80, 30):
                doc.draw_string("lost", 105, 610)
                1 / 0  # noqa: B018 - the failure under test
            doc.draw_string("kept", 300, 300)
        assert annotations(out) == []
        assert b"kept" in page_content(out) and b"lost" not in page_content(out)

    @pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (-5, 10)])
    def test_an_empty_rectangle_is_refused(self, doc, width, height):
        with (
            pytest.raises(ValueError, match="positive width and height"),
            doc.annotation(0, 0, width, height),
        ):
            pass

    def test_annotations_alone_on_a_fresh_page_are_all_kept(self, out):
        """reportlab drops what a blank page holds when a form ends, and never writes it: not here.

        The first page is never blank -- PDFMaker sets its font size there -- so
        the test needs a second one.
        """
        with PDFMaker(out) as doc:
            doc.new_page()
            for index in range(3):
                with doc.annotation(100, 100 + 60 * index, 50, 50, contents=str(index)):
                    doc.draw_rect(100, 100 + 60 * index, 50, 50)
        assert len(PdfReader(out).pages) == 2
        assert [a["/Contents"] for a in annotations(out, 1)] == ["0", "1", "2"]

    def test_annotations_do_not_nest(self, doc):
        with (
            doc.annotation(0, 0, 50, 50),
            pytest.raises(RuntimeError, match="nest"),
            doc.annotation(0, 0, 10, 10),
        ):
            pass

    def test_a_page_break_inside_is_refused(self, out):
        doc = PDFMaker(out)
        with pytest.raises(RuntimeError, match="page break"), doc.annotation(100, 100, 50, 50):
            doc.new_page()
        doc.save()

    def test_a_reader_draws_it_where_it_was_drawn(self, out, ink):
        """poppler, like the readers, paints the appearance at its rectangle."""
        with PDFMaker(out) as doc, doc.annotation(200, 400, 60, 40):
            doc.draw_rect(200, 400, 60, 40, fill="#000000")
        found = ink(out, dpi=144)
        assert found is not None
        assert found.left == pytest.approx(200, abs=1) and found.right == pytest.approx(260, abs=1)
        assert found.bottom == pytest.approx(400, abs=1) and found.top == pytest.approx(440, abs=1)

    def test_text_beyond_ascii_reaches_the_comments_panel(self, out):
        with PDFMaker(out) as doc, doc.annotation(100, 600, 80, 30, contents="unité → ½ ?", author="Zoé"):
            doc.draw_rect(100, 600, 80, 30)
        [stamp] = annotations(out)
        assert (stamp["/Contents"], stamp["/T"]) == ("unité → ½ ?", "Zoé")

    def test_a_string_alone_brings_its_own_font(self, out, ink):
        """An appearance starts from a blank graphics state: nothing set on the page reaches it."""
        with PDFMaker(out) as doc, doc.annotation(100, 600, 200, 40):
            doc.draw_string("HELLO", 105, 610, scale=2)
        assert b" Tf" in annotations(out)[0]["/AP"]["/N"].get_object().get_data()
        found = ink(out, dpi=144)
        assert found is not None
        assert found.left >= 100 and found.right <= 300 and found.bottom >= 600 and found.top <= 640

    def test_drawing_beyond_the_rectangle_is_clipped(self, out, ink):
        with PDFMaker(out) as doc, doc.annotation(200, 400, 60, 40):
            doc.draw_rect(150, 350, 200, 200, fill="#000000")
        found = ink(out, dpi=144)
        assert found is not None
        assert (found.left, found.bottom) == pytest.approx((200, 400), abs=1)
        assert (found.right, found.top) == pytest.approx((260, 440), abs=1)

    def test_saving_inside_is_refused_and_the_page_kept(self, out):
        doc = PDFMaker(out)
        doc.draw_string("before", 300, 300)
        with pytest.raises(RuntimeError, match="saved"), doc.annotation(100, 100, 50, 50):
            doc.draw_rect(100, 100, 50, 50)
            doc.save()
        doc.save()
        assert annotations(out) == []
        assert b"before" in page_content(out)

    @pytest.mark.parametrize(
        ("paint", "resource", "operator"),
        [
            (
                lambda doc: doc.draw_rect(100, 600, 80, 30, fill=(1, 0, 0, 0.5), stroke=None),
                "/ExtGState",
                b"gs",
            ),
            (lambda doc: doc.canvas.linearGradient(100, 600, 180, 630, (red, blue)), "/Shading", b"sh"),
            (
                lambda doc: doc.draw_rect(
                    100, 600, 80, 30, fill=CMYKColorSep(0, 0.5, 1, 0, spotName="ORANGE")
                ),
                "/ColorSpace",
                b"cs",
            ),
        ],
        ids=["see-through colour", "shading", "spot colour"],
    )
    def test_every_resource_the_drawing_names_is_declared(self, out, paint, resource, operator):
        """reportlab writes a form's fonts and images, and leaves these out."""
        with PDFMaker(out) as doc, doc.annotation(100, 600, 80, 30):
            paint(doc)
        appearance = annotations(out)[0]["/AP"]["/N"].get_object()
        named = re.findall(rb"/(\S+) " + operator + rb"\b", appearance.get_data())
        assert named
        declared = appearance["/Resources"][resource]
        assert all(f"/{name.decode()}" in declared for name in named)

    def test_a_see_through_colour_stays_see_through(self, out, tmp_path):
        """Without its graphics state, every reader drew it opaque, hiding the page beneath."""
        if shutil.which("pdftoppm") is None:
            pytest.skip("pdftoppm (poppler) is not installed")
        with PDFMaker(out) as doc:
            doc.draw_rect(100, 600, 80, 30, fill="black", stroke=None)
            with doc.annotation(100, 600, 80, 30):
                doc.draw_rect(100, 600, 80, 30, fill=(1, 1, 1, 0.5), stroke=None)
        stem = tmp_path / "blend"
        subprocess.run(["pdftoppm", "-r", "72", "-png", "-singlefile", str(out), str(stem)], check=True)
        with PILImage.open(stem.with_suffix(".png")) as image:
            grey = image.convert("L").getpixel((140, 842 - 615))
        assert grey == pytest.approx(128, abs=8)
