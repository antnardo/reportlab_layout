"""Drawing plain strings, anchored and optionally rotated.

A single method, :meth:`TextPainter.draw`, replaces the half-dozen
``drawStringCenterH`` / ``...CenterHV`` / ``...LeftCenterV`` variants everyone
ends up writing. The anchor is described by two words -- ``halign`` and
``valign`` -- and working out the baseline is delegated to
:class:`~reportlab_layout.metrics.TextMetrics`, which accounts for scale.

For text that needs to wrap, use a ``Paragraph`` and place it with
``PDFMaker.draw_paragraph``: here the string is drawn as it comes.
"""

from reportlab.lib.styles import StyleSheet1
from reportlab.pdfgen.canvas import Canvas

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.styles import StyleLike, resolve_style

__all__ = ["TextPainter"]


class TextPainter:
    """Draws text strings on a canvas, with an explicit anchor."""

    def __init__(self, canvas: Canvas, stylesheet: StyleSheet1 | None = None) -> None:
        self._canvas = canvas
        self._stylesheet = stylesheet

    def metrics(self, style: StyleLike, scale: float = 1.0) -> TextMetrics:
        """Metrics for the requested style, at the requested scale."""
        return TextMetrics(resolve_style(style, self._stylesheet), scale)

    def draw(
        self,
        text: str,
        x: float,
        y: float,
        *,
        style: StyleLike = None,
        scale: float = 1.0,
        color: ColorLike = "black",
        halign: str = "left",
        valign: str = "baseline",
        angle: float = 0,
        outline: float = 0,
        dx: float = 0,
        dy: float = 0,
    ) -> Box:
        """Draw ``text``, anchoring point ``(x, y)`` per ``halign``/``valign``.

        ``halign`` is ``"left"``, ``"center"`` or ``"right"``; ``valign`` is
        ``"baseline"``, ``"middle"``, ``"cap"``, ``"top"`` or ``"bottom"``.
        ``dx``/``dy`` nudge the drawing after anchoring, for optical
        corrections -- but a constant ``dy`` almost always means the anchor is
        wrong: ``"cap"`` centres short labels with no nudging at all.

        ``color`` defaults to black rather than to whatever fill colour the
        canvas happens to carry: text that silently inherits the fill left by
        the last rectangle is a classic way to draw white on white. Pass
        ``color=None`` to deliberately keep the current colour.

        ``angle`` rotates the text about the anchor point, counterclockwise:
        ``90`` reads bottom-to-top.

        ``outline`` strokes the glyphs as well as filling them, the stroke that
        many points wide: a faux bold, for a family that has no bold face of its
        own. 0.4 pt is about right at text sizes. The stroke takes ``color`` too,
        so the glyphs thicken rather than gain an outline of another colour;
        with ``color=None`` the canvas's own stroke colour applies. A real bold
        face beats this whenever there is one -- the strokes of a drawn bold are
        not all thickened equally, and its shapes differ.

        Returns the em box the string occupies, which is the metric box: the
        advance width and the em height, neither of them counting the half
        ``outline`` the stroke adds all round. With a non-zero ``angle`` that
        box is the one **before** rotation, relative to the translated anchor.
        """
        metrics = self.metrics(style, scale)
        left = metrics.left_edge(0 if angle else x, text, halign) + dx
        baseline = metrics.baseline(0 if angle else y, valign) + dy

        canvas = self._canvas
        canvas.saveState()
        if angle:
            canvas.translate(x, y)
            canvas.rotate(angle)
        canvas.setFont(metrics.font_name, metrics.font_size)
        if (fill := to_color(color)) is not None:
            canvas.setFillColor(fill)
        if outline > 0:
            # Render mode 2 fills then strokes each glyph. drawString cannot ask
            # for it; only a text object can.
            canvas.setLineWidth(outline)
            if fill is not None:
                canvas.setStrokeColor(fill)
            text_object = canvas.beginText(left, baseline)
            text_object.setFont(metrics.font_name, metrics.font_size)
            text_object.setTextRenderMode(2)
            text_object.textOut(text)
            canvas.drawText(text_object)
        else:
            canvas.drawString(left, baseline, text)
        canvas.restoreState()

        return Box(left, baseline + metrics.descent, metrics.width(text), metrics.height)
