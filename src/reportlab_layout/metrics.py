"""Font metrics: width, ascent, descent, baseline.

This is where vertical text placement is decided. A string drawn by
``canvas.drawString(x, y, text)`` has its **baseline** at ``y``; descenders hang
below that line. To centre a string vertically in a box whose middle sits at
``y_center``, the baseline belongs at

    y_center - (ascent + descent) / 2

and not at ``y_center - height / 2`` with ``height = ascent - descent``. Since
the descent is negative, that second formula drops the text by ``|descent|`` too
much, roughly 20% of the type size.

Cutting a text into lines is measured here too, for the box drawn around it
before the text itself. reportlab's ``simpleSplit`` does it, but breaks at any
whitespace: a no-break space -- the one French puts before a colon, or between a
number and its unit -- becomes a line break, and comes back an ordinary space. It
also drops blank lines. :meth:`TextMetrics.lines` breaks where a ``Paragraph``
breaks, and keeps both.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Self

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import getAscentDescent, getFont, stringWidth

__all__ = [
    "STANDARD_CAP_HEIGHTS",
    "TextMetrics",
    "baseline_offset",
    "cap_height",
    "font_ascent",
    "font_descent",
    "font_height",
    "split_lines",
    "string_width",
]

#: Vertical anchors accepted by :meth:`TextMetrics.baseline`.
VALIGNS = ("baseline", "middle", "cap", "top", "bottom")

#: Horizontal anchors accepted by :meth:`TextMetrics.left_edge`.
HALIGNS = ("left", "center", "right")

#: The whitespace a line may break at: all of it but the no-break spaces --
#: U+00A0, the figure space U+2007 and the narrow U+202F -- which a
#: ``Paragraph`` keeps whole as well.
_BREAKS = re.compile(r"[^\S\u00a0\u2007\u202f]+")

#: Cap heights of the standard PostScript fonts, in thousandths of an em, as
#: published by Adobe in their AFM files. reportlab does not expose this metric
#: for these fonts: it only gives the ascent, which equals the cap height for
#: Helvetica but not for Times or Courier. Symbol and ZapfDingbats are left out
#: on purpose: their AFM declares a cap height of zero, which means nothing for
#: centring.
STANDARD_CAP_HEIGHTS = {
    "Courier": 562,
    "Courier-Bold": 562,
    "Courier-Oblique": 562,
    "Courier-BoldOblique": 562,
    "Helvetica": 718,
    "Helvetica-Bold": 718,
    "Helvetica-Oblique": 718,
    "Helvetica-BoldOblique": 718,
    "Times-Roman": 662,
    "Times-Bold": 676,
    "Times-Italic": 653,
    "Times-BoldItalic": 676,
}


@dataclass(frozen=True, slots=True)
class TextMetrics:
    """The metrics of a style, optionally scaled.

    ``scale`` multiplies the style's type size. Every metric exposed here
    accounts for it, which is the whole point of this class. Measuring a string
    at the nominal size and then drawing it at ``scale = 0.5`` gets the centring
    wrong by a factor of two.
    """

    style: ParagraphStyle
    scale: float = 1.0

    @classmethod
    def of_font(cls, font_name: str, font_size: float) -> Self:
        """The metrics of a font at a size, for code that keeps the two apart.

        Measuring is all a style is needed for here, so this one is made on the
        spot -- and cached, a loop measuring each string does not build one each.
        """
        return cls(_font_style(font_name, font_size))

    @property
    def font_name(self) -> str:
        return self.style.fontName

    @property
    def font_size(self) -> float:
        """Effective type size, scale included."""
        return self.style.fontSize * self.scale

    @property
    def leading(self) -> float:
        """Effective leading, scale included."""
        return (self.style.leading or 1.2 * self.style.fontSize) * self.scale

    @property
    def ascent(self) -> float:
        """Height above the baseline, positive."""
        return getAscentDescent(self.font_name, self.font_size)[0]

    @property
    def descent(self) -> float:
        """Depth below the baseline, **negative**."""
        return getAscentDescent(self.font_name, self.font_size)[1]

    @property
    def height(self) -> float:
        """Height of the em box: ``ascent - descent``."""
        ascent, descent = getAscentDescent(self.font_name, self.font_size)
        return ascent - descent

    @property
    def cap_height(self) -> float:
        """Height of the capitals above the baseline, in points.

        Read from :data:`STANDARD_CAP_HEIGHTS` for the standard PostScript
        fonts, otherwise from the font itself when it declares one (TrueType),
        otherwise falling back to the ascent -- exact for Helvetica-like faces,
        about 3% generous for Times.
        """
        if (published := STANDARD_CAP_HEIGHTS.get(self.font_name)) is not None:
            return published / 1000 * self.font_size
        face = getFont(self.font_name).face
        declared = getattr(face, "capHeight", None)
        if declared:
            return declared / 1000 * self.font_size
        return self.ascent

    @property
    def cap_offset(self) -> float:
        """Distance from the middle of the cap box down to the baseline.

        Subtract it from the ordinate you are aiming at to centre a short label
        optically -- a table cell, a banner title -- inside its box. Unlike
        em-box centring it does not reserve room for descenders, which keeps the
        result steady from one label to the next whether or not it has any.
        """
        return self.cap_height / 2

    @property
    def baseline_offset(self) -> float:
        """Distance from the middle of the em box down to the baseline.

        Subtract it from the ordinate you are aiming at to get the baseline of
        vertically centred text.
        """
        ascent, descent = getAscentDescent(self.font_name, self.font_size)
        return (ascent + descent) / 2

    def width(self, text: str) -> float:
        """Width of ``text`` at the effective type size."""
        return stringWidth(text, self.font_name, self.font_size)

    def lines(self, text: str, width: float) -> list[str]:
        """The lines ``text`` breaks into at ``width`` points, ready for ``draw_string``.

        A line breaks at a space, a tab or a newline, never at a no-break space,
        which stays in the line as it was. A newline always breaks, and an empty
        line stays, as an empty string; runs of spaces count as one, and the
        ends of a line lose theirs. A word wider than ``width`` takes a line of
        its own and overflows it: the widest line, not ``width``, is how wide
        the text is drawn. An empty text has no line.
        """
        result: list[str] = []
        for paragraph in text.splitlines():
            line = ""
            for word in _BREAKS.split(paragraph):
                if not word:
                    continue
                longer = f"{line} {word}" if line else word
                if line and self.width(longer) > width:
                    result.append(line)
                    line = word
                else:
                    line = longer
            result.append(line)
        return result

    def baseline(self, y: float, valign: str = "baseline") -> float:
        """The baseline ordinate for a given vertical anchor.

        ``baseline``: ``y`` already is the baseline.
        ``middle``: ``y`` is the middle of the em box, descender room included.
        ``cap``: ``y`` is the middle of the cap box -- the optical centring of a
        short label.
        ``top``: ``y`` is the top of the em box.
        ``bottom``: ``y`` is the bottom of the em box.
        """
        if valign == "baseline":
            return y
        if valign == "middle":
            return y - self.baseline_offset
        if valign == "cap":
            return y - self.cap_offset
        if valign == "top":
            return y - self.ascent
        if valign == "bottom":
            return y - self.descent
        raise ValueError(f"valign must be one of {VALIGNS}, got {valign!r}")

    def left_edge(self, x: float, text: str, halign: str = "left") -> float:
        """Where the drawing starts, for a given horizontal anchor."""
        if halign == "left":
            return x
        if halign == "center":
            return x - self.width(text) / 2
        if halign == "right":
            return x - self.width(text)
        raise ValueError(f"halign must be one of {HALIGNS}, got {halign!r}")


@lru_cache(maxsize=256)
def _font_style(font_name: str, font_size: float) -> ParagraphStyle:
    return ParagraphStyle(f"{font_name} {font_size}", fontName=font_name, fontSize=font_size)


def string_width(text: str, style: ParagraphStyle, scale: float = 1.0) -> float:
    """Width of ``text`` rendered with ``style`` at ``scale``."""
    return TextMetrics(style, scale).width(text)


def split_lines(text: str, style: ParagraphStyle, width: float, scale: float = 1.0) -> list[str]:
    """The lines of ``text`` at ``width`` points; see :meth:`TextMetrics.lines`."""
    return TextMetrics(style, scale).lines(text, width)


def font_ascent(style: ParagraphStyle, scale: float = 1.0) -> float:
    """The style's ascent, in points."""
    return TextMetrics(style, scale).ascent


def font_descent(style: ParagraphStyle, scale: float = 1.0) -> float:
    """The style's descent, in points (a negative value)."""
    return TextMetrics(style, scale).descent


def font_height(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Height of the style's em box, in points."""
    return TextMetrics(style, scale).height


def baseline_offset(style: ParagraphStyle, scale: float = 1.0) -> float:
    """What to subtract from the target centre to get the baseline."""
    return TextMetrics(style, scale).baseline_offset


def cap_height(style: ParagraphStyle, scale: float = 1.0) -> float:
    """The style's cap height, in points."""
    return TextMetrics(style, scale).cap_height
