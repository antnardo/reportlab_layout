"""Tracé de chaînes simples, ancrées et éventuellement pivotées.

Une seule méthode, :meth:`TextPainter.draw`, remplace la demi-douzaine de
variantes ``drawStringCenterH`` / ``…CenterHV`` / ``…LeftCenterV`` que l'on
finit toujours par écrire. L'ancrage est décrit par deux mots — ``halign`` et
``valign`` — et le calcul de ligne de base est délégué à
:class:`~reportlab_layout.metrics.TextMetrics`, qui tient compte de l'échelle.

Pour du texte qui doit se retourner à la ligne, utiliser un ``Paragraph`` et le
placer avec ``PDFMaker.draw_paragraph`` : ici, la chaîne est tracée telle quelle.
"""

from reportlab.lib.styles import StyleSheet1
from reportlab.pdfgen.canvas import Canvas

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.styles import StyleLike, resolve_style

__all__ = ["TextPainter"]


class TextPainter:
    """Dessine des chaînes de texte sur un canvas, avec ancrage explicite."""

    def __init__(self, canvas: Canvas, stylesheet: StyleSheet1 | None = None) -> None:
        self._canvas = canvas
        self._stylesheet = stylesheet

    def metrics(self, style: StyleLike, scale: float = 1.0) -> TextMetrics:
        """Métriques du style demandé, à l'échelle demandée."""
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
        """Trace ``text`` en ancrant le point ``(x, y)`` selon ``halign``/``valign``.

        ``halign`` vaut ``"left"``, ``"center"`` ou ``"right"`` ; ``valign`` vaut
        ``"baseline"``, ``"middle"``, ``"cap"``, ``"top"`` ou ``"bottom"``.
        ``dx``/``dy`` décalent le tracé après ancrage, pour les retouches
        optiques — mais un ``dy`` constant est presque toujours le signe d'un
        mauvais ancrage : ``"cap"`` centre les étiquettes courtes sans retouche.

        ``angle`` fait pivoter le texte autour du point d'ancrage, dans le sens
        trigonométrique : ``90`` donne un texte lisible de bas en haut.

        Rend la boîte em occupée par la chaîne. Avec ``angle`` non nul, cette
        boîte est celle **avant** rotation, exprimée relativement au point
        d'ancrage translaté.
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
