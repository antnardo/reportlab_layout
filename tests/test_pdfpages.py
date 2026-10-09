"""Pages of other PDFs, laid down as vector drawing: once per document, fonts included."""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject, StreamObject
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

from reportlab_layout import (
    InlineParagraph,
    PDFMaker,
    TaggedParagraph,
    draw_pdf_page,
    inline_image,
    inline_pdf,
    pdf_page,
    pdfpages,
)

STYLE = ParagraphStyle("inline", fontName="Helvetica", fontSize=10, leading=12, autoLeading="max")


@pytest.fixture
def black_page(tmp_path):
    """A one-page PDF whose crop box, (10, 10)-(70, 30), is painted black, and nothing else is."""
    path = tmp_path / "black.pdf"
    canvas = pdfcanvas.Canvas(str(path), pagesize=(80, 40))
    canvas.setFillColorRGB(0, 0, 0)
    canvas.rect(10, 10, 60, 20, stroke=0, fill=1)
    canvas.setFillColorRGB(0.5, 0.5, 0.5)
    canvas.rect(0, 0, 10, 40, stroke=0, fill=1)  # outside the crop box: clipped
    canvas.save()
    writer = PdfWriter(clone_from=str(path))
    writer.pages[0].cropbox = RectangleObject([10, 10, 70, 30])
    writer.write(str(path))
    return path


@pytest.fixture
def two_formulas(tmp_path):
    """Two one-page PDFs cut out of one document: different text, the very same font."""
    pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
    whole = tmp_path / "lot.pdf"
    canvas = pdfcanvas.Canvas(str(whole), pagesize=(60, 16))
    for text in ("PV = nRT", "E = mc2"):
        canvas.setFont("Vera", 10)
        canvas.drawString(2, 4, text)
        canvas.showPage()
    canvas.save()
    paths = []
    for index in range(2):
        writer = PdfWriter()
        writer.add_page(PdfReader(whole).pages[index])
        paths.append(tmp_path / f"formula{index}.pdf")
        writer.write(paths[-1])
    return paths


def streams(path, test):
    """The streams of a PDF for which ``test(stream)`` holds."""
    reader = PdfReader(path)
    found = []
    for number in range(1, int(reader.trailer["/Size"])):
        obj = reader.get_object(number)
        if isinstance(obj, StreamObject) and test(obj):
            found.append(obj)
    return found


def forms(path):
    return streams(path, lambda s: s.get("/Subtype") == "/Form")


def images(path):
    return streams(path, lambda s: s.get("/Subtype") == "/Image")


def font_files(path):
    return streams(path, lambda s: "/Length1" in s)


class TestPdfPage:
    def test_reads_the_crop_box(self, black_page):
        page = pdf_page(black_page)
        assert page.box == (10, 10, 70, 30)
        assert (page.width, page.height) == (60, 20)

    def test_path_bytes_and_file_give_the_same_page(self, black_page):
        data = Path(black_page).read_bytes()
        keys = {pdf_page(black_page).key, pdf_page(data).key, pdf_page(io.BytesIO(data)).key}
        assert len(keys) == 1

    @pytest.mark.parametrize(
        ("asked", "size"),
        [
            ({}, (60, 20)),
            ({"width": 120}, (120, 40)),
            ({"height": 10}, (30, 10)),
            ({"scale": 0.5}, (30, 10)),
            ({"width": 50, "height": 50}, (50, 50)),
        ],
    )
    def test_size_follows_an_images_rules(self, black_page, asked, size):
        assert pdf_page(black_page).size(**asked) == pytest.approx(size)

    def test_a_missing_page_is_refused(self, black_page):
        with pytest.raises(IndexError):
            pdf_page(black_page, index=3)

    def test_a_rotated_page_is_refused(self, black_page, tmp_path):
        writer = PdfWriter(clone_from=str(black_page))
        writer.pages[0].rotate(90)
        rotated = tmp_path / "rotated.pdf"
        writer.write(rotated)
        with pytest.raises(ValueError, match="rotated"):
            pdf_page(rotated)

    def test_without_pypdf_says_what_to_install(self, black_page, monkeypatch):
        pdfpages._read_page.cache_clear()  # a page read before would be served without pypdf
        monkeypatch.setitem(sys.modules, "pypdf", None)
        with pytest.raises(ImportError, match=r"reportlab_layout\[pdf\]"):
            pdf_page(black_page)


