"""A formula composer built on texformules: the formulas typeset by LaTeX, in one batch.

:meth:`~reportlab_layout.PDFMaker.draw_markdown` typesets nothing itself: it hands
its formulas to a composer. :class:`TexFormulas` is one, built on **texformules**,
which typesets every missing formula of the text with a real LaTeX and the preamble
you give it, in a single compilation, and keeps each one in a cache as a one-page
PDF and a PNG, with its baseline. **latexdetok** explains a formula LaTeX refused:
an unclosed brace, a ``\\frac`` missing an argument, at the place it occurs.

Both come with the ``texformules`` extra, which needs Python 3.13 or later and a TeX
distribution (lualatex or pdflatex) on the ``PATH``. Without TeX, every formula is
refused, with the reason, and written as it stands.

    from reportlab_layout.texmath import TexFormulas

    formulas = TexFormulas(preamble=r"\\usepackage{amsmath,siunitx}")
    doc.draw_markdown(text, formulas=formulas)

Each formula is read by latexdetok before it goes to LaTeX: one whose ``$`` or brace
is left open is refused there, with what latexdetok saw, since it would swallow the
rest of the batch. ``$$…$$`` is set in ``\\displaystyle``. A formula is one line of
the batch, so the lines of a displayed formula are joined, their ``%`` comments
removed.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab_layout.markdown import MathFragment

try:
    from latexdetok import TexFile, check
    from texformules import BP_PER_PT, FormulaBook, default_cache, split
except ImportError as error:  # pragma: no cover - depends on the installation
    raise ImportError(
        'TexFormulas needs texformules and latexdetok: pip install "reportlab_layout[texformules]"'
    ) from error

__all__ = ["TexFormulas", "TexMath"]

_COMMENT = re.compile(r"(?<!\\)%.*$")


@dataclass(frozen=True, slots=True)
class TexMath:
    """A formula as :class:`TexFormulas` returns it: see :class:`~reportlab_layout.TypesetMath`."""

    file: Path | None
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    size: float = 10.0
    error: str | None = None


class TexFormulas:
    """Typesets the formulas of a text with texformules, all of them in one compilation.

    :param book: the ``FormulaBook`` to typeset with; by default one on
        ``default_cache()`` built with ``options``.
    :param vector: hand over the one-page PDF, laid down as vector drawing
        (``reportlab_layout[pdf]``); ``False`` hands over the PNG.
    :param options: ``FormulaBook``'s keywords, when ``book`` is not given:
        ``preamble``, ``engine``, ``size``, ``dpi``…
    """

    def __init__(self, book: FormulaBook | None = None, *, vector: bool = True, **options: Any) -> None:
        if book is not None and options:
            raise TypeError("Give a FormulaBook or its options, not both")
        self.book = book if book is not None else FormulaBook(default_cache(), **options)
        self.vector = vector

    @staticmethod
    def source(fragment: MathFragment) -> str:
        """What texformules typesets for a fragment: one line, dollars included."""
        lines = (_COMMENT.sub("", line).strip() for line in fragment.latex.splitlines())
        latex = " ".join(line for line in lines if line)
        dollars = "$$" if fragment.display else "$"
        return f"{dollars}{latex}{dollars}"

    def __call__(self, fragments: Sequence[MathFragment]) -> list[TexMath]:
        vetted = [self.vet(self.source(fragment)) for fragment in fragments]
        formulas = self.book.render(latex for latex, _ in vetted if latex is not None)
        return [
            TexMath(None, error=problem) if latex is None else self._result(latex, formulas.get(latex))
            for latex, problem in vetted
        ]

    @staticmethod
    def vet(source: str) -> tuple[str | None, str | None]:
        """The formula as texformules typesets it, or why it is not sent to LaTeX.

        texformules reads it with latexdetok first (``split``): a ``$`` or a brace
        left open would swallow the rest of the batch, and every formula with it.
        ``$$…$$`` comes back as ``$\\displaystyle …$``.
        """
        fragments = split(source)
        if len(fragments) == 1 and fragments[0].latex:
            return fragments[0].text, None
        messages = [problem.message for fragment in fragments for problem in fragment.problems]
        return None, "; ".join(dict.fromkeys(messages)) or "not read as a single formula"

    def _result(self, source: str, formula: Any) -> TexMath:
        if formula is None or not formula.ok:
            return TexMath(None, error=self.explain(source, None if formula is None else formula.error))
        first, second = (self.book.pdf, self.book.image) if self.vector else (self.book.image, self.book.pdf)
        file = first(formula.key) or second(formula.key)
        if file is None:
            return TexMath(None, error="typeset, but its file is missing from the cache")
        box = formula.pdf_box
        return TexMath(file, box.width, box.height, box.depth, formula.size * BP_PER_PT)

    @staticmethod
    def explain(source: str, error: str | None) -> str:
        """Why LaTeX refused a formula: what latexdetok sees wrong in it, then LaTeX's own message."""
        tex = TexFile([source + "\n"])
        try:
            found = [diagnostic.message for diagnostic in check(tex, follow_inputs=False)]
        except Exception:  # pragma: no cover - a reader's failure must not hide LaTeX's message
            found = []
        said = error or "rejected by LaTeX"
        return "; ".join(dict.fromkeys(found)) + f" (LaTeX: {said})" if found else said
