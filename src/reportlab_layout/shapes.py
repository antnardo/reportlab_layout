"""Geometric primitives: rules, rectangles, rounded rectangles, ellipses, polygons.

Every drawing is wrapped in ``saveState`` / ``restoreState``, so the colour, the
line width and the dash pattern chosen here do not leak into whatever is drawn
next.
"""

import math
from collections.abc import Sequence

from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import FILL_NON_ZERO, Canvas

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color

__all__ = ["ShapePainter"]


class ShapePainter:
    """Draws simple shapes on a reportlab canvas."""

    def __init__(self, canvas: Canvas) -> None:
        self._canvas = canvas

    def _pen(
        self,
        *,
        fill: ColorLike,
        stroke: ColorLike,
        line_width: float,
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
        line_cap: int | None = None,
        line_join: int | None = None,
    ) -> tuple[Color | None, Color | None]:
        """Set the canvas pen and return the resolved ``(fill, stroke)`` colours.

        Call it inside a ``saveState`` block. A colour left at ``None`` means
        "do not paint that part", which is why the colours come back: each
        drawing call needs them to decide whether to fill and whether to stroke.
        ``dash``, ``line_cap`` and ``line_join`` left at ``None`` leave the
        canvas setting alone.
        """
        canvas = self._canvas
        canvas.setLineWidth(line_width)
        if dash is not None:
            # An empty pattern is reportlab's way of going back to a solid line.
            canvas.setDash(list(dash), dash_phase)
        if line_cap is not None:
            canvas.setLineCap(line_cap)
        if line_join is not None:
            canvas.setLineJoin(line_join)
        fill_color, stroke_color = to_color(fill), to_color(stroke)
        if fill_color is not None:
            canvas.setFillColor(fill_color)
        if stroke_color is not None:
            canvas.setStrokeColor(stroke_color)
        return fill_color, stroke_color

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: ColorLike = None,
        line_width: float = 0.5,
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
        line_cap: int | None = None,
    ) -> Box:
        """Draw a line segment. Returns its bounding box.

        ``dash`` is reportlab's pattern, in points: ``(2, 2)`` alternates two on
        and two off, ``dash_phase`` starting the pattern part-way through. An
        empty pattern goes back to a solid line.

        ``line_cap`` takes reportlab's codes -- 0 butt, 1 round, 2 square -- and
        says how the ends are finished. A round cap is what a freehand stroke, a
        highlighter or a tick wants; it extends half the line width past each
        end, which the box returned does not account for.
        """
        canvas = self._canvas
        canvas.saveState()
        self._pen(
            fill=None,
            stroke=stroke,
            line_width=line_width,
            dash=dash,
            dash_phase=dash_phase,
            line_cap=line_cap,
        )
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
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
    ) -> Box:
        """Draw a rectangle. ``fill=None`` leaves the inside empty.

        ``dash`` dashes the outline; see :meth:`line`.
        """
        canvas = self._canvas
        canvas.saveState()
        fill_color, stroke_color = self._pen(
            fill=fill, stroke=stroke, line_width=line_width, dash=dash, dash_phase=dash_phase
        )
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
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
    ) -> Box:
        """Draw a rectangle with rounded corners.

        ``radius`` is clamped to half the shorter side: beyond that the arcs
        overlap and the path folds back on itself. ``dash`` dashes the outline;
        see :meth:`line`.
        """
        radius = max(0.0, min(radius, abs(width) / 2, abs(height) / 2))
        canvas = self._canvas
        canvas.saveState()
        fill_color, stroke_color = self._pen(
            fill=fill, stroke=stroke, line_width=line_width, dash=dash, dash_phase=dash_phase
        )
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

    def ellipse(
        self,
        x: float,
        y: float,
        radius_x: float,
        radius_y: float,
        *,
        fill: ColorLike = None,
        stroke: ColorLike = "black",
        line_width: float = 0.5,
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
    ) -> Box:
        """Draw an ellipse **centred** on ``(x, y)``. Returns its bounding box.

        Centre and radii rather than a bounding box, to match
        :meth:`regular_polygon`: a shape defined by a centre is nearly always
        placed by its centre, and reportlab's own corner-to-corner form makes
        that an arithmetic chore at every call site.
        """
        if radius_x <= 0 or radius_y <= 0:
            raise ValueError(f"radii must be positive, got ({radius_x}, {radius_y})")

        canvas = self._canvas
        canvas.saveState()
        fill_color, stroke_color = self._pen(
            fill=fill, stroke=stroke, line_width=line_width, dash=dash, dash_phase=dash_phase
        )
        canvas.ellipse(
            x - radius_x,
            y - radius_y,
            x + radius_x,
            y + radius_y,
            stroke=int(stroke_color is not None),
            fill=int(fill_color is not None),
        )
        canvas.restoreState()
        return Box(x - radius_x, y - radius_y, 2 * radius_x, 2 * radius_y)

    def circle(self, x: float, y: float, radius: float, **kwargs: object) -> Box:
        """Draw a circle centred on ``(x, y)`` -- an ellipse with equal radii."""
        return self.ellipse(x, y, radius, radius, **kwargs)  # type: ignore[arg-type]

    def polygon(
        self,
        points: Sequence[tuple[float, float]],
        *,
        fill: ColorLike = None,
        stroke: ColorLike = "black",
        line_width: float = 0.5,
        close: bool = True,
        fill_mode: int = FILL_NON_ZERO,
        line_join: int | None = None,
        line_cap: int | None = None,
        dash: Sequence[float] | None = None,
        dash_phase: float = 0,
    ) -> Box:
        """Draw a polygon through ``points``. Returns their bounding box.

        ``fill_mode`` only matters for a path that crosses itself, and there it
        decides the whole look: ``FILL_NON_ZERO`` (the default) fills a pentagram
        solid, ``FILL_EVEN_ODD`` leaves its central pentagon hollow.

        ``line_join`` takes reportlab's codes -- 0 mitre, 1 round, 2 bevel. Left
        at ``None`` the canvas setting stands. Sharp points at a small size tend
        to look better rounded, since a mitre spike can extend well past the
        vertex.

        ``line_cap`` finishes the two free ends of an open path -- it does
        nothing on a closed one, which has none. ``dash`` dashes the outline;
        both are described on :meth:`line`.
        """
        if len(points) < 3:
            raise ValueError(f"a polygon needs at least 3 points, got {len(points)}")

        canvas = self._canvas
        canvas.saveState()
        fill_color, stroke_color = self._pen(
            fill=fill,
            stroke=stroke,
            line_width=line_width,
            dash=dash,
            dash_phase=dash_phase,
            line_cap=line_cap,
            line_join=line_join,
        )

        path = canvas.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        if close:
            path.close()
        canvas.drawPath(
            path,
            fill=int(fill_color is not None),
            stroke=int(stroke_color is not None),
            fillMode=fill_mode,
        )
        canvas.restoreState()

        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def regular_polygon(
        self,
        x: float,
        y: float,
        radius: float,
        *,
        vertices: int = 5,
        leap: int = 1,
        start_angle: float = 90,
        **kwargs: object,
    ) -> Box:
        """Draw a regular polygon or star inscribed in a circle of ``radius``.

        ``leap`` is how many vertices each edge skips, the *k* of the Schläfli
        symbol {n/k}: 1 gives a convex polygon, and {5/2} is the five-pointed
        star. ``start_angle`` is in degrees, counterclockwise from east, so the
        default 90 puts a vertex straight up.

        ``leap`` must be coprime with ``vertices``, otherwise the path closes
        early and quietly draws a smaller shape -- {6/2} would trace a triangle
        rather than the hexagram, which needs two separate paths.
        """
        if vertices < 3:
            raise ValueError(f"a polygon needs at least 3 vertices, got {vertices}")
        if not 1 <= leap < vertices:
            raise ValueError(f"leap must be in [1, {vertices - 1}], got {leap}")
        if math.gcd(vertices, leap) != 1:
            raise ValueError(
                f"{{{vertices}/{leap}}} closes after {vertices // math.gcd(vertices, leap)} "
                "vertices; a single path cannot draw it"
            )

        step = 2 * math.pi * leap / vertices
        start = math.radians(start_angle)
        points = [
            (x + radius * math.cos(start + index * step), y + radius * math.sin(start + index * step))
            for index in range(vertices)
        ]
        return self.polygon(points, **kwargs)  # type: ignore[arg-type]