class TestDrawPdfPage:
    def test_lands_on_the_rectangle_asked_and_is_clipped_to_its_box(self, out, black_page, ink):
        with PDFMaker(out) as doc:
            box = doc.draw_pdf_page(black_page, 100, 500, width=120)
        assert tuple(box) == pytest.approx((100, 500, 120, 40))
        found = ink(out, dpi=144)
        assert found is not None
        assert (found.left, found.bottom) == pytest.approx((100, 500), abs=1)
        assert (found.right, found.top) == pytest.approx((220, 540), abs=1)

    def test_stays_vector_text(self, out, two_formulas):
        with PDFMaker(out) as doc:
            doc.draw_pdf_page(two_formulas[0], 100, 500, scale=2)
        assert images(out) == []
        assert "PV = nRT" in PdfReader(out).pages[0].extract_text()

    def test_a_page_drawn_again_is_written_once(self, out, black_page):
        with PDFMaker(out) as doc:
            doc.draw_pdf_page(black_page, 100, 500)
            doc.draw_pdf_page(pdf_page(Path(black_page).read_bytes()), 100, 300, scale=2)
            doc.new_page()
            doc.draw_pdf_page(black_page, 100, 500)
        assert len(forms(out)) == 1

    def test_the_same_page_from_another_file_is_written_once(self, out, black_page, tmp_path):
        copy = tmp_path / "copy.pdf"
        writer = PdfWriter(clone_from=str(black_page))
        writer.add_metadata({"/Title": "another file, the same page"})
        writer.write(copy)
        assert pdf_page(copy).key != pdf_page(black_page).key
        with PDFMaker(out) as doc:
            doc.draw_pdf_page(black_page, 100, 500)
            doc.draw_pdf_page(copy, 100, 300)
        assert len(forms(out)) == 1

    def test_a_page_drawn_again_is_not_read_again(self, out, black_page, monkeypatch):
        reads = []
        original = pdfpages._reader
        monkeypatch.setattr(pdfpages, "_reader", lambda data: reads.append(1) or original(data))
        page = pdf_page(black_page)
        reads.clear()
        with PDFMaker(out) as doc:
            for y in (100, 300, 500):
                doc.draw_pdf_page(page, 100, y)
        assert len(reads) == 1

    def test_a_font_two_pages_share_is_written_once(self, out, two_formulas):
        with PDFMaker(out) as doc:
            doc.draw_pdf_page(two_formulas[0], 100, 500)
            doc.draw_pdf_page(two_formulas[1], 100, 400)
        assert len(forms(out)) == 2
        assert len(font_files(out)) == 1

    def test_works_on_a_bare_canvas(self, out, black_page):
        canvas = pdfcanvas.Canvas(str(out))
        draw_pdf_page(canvas, black_page, 100, 500)
        canvas.save()
        assert len(forms(out)) == 1

    def test_an_encrypted_document_is_refused(self, out, black_page):
        canvas = pdfcanvas.Canvas(str(out), encrypt="secret")
        with pytest.raises(ValueError, match="encrypted"):
            draw_pdf_page(canvas, black_page, 100, 500)

    def test_inside_an_annotation_its_appearance_declares_the_page(self, out, black_page):
        with PDFMaker(out) as doc, doc.annotation(100, 500, 60, 20):
            doc.draw_pdf_page(black_page, 100, 500)
        [stamp] = [a.get_object() for a in PdfReader(out).pages[0]["/Annots"]]
        appearance = stamp["/AP"]["/N"].get_object()
        assert any(
            x.get_object().get("/Subtype") == "/Form" for x in appearance["/Resources"]["/XObject"].values()
        )


class TestInlinePdf:
    @pytest.fixture
    def black_png(self, tmp_path):
        path = tmp_path / "black.png"
        PILImage.new("RGB", (60, 20), "black").save(path)
        return path

    def text(self, tag):
        return f"Before {tag} and after, a line long enough to be broken at least once in its width."

    def test_the_line_is_laid_out_as_for_an_image(self, black_page, black_png):
        as_pdf = InlineParagraph(self.text(inline_pdf(black_page, depth=4)), STYLE)
        as_image = InlineParagraph(self.text(inline_image(black_png, 60, 20, depth=4)), STYLE)
        assert as_pdf.wrap(200, 500) == as_image.wrap(200, 500)
        assert as_pdf.baselines() == as_image.baselines()

    def test_the_page_lands_where_the_image_would(self, tmp_path, black_page, black_png, ink):
        found = []
        for name, tag in (
            ("pdf", inline_pdf(black_page, depth=4)),
            ("png", inline_image(black_png, 60, 20, depth=4)),
        ):
            path = tmp_path / f"{name}.pdf"
            with PDFMaker(path) as doc:
                doc.draw(InlineParagraph(tag, STYLE), x=100, y=200, absolute=True)
            found.append(ink(path, dpi=144))
        assert found[0] is not None
        assert found[0] == pytest.approx(found[1], abs=1)

    def test_no_stand_in_reaches_the_document(self, out, black_page, black_png):
        with PDFMaker(out) as doc:
            doc.draw(InlineParagraph(self.text(inline_pdf(black_page)), STYLE))
            doc.draw(InlineParagraph(self.text(inline_image(black_png, 60, 20)), STYLE))
        assert len(forms(out)) == 1
        assert len(images(out)) == 1  # the real one

    def test_a_tagged_paragraph_draws_the_pages_of_its_tag(self, out, black_page):
        with PDFMaker(out) as doc:
            doc.draw(
                TaggedParagraph(
                    self.text(inline_pdf(black_page)), STYLE, tag=inline_pdf(black_page, scale=0.5)
                )
            )
        assert images(out) == []
        assert len(forms(out)) == 1

    def test_a_plain_paragraph_paints_the_stand_in(self, out, black_page):
        """It cannot draw the page; the magenta box makes the slip show."""
        with PDFMaker(out) as doc:
            doc.draw(Paragraph(self.text(inline_pdf(black_page)), STYLE))
        assert forms(out) == []
        assert len(images(out)) == 1
