"""Page "x of y" numbering."""

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.units import inch, mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from reportlab_layout import NumberedCanvas, make_stylesheet


def build(path, pages: int) -> PdfReader:
    style = make_stylesheet()["Normal"]
    story = []
    for number in range(pages):
        story.append(Paragraph(f"Content of page {number + 1}", style))
        if number < pages - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=(210 * mm, 297 * mm)).build(story, canvasmaker=NumberedCanvas)
    return PdfReader(str(path))


class TestNumberedCanvas:
    @pytest.mark.parametrize("pages", [1, 2, 5])
    def test_page_count_is_preserved(self, tmp_path, pages):
        assert len(build(tmp_path / "n.pdf", pages).pages) == pages

    def test_last_page_is_numbered(self, tmp_path):
        """The original recipe loses the last page: it is never replayed."""
        reader = build(tmp_path / "n.pdf", 3)
        assert "Page 3 of 3" in reader.pages[2].extract_text()

    def test_total_is_the_same_on_every_page(self, tmp_path):
        reader = build(tmp_path / "n.pdf", 4)
        for index in range(4):
            assert "of 4" in reader.pages[index].extract_text()

    def test_folio_label_is_overridable(self, tmp_path):
        class Folio(NumberedCanvas):
            folio_label = staticmethod(lambda page, total: f"{page}/{total}")

        style = make_stylesheet()["Normal"]
        SimpleDocTemplate(str(tmp_path / "f.pdf")).build([Paragraph("Hello", style)], canvasmaker=Folio)
        assert "1/1" in PdfReader(str(tmp_path / "f.pdf")).pages[0].extract_text()


def folio_ends(path):
    """Where each page's folio ends, and its baseline: its start, read from the PDF, plus its width."""
    found = []
    for page in PdfReader(str(path)).pages:
        spots = []

        def record(text, cm, tm, font_dict, font_size, spots=spots):
            if text.strip().startswith("Page"):
                start = tm[4] * cm[0] + cm[4]
                spots.append((start + stringWidth(text.strip(), "Helvetica", 9), tm[5] * cm[3] + cm[5]))

        page.extract_text(visitor_text=record)
        found.extend(spots)
    return found


def numbered(path, pagesize, canvasmaker=NumberedCanvas):
    style = make_stylesheet()["Normal"]
    SimpleDocTemplate(str(path), pagesize=pagesize).build(
        [Paragraph("Hello", style)], canvasmaker=canvasmaker
    )
    return folio_ends(path)


class TestFolioPosition:
    @pytest.mark.parametrize("pagesize", [A4, letter, landscape(A4)], ids=["A4", "letter", "A4-landscape"])
    def test_folio_ends_15_mm_from_the_right_edge_of_any_page(self, tmp_path, pagesize):
        """Up to 1.5.0 it ended at 195 mm, whatever the page."""
        [(right, baseline)] = numbered(tmp_path / "n.pdf", pagesize)
        assert right == pytest.approx(pagesize[0] - 15 * mm, abs=0.01)
        assert baseline == pytest.approx(10 * mm, abs=0.01)

    def test_a4_portrait_keeps_its_folio_where_it_was(self, tmp_path):
        [(right, _)] = numbered(tmp_path / "n.pdf", A4)
        assert right == pytest.approx(195 * mm, abs=0.01)

    def test_inset_moves_the_folio_on_every_page_size(self, tmp_path):
        class Folio(NumberedCanvas):
            folio_inset = (inch, inch / 2)

        [(right, baseline)] = numbered(tmp_path / "n.pdf", letter, Folio)
        assert (right, baseline) == pytest.approx((letter[0] - inch, inch / 2), abs=0.01)

    def test_fixed_position_still_pins_the_folio(self, tmp_path):
        class Folio(NumberedCanvas):
            folio_position = (300, 40)

        [(right, baseline)] = numbered(tmp_path / "n.pdf", landscape(A4), Folio)
        assert (right, baseline) == pytest.approx((300, 40), abs=0.01)


class TestDirectCanvasUse:
    def test_last_page_survives_without_a_doctemplate(self, tmp_path):
        """Used on its own the canvas sends no final showPage: the page still counts."""
        path = tmp_path / "direct.pdf"
        canvas = NumberedCanvas(str(path))
        canvas.drawString(50, 50, "Page one")
        canvas.showPage()
        canvas.drawString(50, 50, "Page two")
        canvas.save()
        reader = PdfReader(str(path))
        assert len(reader.pages) == 2
        assert "Page 2 of 2" in reader.pages[1].extract_text()
