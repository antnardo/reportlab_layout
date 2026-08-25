"""Primitives géométriques : filets, rectangles, rectangles arrondis.

Chaque tracé est encadré par ``saveState`` / ``restoreState`` : la couleur et
l'épaisseur de trait choisies ici ne fuient pas vers le tracé suivant.
"""

from reportlab.pdfgen.canvas import Canvas

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color

__all__ = ["ShapePainter"]


class ShapePainter:
    """Trace des formes simples sur un canvas reportlab."""

    def __init__(self, canvas: Canvas) -> None:
        self._canvas = canvas

    def line(
        self, x1: float, y1: float, x2: float, y2: float, *, stroke: ColorLike = None, line_width: float = 0.5
    ) -> Box:
        """Trace un segment. Rend sa boîte englobante."""
        canvas = self._canvas
        canvas.saveState()
        canvas.setLineWidth(line_width)
        if (color := to_color(stroke)) is not None:
            canvas.setStrokeColor(color)
        canvas.line(x1, y1, x2, y2)
        canvas.restoreState()
        return Box(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: ColorLike = None,
        stroke: ColorLike = "black",
        line_width: float = 0.5,
    ) -> Box:
        """Trace un rectangle. ``fill=None`` laisse l'intérieur vide."""
        canvas = self._canvas
        fill_color = to_color(fill)
        stroke_color = to_color(stroke)
        canvas.saveState()
        canvas.setLineWidth(line_width)
        if fill_color is not None:
            canvas.setFillColor(fill_color)
        if stroke_color is not None:
            canvas.setStrokeColor(stroke_color)
        canvas.rect(
            x, y, width, height, fill=int(fill_color is not None), stroke=int(stroke_color is not None)
        )
        canvas.restoreState()
        return Box(x, y, width, height)

    def round_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        radius: float = 5,
        fill: ColorLike = None,
        stroke: ColorLike = "black",
        line_width: float = 0.5,
    ) -> Box:
        """Trace un rectangle à coins arrondis.

        ``radius`` est écrêté à la moitié du plus petit côté : au-delà, les arcs
        se recouvrent et le tracé se referme sur lui-même.
        """
        radius = max(0.0, min(radius, abs(width) / 2, abs(height) / 2))
        canvas = self._canvas
        fill_color = to_color(fill)
        stroke_color = to_color(stroke)
        canvas.saveState()
        canvas.setLineWidth(line_width)
        if fill_color is not None:
            canvas.setFillColor(fill_color)
        if stroke_color is not None:
            canvas.setStrokeColor(stroke_color)
        path = canvas.beginPath()
        path.moveTo(x + radius, y)
        path.lineTo(x + width - radius, y)
        path.arcTo(x + width - 2 * radius, y, x + width, y + 2 * radius, startAng=-90, extent=90)
        path.lineTo(x + width, y + height - radius)
        path.arcTo(
            x + width - 2 * radius, y + height - 2 * radius, x + width, y + height, startAng=0, extent=90
        )
        path.lineTo(x + radius, y + height)
        path.arcTo(x, y + height - 2 * radius, x + 2 * radius, y + height, startAng=90, extent=90)
        path.lineTo(x, y + radius)
        path.arcTo(x, y, x + 2 * radius, y + 2 * radius, startAng=180, extent=90)
        path.close()
        canvas.drawPath(path, fill=int(fill_color is not None), stroke=int(stroke_color is not None))
        canvas.restoreState()
        return Box(x, y, width, height)
