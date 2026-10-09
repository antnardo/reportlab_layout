"""Paragraphs that carry more than text: inline images, and a tag on the last line.

:class:`InlineParagraph` fixes the first line. With ``autoLeading`` on, reportlab
makes each line as tall as what it holds -- an inline image, a larger font -- but
it still hangs the first baseline one type size below the top of the block,
whatever that line holds. A formula on the first line therefore sticks out above
the paragraph by its extra height and overprints the block above, while the same
amount is left empty at the bottom. The fix lowers the whole paragraph by that
amount when it draws; an ordinary paragraph, whose first line is no taller than
its type size, is drawn exactly as reportlab draws it.

It also measures again the lines that start with an image. When a wrap puts an
image at the head of a line, reportlab's ``breakLines`` (4.x as 5.0) stores the
image's extent in two local variables instead of the line's: the line keeps the
ascent and descent of its font, and a formula there overprints the line above or
the block below. Each line's extent is recomputed from its words, as reportlab
computes it for the others; a line without an image comes out unchanged.

:class:`TaggedParagraph` sets a tag flush right on the last line, as LaTeX does
with ``\\hfill`` at the end of a paragraph: the points of an exam question, a
reference, a page number. When the last line has no room left for it, the tag
goes on a line of its own, still flush right. reportlab has no such thing:
``endDots`` fills the line with leaders but carries no text, and a separate
right-aligned paragraph always costs a line.

Both stay ``Paragraph`` objects: they wrap, split across frames and columns, and
take every placement option of :meth:`~reportlab_layout.PDFMaker.draw`. When a
tagged paragraph splits, the tag goes with its last part.

The tag is placed with reportlab's own line arithmetic, read back from the
wrapped lines: the text is meant to be aligned left or justified, since a
centred or right-aligned last line has no free end.
"""

from itertools import pairwise
from typing import Any

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import getAscentDescent
from reportlab.platypus import Paragraph
from reportlab.platypus import paragraph as platypus_paragraph
from reportlab.platypus.paragraph import imgNormV, imgVRange

from reportlab_layout.pdfpages import pdf_placeholders

__all__ = ["InlineParagraph", "TaggedParagraph"]


def _auto_leading(paragraph: Paragraph) -> str:
    return getattr(paragraph, "autoLeading", getattr(paragraph.style, "autoLeading", "")) or ""


def _first_drop(paragraph: Paragraph) -> float:
    """How far below the top of the block reportlab puts the first baseline."""
    first = paragraph.blPara.lines[0] if paragraph.blPara.kind else paragraph.blPara
    if platypus_paragraph.paraFontSizeHeightOffset:
        return float(first.fontSize)
    return float(getattr(first, "ascent", first.fontSize))


def _line_extents(paragraph: Paragraph) -> list[tuple[float, float]]:
    """The ascent and descent reportlab gives each line of a wrapped paragraph.

    With ``autoLeading``, a line is as tall as what it holds, but never less
    than the leading, split five sixths above the baseline and one sixth below
    (``_putFragLine``). Without it, every line is one leading.
    """
    blpara = paragraph.blPara
    leading = paragraph.style.leading
    auto = _auto_leading(paragraph)
    if blpara.kind and auto in ("max", "min"):
        extents = []
        for line in blpara.lines:
            if auto == "max":
                extents.append((max(5 * leading / 6, line.ascent), max(leading / 6, -line.descent)))
            else:
                extents.append((float(line.ascent), float(-line.descent)))
        return extents
    if not blpara.kind and auto == "max":
        leading = max(leading, blpara.ascent - blpara.descent)
    elif not blpara.kind and auto == "min":
        leading = blpara.ascent - blpara.descent
    drop = _first_drop(paragraph)
    return [(drop, leading - drop)] * len(blpara.lines)


def _measure(line: Any) -> None:
    """Set a wrapped line's ascent and descent from its words, images included."""
    ascent = descent = None
    for frag in line.words:
        definition = getattr(frag, "cbDefn", None)
        if definition is not None:
            if getattr(definition, "kind", None) != "img":
                continue  # an anchor or a callback takes no room
            bottom, top = imgVRange(
                imgNormV(definition.height, frag.fontSize), definition.valign, frag.fontSize
            )
        else:
            top, bottom = getAscentDescent(frag.fontName, frag.fontSize)
        ascent = top if ascent is None else max(ascent, top)
        descent = bottom if descent is None else min(descent, bottom)
    if ascent is not None and descent is not None:
        line.ascent, line.descent = ascent, descent


