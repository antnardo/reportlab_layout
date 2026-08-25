"""Font metrics: width, ascent, descent, baseline.

This is where vertical text placement is decided. A string drawn by
``canvas.drawString(x, y, text)`` has its **baseline** at ``y``; descenders hang
below that line. To centre a string vertically in a box whose middle sits at
``y_center``, the baseline belongs at

    y_center - (ascent + descent) / 2

and not at ``y_center - height / 2`` with ``height = ascent - descent``. Since
the descent is negative, that second formula drops the text by ``|descent|`` too
much, roughly 20% of the type size.
"""

from dataclasses import dataclass

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
    "string_width",
]

#: Vertical anchors accepted by :meth:`TextMetrics.baseline`.
VALIGNS = ("baseline", "middle", "cap", "top", "bottom")

#: Horizontal anchors accepted by :meth:`TextMetrics.left_edge`.
HALIGNS = ("left", "center", "right")

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


def string_width(text: str, style: ParagraphStyle, scale: float = 1.0) -> float:
    """Width of ``text`` rendered with ``style`` at ``scale``."""
    return TextMetrics(style, scale).width(text)


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
