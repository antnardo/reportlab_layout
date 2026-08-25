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
        color: ColorLike = None,
        halign: str = "left",
        valign: str = "baseline",
        angle: float = 0,
        dx: float = 0,
        dy: float = 0,
    ) -> Box:
        """Draw ``text``, anchoring point ``(x, y)`` per ``halign``/``valign``.

        ``halign`` is ``"left"``, ``"center"`` or ``"right"``; ``valign`` is
        ``"baseline"``, ``"middle"``, ``"cap"``, ``"top"`` or ``"bottom"``.
        ``dx``/``dy`` nudge the drawing after anchoring, for optical
        corrections -- but a constant ``dy`` almost always means the anchor is
        wrong: ``"cap"`` centres short labels with no nudging at all.

        ``angle`` rotates the text about the anchor point, counterclockwise:
        ``90`` reads bottom-to-top.

        Returns the em box the string occupies. With a non-zero ``angle`` that
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
        canvas.drawString(left, baseline, text)
        canvas.restoreState()

        return Box(left, baseline + metrics.descent, metrics.width(text), metrics.height)
