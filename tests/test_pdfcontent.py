"""What a page draws, glyph by glyph, and the same page with elements taken out."""

import io

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, StreamObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from reportlab_layout import PdfElement, PDFMaker, pdf_elements

HELVETICA = pdfmetrics.getTypeFace("Helvetica")


def source(tmp_path, draw, size=(400, 300), name="source.pdf"):
    """A one-page PDF drawn by ``draw(canvas)``."""
    path = tmp_path / name
    canvas = pdfcanvas.Canvas(str(path), pagesize=size)
    draw(canvas)
    canvas.save()
    return path


def redrawn(tmp_path, path, keep):
    """``path`` laid down again at the origin, without what ``keep`` refuses."""
    out = tmp_path / "out.pdf"
    page = PdfReader(path).pages[0]
    with PDFMaker(out, pagesize=(float(page.mediabox.width), float(page.mediabox.height))) as doc:
        doc.draw_pdf_page(path, 0, 0, keep=keep)
    return out


def glyphs(path):
    return [e for e in pdf_elements(path) if e.kind == "text"]


def text(path):
    return "".join(e.text for e in glyphs(path))


def decoded(path):
    """Every object of a PDF, streams decoded, as one blob of bytes."""
    reader = PdfReader(path)
    blob = b""
    for number in range(1, int(reader.trailer["/Size"])):
        obj = reader.get_object(number)
        blob += obj.get_data() if isinstance(obj, StreamObject) else repr(obj).encode()
    return blob


def without(*words):
    """Keep every element but the glyphs of ``words``, wherever they are."""
    return lambda e: e.kind != "text" or e.text not in "".join(words)


class TestElements:
    def test_a_glyph_runs_from_its_origin_over_its_advance_and_from_descent_to_ascent(self, tmp_path):
        path = source(tmp_path, lambda c: (c.setFont("Helvetica", 12), c.drawString(20, 250, "AB")))
        a, b = glyphs(path)
        width = HELVETICA.glyphWidths["A"] * 12 / 1000
        assert (a.text, a.font, a.size, a.page) == ("A", "Helvetica", 12, 0)
        assert a.origin == pytest.approx((20, 250))
        assert a.box == pytest.approx(
            (20, 250 + HELVETICA.descent * 12 / 1000, 20 + width, 250 + HELVETICA.ascent * 12 / 1000)
        )
        assert b.origin == pytest.approx((20 + width, 250))

    def test_the_text_matrix_and_the_ctm_place_and_size_glyphs(self, tmp_path):
        def draw(c):
            c.translate(100, 50)
            c.rotate(90)
            c.setFont("Helvetica", 10)
            c.drawString(0, 0, "I")
            c.scale(2, 2)
            c.drawString(10, 0, "I")

        upright, doubled = glyphs(source(tmp_path, draw))
        assert upright.origin == pytest.approx((100, 50))
        assert upright.box[0] < 100 < upright.box[2]  # turned a quarter: the advance goes up
        assert upright.box[3] - upright.box[1] == pytest.approx(HELVETICA.glyphWidths["I"] * 10 / 1000)
        assert doubled.size == pytest.approx(20)
        assert doubled.origin == pytest.approx((100, 70))

    def test_spacings_and_scaling_move_the_glyphs_that_follow(self, tmp_path):
        def draw(c):
            text_object = c.beginText(20, 200)
            text_object.setFont("Helvetica", 10)
            text_object.setCharSpace(2)
            text_object.setWordSpace(5)
            text_object.setHorizScale(50)
            text_object.textOut("a b")
            c.drawText(text_object)

        _, space, b = glyphs(source(tmp_path, draw))
        advance = lambda glyph, extra: (HELVETICA.glyphWidths[glyph] * 10 / 1000 + extra) * 0.5  # noqa: E731
        assert space.origin[0] == pytest.approx(20 + advance("a", 2))
        assert b.origin[0] == pytest.approx(space.origin[0] + advance("space", 2 + 5))

    def test_a_truetype_font_gives_its_unicode_text(self, tmp_path):
        pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
        path = source(tmp_path, lambda c: (c.setFont("Vera", 11), c.drawString(20, 200, "Élève à l’été")))
        assert text(path) == "Élève à l’été"

    def test_images_paths_and_forms_are_elements_too(self, tmp_path):
        png = io.BytesIO()
        PILImage.new("RGB", (4, 4), "red").save(png, "PNG")

        def draw(c):
            c.drawImage(ImageReader(io.BytesIO(png.getvalue())), 300, 140, 30, 20)
            c.setLineWidth(4)
            c.line(10, 10, 110, 10)
            c.beginForm("stamp")
            c.setFont("Helvetica", 10)
            c.drawString(0, 0, "F")
            c.endForm()
            c.saveState()
            c.translate(150, 100)
            c.doForm("stamp")
            c.restoreState()

        elements = pdf_elements(source(tmp_path, draw))
        image, path, glyph = (
            next(e for e in elements if e.kind == kind) for kind in ("image", "path", "text")
        )
        assert image.box == pytest.approx((300, 140, 330, 160))
        assert path.box == pytest.approx((8, 8, 112, 12))  # widened by half the line width
        assert glyph.origin == pytest.approx((150, 100))  # inside the form, its placement applied

    def test_a_font_that_cannot_be_measured_is_refused(self, tmp_path):
        pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
        path = source(tmp_path, lambda c: (c.setFont("Vera", 11), c.drawString(20, 200, "x")))
        writer = PdfWriter(clone_from=str(path))
        for font in writer.pages[0]["/Resources"]["/Font"].values():
            font.get_object().pop("/Widths", None)
        writer.write(path)
        with pytest.raises(ValueError, match="no /Widths"):
            pdf_elements(path)


