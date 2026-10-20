"""The texformules composer: one batch, the file and box it hands over, the reasons for a refusal."""

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("texformules")
pytest.importorskip("latexdetok")

from texformules import BP_PER_PT, PdfBox

from reportlab_layout import MathFragment
from reportlab_layout.texmath import TexFormulas


@dataclass
class Formula:
    source: str
    key: str
    ok: bool = True
    error: str | None = None
    size: float = 10.0

    @property
    def pdf_box(self) -> PdfBox:
        return PdfBox(30.0, 12.0, 3.0)


class Book:
    """A FormulaBook's interface: refuses what holds ``\\oops``, keeps a PDF and a PNG of the rest."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.batches: list[list[str]] = []

    def render(self, sources):
        batch = list(sources)
        self.batches.append(batch)
        found = {}
        for rank, source in enumerate(batch):
            if "\\oops" in source:
                found[source] = Formula(source, "", ok=False, error="Undefined control sequence.")
                continue
            key = f"{rank:024x}"
            (self.folder / f"{key}.pdf").write_bytes(b"%PDF-1.4")
            (self.folder / f"{key}.png").write_bytes(b"png")
            found[source] = Formula(source, key)
        return found

    def pdf(self, key):
        path = self.folder / f"{key}.pdf"
        return path if path.is_file() else None

    def image(self, key):
        path = self.folder / f"{key}.png"
        return path if path.is_file() else None


@pytest.fixture
def book(tmp_path: Path) -> Book:
    return Book(tmp_path)


def test_one_batch_for_all_the_formulas(book):
    results = TexFormulas(book)([MathFragment("a", False), MathFragment("b", True)])
    assert book.batches == [["$a$", "$\\displaystyle b$"]]
    assert [result.file.suffix for result in results] == [".pdf", ".pdf"]


def test_the_box_is_in_pdf_points(book):
    [result] = TexFormulas(book)([MathFragment("a", False)])
    assert (result.width, result.height, result.depth) == (30.0, 12.0, 3.0)
    assert result.size == pytest.approx(10 * BP_PER_PT)
    assert result.error is None


def test_the_png_on_request(book):
    [result] = TexFormulas(book, vector=False)([MathFragment("a", False)])
    assert result.file.suffix == ".png"


def test_a_displayed_formula_is_one_line_without_its_comments():
    fragment = MathFragment("\n  a = b % the first\n\n  + c \\% d\n", True)
    assert TexFormulas.source(fragment) == "$$a = b + c \\% d$$"


def test_an_open_brace_never_reaches_latex(book):
    [result] = TexFormulas(book)([MathFragment("\\frac{1}{2", False)])
    assert book.batches == [[]]
    assert result.file is None
    assert "never closed" in result.error


def test_latex_says_why_it_refused(book):
    [result] = TexFormulas(book)([MathFragment("\\oops", False)])
    assert result.file is None
    assert result.error == "Undefined control sequence."


def test_a_book_or_its_options():
    with pytest.raises(TypeError):
        TexFormulas(object(), preamble="")


@pytest.mark.skipif(shutil.which("lualatex") is None and shutil.which("pdflatex") is None, reason="no LaTeX")
def test_with_latex(tmp_path):
    from texformules import FormulaBook

    composer = TexFormulas(FormulaBook(tmp_path))
    good, bad = composer([MathFragment("\\frac{a}{b}", True), MathFragment("\\oops", False)])
    assert good.file.read_bytes().startswith(b"%PDF")
    assert good.depth > 0
    assert bad.file is None
    assert "Undefined control sequence" in bad.error