class InlineParagraph(Paragraph):
    """A ``Paragraph`` whose lines leave room for the images they hold.

    Use it with ``autoLeading="max"`` whenever the text holds inline images
    (see :func:`~reportlab_layout.inline_image`) or changes size: a tall first
    line then lowers the paragraph instead of overprinting the block above, and
    a line that starts with an image is as tall as the image. It also draws the
    PDF pages of :func:`~reportlab_layout.inline_pdf`, which a plain
    ``Paragraph`` cannot.
    """

    def drawOn(self, canvas: Any, x: float, y: float, _sW: float = 0) -> None:  # noqa: N802, N803 - reportlab's names
        with pdf_placeholders(canvas):
            super().drawOn(canvas, x, y, _sW)

    def breakLines(self, width: Any) -> Any:  # noqa: N802 - reportlab's name
        lines = super().breakLines(width)
        if lines.kind and _auto_leading(self) in ("max", "min"):
            for line in lines.lines:
                _measure(line)
        return lines

    def _first_line_shift(self) -> float:
        if not self.blPara.lines or not self.blPara.kind or _auto_leading(self) not in ("max", "min"):
            return 0.0
        ascent = _line_extents(self)[0][0]
        return max(0.0, ascent - _first_drop(self))

    def baselines(self) -> list[float]:
        """The baseline of every line, as drawn, above the bottom of the block.

        Only meaningful once the paragraph is wrapped.
        """
        extents = _line_extents(self)
        if not extents:
            return []
        first = self.height - _first_drop(self) - self._first_line_shift()
        found = [first]
        for (_, descent), (ascent, _) in pairwise(extents):
            found.append(found[-1] - descent - ascent)
        return found

    def draw(self) -> None:
        shift = self._first_line_shift()
        if not shift:
            super().draw()
            return
        self.canv.saveState()
        self.canv.translate(0, -shift)
        try:
            super().draw()
        finally:
            self.canv.restoreState()


class TaggedParagraph(InlineParagraph):
    """A paragraph with a tag set flush right on its last line.

    :param text: the paragraph's markup, as for ``Paragraph``.
    :param style: its style.
    :param tag: the tag's markup; empty, the paragraph is an ordinary one.
    :param tag_style: the tag's style; by default the paragraph's.
    :param gap: the least room between the text and the tag, in points; by
        default half the type size. With less room than that on the last line,
        the tag goes on a line of its own.
    """

    def __init__(
        self,
        text: str | None,
        style: ParagraphStyle | None = None,
        tag: str = "",
        tag_style: ParagraphStyle | None = None,
        *,
        gap: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(text, style, **kwargs)
        # The tag is one flush-right word: none of the paragraph's indents or spacing.
        tag_base = tag_style or self.style
        bare = ParagraphStyle(
            f"{tag_base.name}-tag",
            parent=tag_base,
            leftIndent=0,
            rightIndent=0,
            firstLineIndent=0,
            bulletIndent=0,
            spaceBefore=0,
            spaceAfter=0,
            alignment=TA_LEFT,
        )
        self._tag = Paragraph(tag, bare) if tag else None
        self._gap = 0.5 * self.style.fontSize if gap is None else gap
        self._tag_width = 0.0
        self._tag_line = 0.0  # height of the line added for the tag, 0 on the last line

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # noqa: N803 - reportlab's names
        width, height = super().wrap(availWidth, availHeight)
        self._tag_line = 0.0
        if self._tag is None or not self.blPara.lines:
            return width, height
        room = availWidth - self.style.leftIndent - self.style.rightIndent
        _, tag_height = self._tag.wrap(room, availHeight)
        self._tag_width = min(room, max(self._tag.getActualLineWidths0()))
        last = self.blPara.lines[-1]
        free = last.extraSpace if self.blPara.kind else last[0]
        if free < self._tag_width + self._gap:
            self._tag_line = max(tag_height, self.style.leading)
            self.height = height + self._tag_line
        return width, self.height

    def split(self, availWidth: float, availHeight: float) -> list[Any]:  # noqa: N803 - reportlab's names
        parts = super().split(availWidth, availHeight)
        if len(parts) > 1 and self._tag is not None:
            last = parts[-1]
            if not isinstance(last, TaggedParagraph):
                return parts
            last._tag, last._gap = self._tag, self._gap
        return parts

    def tag_bottom(self) -> float:
        """The bottom of the tag's box, above the bottom of the block.

        On the last line, the tag stands on its baseline; on a line of its own,
        it fills the bottom of the block.
        """
        tag = self._tag
        if tag is None:
            raise ValueError("This paragraph has no tag")
        if self._tag_line:
            return self._tag_line - tag.height
        return self.baselines()[-1] - (tag.height - _first_drop(tag))

    def draw(self) -> None:
        if self._tag is None:
            super().draw()
            return
        text_height = self.height - self._tag_line
        self.canv.saveState()
        self.canv.translate(0, self._tag_line)
        self.height = text_height
        try:
            super().draw()
        finally:
            self.height = text_height + self._tag_line
            self.canv.restoreState()
        x = self.width - self.style.rightIndent - self._tag_width
        self._tag.drawOn(self.canv, x, self.tag_bottom())