class TestFiltering:
    def test_a_glyph_taken_out_leaves_the_others_in_place(self, tmp_path):
        def draw(c):
            text_object = c.beginText(20, 200)
            text_object.setFont("Helvetica", 10)
            text_object.setCharSpace(1)
            text_object.setWordSpace(3)
            text_object.textOut("Name: SECRET and more")
            c.drawText(text_object)

        path = source(tmp_path, draw)
        out = redrawn(tmp_path, path, without("SECRET"))
        kept = [e for e in glyphs(path) if e.text not in "SECRET"]
        assert [(e.text, e.origin) for e in glyphs(out)] == [(e.text, pytest.approx(e.origin)) for e in kept]
        assert b"SECRET" not in decoded(out)

    @pytest.mark.parametrize("operator", ["'", '"'])
    def test_the_next_line_operators_keep_their_line(self, tmp_path, operator):
        def draw(c):
            c.setFont("Helvetica", 10)
            shown = "(SECRETline) '" if operator == "'" else '2 1 (SECRETline) "'
            c._code.append(f"BT /F1 10 Tf 14 TL 20 200 Td (first) Tj {shown} ET")

        path = source(tmp_path, draw)
        out = redrawn(tmp_path, path, without("SECRET"))
        kept = [e for e in glyphs(path) if e.text not in "SECRET"]
        assert [(e.text, e.origin) for e in glyphs(out)] == [(e.text, pytest.approx(e.origin)) for e in kept]

    def test_a_hidden_text_goes_and_the_box_over_it_stays(self, tmp_path):
        def draw(c):
            c.setFont("Courier-Bold", 9)
            c.drawString(150, 150, "HIDDEN")
            c.setFillColorRGB(1, 1, 1)
            c.rect(140, 140, 120, 25, fill=1, stroke=0)

        out = redrawn(tmp_path, source(tmp_path, draw), without("HIDDEN"))
        assert glyphs(out) == []
        assert [e.kind for e in pdf_elements(out)] == ["path"]
        assert b"HIDDEN" not in decoded(out)

    def test_an_image_taken_out_leaves_the_file(self, tmp_path):
        pngs = []
        for colour in (
            "red",
            "green",
        ):  # two images: reportlab would write one image drawn twice as one object
            png = io.BytesIO()
            PILImage.new("RGB", (4, 4), colour).save(png, "PNG")
            pngs.append(png.getvalue())
        inline = PILImage.new("RGB", (4, 4), "blue")

        def draw(c):
            c.drawImage(ImageReader(io.BytesIO(pngs[0])), 300, 140, 30, 20)
            c.drawImage(ImageReader(io.BytesIO(pngs[1])), 20, 20, 30, 20)
            c.drawInlineImage(inline, 300, 20, 30, 20)

        path = source(tmp_path, draw)
        out = redrawn(tmp_path, path, lambda e: e.kind != "image" or e.box[0] < 100)
        assert [e.box for e in pdf_elements(out)] == [pytest.approx((20, 20, 50, 40))]
        reader = PdfReader(out)
        images = [
            n
            for n in range(1, int(reader.trailer["/Size"]))
            if isinstance(o := reader.get_object(n), StreamObject) and o.get("/Subtype") == "/Image"
        ]
        assert len(images) == 1

    def test_a_clipping_path_taken_out_still_clips(self, tmp_path):
        source_path = source(tmp_path, lambda c: c._code.append("10 10 50 50 re W f"))
        out = redrawn(tmp_path, source_path, lambda e: e.kind != "path")
        assert pdf_elements(out) == []
        form = next(
            o
            for n in range(1, int(PdfReader(out).trailer["/Size"]))
            if isinstance(o := PdfReader(out).get_object(n), StreamObject) and o.get("/Subtype") == "/Form"
        )
        operators = [op for _, op in ContentStream(form, PdfReader(out)).operations]
        assert operators[-3:] == [b"re", b"W", b"n"]

    def test_a_form_is_filtered_inside(self, tmp_path):
        def draw(c):
            c.beginForm("stamp")
            c.setFont("Helvetica", 10)
            c.drawString(0, 0, "keep SECRET")
            c.endForm()
            c.doForm("stamp")

        out = redrawn(tmp_path, source(tmp_path, draw), without("SECRET"))
        assert text(out) == "keep "
        assert b"SECRET" not in decoded(out)

    def test_marked_content_loses_the_texts_it_repeats(self, tmp_path):
        def draw(c):
            c._code.append("/Span <</ActualText (ACTUALSECRET) /Alt (ALTSECRET)>> BDC")
            c.setFont("Helvetica", 10)
            c.drawString(20, 200, "x")
            c._code.append("EMC")

        out = redrawn(tmp_path, source(tmp_path, draw), lambda e: True)
        assert text(out) == "x"
        assert b"ACTUALSECRET" not in decoded(out)
        assert b"ALTSECRET" not in decoded(out)

    def test_without_keep_the_page_is_copied_as_it_is(self, tmp_path, out):
        path = source(tmp_path, lambda c: (c.setFont("Helvetica", 10), c.drawString(20, 200, "all of it")))
        with PDFMaker(out, pagesize=(400, 300)) as doc:
            doc.draw_pdf_page(path, 0, 0)
        assert [(e.text, e.origin) for e in glyphs(out)] == [
            (e.text, pytest.approx(e.origin)) for e in glyphs(path)
        ]

    def test_an_element_is_a_frozen_record(self):
        element = PdfElement("text", (0, 0, 1, 1), 0, (0, 0), "a", "Helvetica", 10)
        with pytest.raises(AttributeError):
            element.text = "b"  # type: ignore[misc]
