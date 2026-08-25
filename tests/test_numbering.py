"""Numérotation « page x sur y »."""

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from reportlab_layout import NumberedCanvas, make_stylesheet


def build(path, pages: int) -> PdfReader:
    style = make_stylesheet()["Normal"]
    story = []
    for number in range(pages):
        story.append(Paragraph(f"Contenu de la page {number + 1}", style))
        if number < pages - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=(210 * mm, 297 * mm)).build(story, canvasmaker=NumberedCanvas)
    return PdfReader(str(path))


class TestNumberedCanvas:
    @pytest.mark.parametrize("pages", [1, 2, 5])
    def test_page_count_is_preserved(self, tmp_path, pages):
        assert len(build(tmp_path / "n.pdf", pages).pages) == pages

    def test_last_page_is_numbered(self, tmp_path):
        """La recette d'origine perd la dernière page : elle n'est jamais rejouée."""
        reader = build(tmp_path / "n.pdf", 3)
        assert "Page 3 sur 3" in reader.pages[2].extract_text()

    def test_total_is_the_same_on_every_page(self, tmp_path):
        reader = build(tmp_path / "n.pdf", 4)
        for index in range(4):
            assert "sur 4" in reader.pages[index].extract_text()

    def test_folio_label_is_overridable(self, tmp_path):
        class Folio(NumberedCanvas):
            folio_label = staticmethod(lambda page, total: f"{page}/{total}")

        style = make_stylesheet()["Normal"]
        SimpleDocTemplate(str(tmp_path / "f.pdf")).build([Paragraph("Bonjour", style)], canvasmaker=Folio)
        assert "1/1" in PdfReader(str(tmp_path / "f.pdf")).pages[0].extract_text()


class TestDirectCanvasUse:
    def test_last_page_survives_without_a_doctemplate(self, tmp_path):
        """Le canvas utilisé seul ne passe pas de showPage final : la page compte."""
        path = tmp_path / "direct.pdf"
        canvas = NumberedCanvas(str(path))
        canvas.drawString(50, 50, "Page une")
        canvas.showPage()
        canvas.drawString(50, 50, "Page deux")
        canvas.save()
        reader = PdfReader(str(path))
        assert len(reader.pages) == 2
        assert "Page 2 sur 2" in reader.pages[1].extract_text()
