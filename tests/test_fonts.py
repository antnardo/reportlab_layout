"""TrueType families: registration, fallbacks, and the markup that switches faces."""

import itertools
import logging
from pathlib import Path

import pytest
import reportlab
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph

from reportlab_layout import PDFMaker, register_font_family

#: The Bitstream Vera faces reportlab ships with its tests, in all four styles.
VERA = Path(reportlab.__file__).parent / "fonts"

_names = itertools.count()


@pytest.fixture
def family() -> str:
    """A family name no other test has registered: the registry is global."""
    return f"TestVera{next(_names)}"


def register_vera(name: str, **faces: bool) -> str:
    files = {"bold": "VeraBd.ttf", "italic": "VeraIt.ttf", "bold_italic": "VeraBI.ttf"}
    chosen = {face: VERA / files[face] for face, wanted in faces.items() if wanted}
    return register_font_family(name, VERA / "Vera.ttf", **chosen)


def vera_faces(path: Path) -> set[str]:
    """The Vera faces a page embeds; the canvas also arms Helvetica on its own."""
    page = PdfReader(str(path)).pages[0]
    names = {str(font["/BaseFont"]).split("+")[-1] for font in page["/Resources"]["/Font"].values()}
    return {name for name in names if "Vera" in name}


class TestRegisterFontFamily:
    def test_returns_the_name_to_put_in_a_style(self, family):
        assert register_vera(family, bold=True, italic=True, bold_italic=True) == family
        assert family + "-BoldItalic" in pdfmetrics.getRegisteredFontNames()

    def test_bold_and_italic_markup_switch_faces(self, family, out):
        register_vera(family, bold=True, italic=True, bold_italic=True)
        style = ParagraphStyle("body", fontName=family, fontSize=11)
        with PDFMaker(out) as doc:
            doc.draw(Paragraph("plain <b>bold</b> <i>italic</i> <b><i>both</i></b>", style))
        assert vera_faces(out) == {
            "BitstreamVeraSans-Roman",
            "BitstreamVeraSans-Bold",
            "BitstreamVeraSans-Oblique",
            "BitstreamVeraSans-BoldOblique",
        }

    def test_missing_faces_fall_back_on_the_regular(self, family, out):
        register_vera(family)
        style = ParagraphStyle("body", fontName=family, fontSize=11)
        with PDFMaker(out) as doc:
            doc.draw(Paragraph("plain <b>bold</b> <i>italic</i>", style))
        assert vera_faces(out) == {"BitstreamVeraSans-Roman"}

    def test_bold_italic_falls_back_on_the_bold(self, family, out):
        register_vera(family, bold=True)
        style = ParagraphStyle("body", fontName=family, fontSize=11)
        with PDFMaker(out) as doc:
            doc.draw(Paragraph("<b><i>both</i></b>", style))
        assert vera_faces(out) == {"BitstreamVeraSans-Bold"}

    def test_letters_beyond_latin_1_are_drawn_and_extracted(self, family, out):
        register_vera(family)
        with PDFMaker(out) as doc:
            doc.draw_string("Łódka", 50, 700, style=ParagraphStyle("pl", fontName=family, fontSize=12))
        assert "Łódka" in PdfReader(str(out)).pages[0].extract_text()

    def test_registering_again_with_the_same_files_does_nothing(self, family):
        register_vera(family, bold=True)
        assert register_vera(family, bold=True) == family

    def test_registering_again_with_other_files_is_refused(self, family):
        register_vera(family, bold=True)
        with pytest.raises(ValueError, match="already registered"):
            register_vera(family, italic=True)

    def test_a_missing_file_is_refused(self, family, tmp_path):
        with pytest.raises(FileNotFoundError):
            register_font_family(family, tmp_path / "absent.ttf")

    def test_a_standard_font_name_is_refused(self):
        with pytest.raises(ValueError, match="shadow"):
            register_font_family("Helvetica", VERA / "Vera.ttf")

    def test_a_face_without_cap_height_is_reported(self, family, caplog):
        # Vera's OS/2 table predates the cap height: reportlab falls back on the ascent.
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.fonts"):
            register_vera(family)
        assert "no cap height of its own" in caplog.text
