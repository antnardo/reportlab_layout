"""The cursor-driven PDF document: geometry, cursor, styles and drawing.

:class:`PDFMaker` drives a reportlab ``canvas`` with a cursor that moves down
the page as elements are laid onto it -- the convenience of a flowing document,
without giving up absolute positioning when you need it.

Two placement modes live side by side, and every ``draw_*`` method accepts both:

* **flow** (the default): no ``x``, no ``y``; the element lands under the
  previous one and the cursor moves down by its height;
* **absolute** (``absolute=True``): ``x`` and ``y`` are canvas coordinates in
  **points**, and the cursor is left alone.

In between, giving ``x`` and/or ``y`` without ``absolute`` reads them in
``unit`` (millimetres by default), ``y`` being a depth from the top of the page.
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeAlias

from reportlab.lib.styles import StyleSheet1
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, Frame, Image, Paragraph, Spacer, Table, TableStyle

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.cursor import Cursor
from reportlab_layout.frames import FrameWriter
from reportlab_layout.geometry import PageGeometry
from reportlab_layout.images import ImageSpec, load_image
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.styles import STYLES, StyleLike, resolve_style
from reportlab_layout.text import TextPainter

__all__ = ["PDFMaker"]

logger = logging.getLogger(__name__)

TableCommand: TypeAlias = tuple[Any, ...]


class PDFMaker:
    """A PDF document built page by page, with a flow cursor.

    :param path: the output file.
    :param pagesize: a name (``"A4"``, ``"letter"``...) or a ``(width, height)``
        pair in points.
    :param landscape: flip the page size to landscape.
    :param unit: the unit of the coordinates passed to the ``draw_*`` methods
        (``reportlab.lib.units.mm`` by default).
    :param left, right, top, bottom: margins, expressed in ``unit``.
    :param font_size: the reference type size, used by :meth:`add_space`.
    :param stylesheet: the stylesheet; defaults to the shared
        :data:`reportlab_layout.styles.STYLES`.
    :param auto_page_break: start a new page when an element would overflow the
        bottom margin.
    :param show_boundaries: outline the box of every element laid down -- for
        debugging a layout.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        pagesize: str | tuple[float, float] = "A4",
        landscape: bool = False,
        unit: float = mm,
        left: float = 15,
        right: float = 15,
        top: float = 15,
        bottom: float = 15,
        font_size: float = 12,
        stylesheet: StyleSheet1 | None = None,
        auto_page_break: bool = False,
        show_boundaries: bool = False,
    ) -> None:
        self.geometry = PageGeometry.build(
            pagesize=pagesize,
            landscape=landscape,
            unit=unit,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
        )
        self.canvas = pdfcanvas.Canvas(str(path), pagesize=(self.geometry.width, self.geometry.height))
        self.unit = unit
        self.font_size = font_size
        self.stylesheet = stylesheet if stylesheet is not None else STYLES
        self.auto_page_break = auto_page_break
        self.show_boundaries = show_boundaries

        self.cursor = Cursor(self.geometry.margins.top, self.geometry.bottom_depth)
        self.shapes = ShapePainter(self.canvas)
        self.text = TextPainter(self.canvas, self.stylesheet)

        #: Height :meth:`add_space` adds when called bare, in type sizes.
        self.default_space = 1.0
        self.header: list[Flowable] = []
        self.footer: list[Flowable] = []
        self.active_frame: Frame | None = None
        self.page = 1

        self._export_geometry()
        self.canvas.setFontSize(self.font_size)

    def _export_geometry(self) -> None:
        """Copy the page dimensions onto attributes, for readability.

        These are mutable snapshots, not properties: a derived document can
        adjust them without disturbing the reference geometry.
        """
        geometry = self.geometry
        self.width = geometry.width
        self.height = geometry.height
        self.left = geometry.margins.left
        self.right = geometry.margins.right
        self.top = geometry.margins.top
        self.bottom = geometry.margins.bottom
        self.content_width = geometry.content_width
        self.content_height = geometry.content_height
        self.x_left = geometry.x_left
        self.x_right = geometry.x_right
        self.y_top = geometry.y_top
        self.y_bottom = geometry.y_bottom
        self.bottom_depth = geometry.bottom_depth

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __enter__(self) -> "PDFMaker":
        return self

    def __exit__(self, exc_type: type | None, exc: BaseException | None, tb: object) -> None:
        if exc_type is None:
            self.save()

    def set_metadata(self, author: str = "", title: str = "", subject: str = "") -> None:
        """Set the PDF metadata."""
        self.canvas.setAuthor(author)
        self.canvas.setTitle(title)
        self.canvas.setSubject(subject)

    def new_page(self) -> int:
        """Finish the current page -- header and footer included -- and open a fresh one."""
        self.draw_header_footer()
        self.canvas.showPage()
        self.page += 1
        logger.debug("New page [%d]", self.page)
        self.cursor.reset()
        return self.page

    def save(self) -> None:
        """Draw the last page's header and footer, then write the file."""
        self.draw_header_footer()
        self.canvas.save()

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------
    @property
    def remaining_height(self) -> float:
        """Height available below the cursor, in points."""
        return self.cursor.remaining

    @property
    def cursor_y(self) -> float:
        """Canvas ordinate of the cursor's current position, in points."""
        return self.geometry.depth_to_y(self.cursor.depth)

    @property
    def cursor_point(self) -> tuple[float, float]:
        """The cursor's current position as canvas coordinates ``(x, y)``."""
        return (self.left, self.cursor_y)

    def reset_cursor(self) -> float:
        """Send the cursor back to the top of the content area."""
        return self.cursor.reset()

    def advance(self, height: float) -> float:
        """Move the cursor down by ``height`` **points**."""
        return self.cursor.advance(height)

    def add_space(self, space: float | None = None) -> float:
        """Move the cursor down by ``space`` reference type sizes."""
        if space is None:
            space = self.default_space
        return self.cursor.advance(space * self.font_size)

    # ------------------------------------------------------------------
    # Flowable factories
    # ------------------------------------------------------------------
    def make_paragraph(self, text: str, style: StyleLike = None) -> Paragraph:
        """Build a ``Paragraph`` with the requested style."""
        return Paragraph(text, style=resolve_style(style, self.stylesheet))

    def make_spacer(self, space: float = 1) -> Spacer:
        """Build a ``Spacer`` of ``space`` reference type sizes."""
        return Spacer(self.content_width, space * self.font_size)

    def make_table(
        self,
        data: list[list[object]],
        col_widths: float | list[float] | None = None,
        row_heights: float | list[float] | None = None,
    ) -> Table:
        """Build a ``Table``.

        Without ``col_widths`` the content width is split evenly. A scalar
        applies to every column.
        """
        if not data or not data[0]:
            raise ValueError("A table needs at least one non-empty row")
        columns = len(data[0])
        if col_widths is None:
            col_widths = [self.content_width / columns] * columns
        elif not isinstance(col_widths, list | tuple):
            col_widths = [col_widths] * columns
        return Table(data, colWidths=list(col_widths), rowHeights=row_heights)

    def make_image(
        self,
        spec: ImageSpec | str | Path,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> Image:
        """Build an ``Image`` flowable sized in points."""
        return load_image(spec, width=width, height=height, scale=scale)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def _wrap_size(self, width: float | None, height: float | None) -> tuple[float, float]:
        """The largest space offered to the flowable when it works out its wrapping."""
        return (
            self.content_width if width is None else width,
            self.height if height is None else height,
        )

    def _anchor(
        self,
        x: float | None,
        y: float | None,
        height: float,
        before: float,
        space_before: float,
        halign: str,
        wscale: float,
    ) -> tuple[float, float]:
        """Bottom-left corner, in points, of an element ``height`` points tall.

        ``x`` and ``y`` are in ``unit``; ``y`` is a depth from the top of the
        page. ``None`` means "left margin" for ``x`` and "wherever the cursor
        is" for ``y``.
        """
        x = self.left if x is None else x * self.unit
        free = (1 - wscale) * self.content_width
        if halign == "right":
            x += free
        elif halign == "center":
            x += free / 2
        elif halign != "left":
            raise ValueError(f"halign must be 'left', 'center' or 'right', got {halign!r}")
        depth = self.cursor.depth + before * self.unit if y is None else y * self.unit
        return x, self.geometry.depth_to_y(depth) - height - space_before

    def draw(
        self,
        flowable: Flowable,
        *,
        x: float | None = None,
        y: float | None = None,
        width: float | None = None,
        height: float | None = None,
        before: float = 0,
        absolute: bool = False,
        halign: str = "left",
        valign: str = "bottom",
        wscale: float = 1.0,
        page_break: bool | None = None,
        show_boundary: bool | None = None,
    ) -> Box:
        """Lay a flowable down and return the box it occupies.

        The cursor only moves when the element was placed in flow, that is when
        ``y`` is ``None`` and ``absolute`` is false.

        ``valign`` only applies in absolute mode and says what ``y`` refers to:
        the element's bottom (``"bottom"``, the default), its middle
        (``"middle"``) or its top (``"top"``).

        ``page_break`` at ``None`` follows the document's ``auto_page_break``
        setting; ``True`` or ``False`` force it for this call.
        """
        flow = y is None and not absolute
        allow_break = self.auto_page_break if page_break is None else page_break

        box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)
        if flow and allow_break and box.y < self.bottom:
            self.new_page()
            box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)

        flowable.drawOn(self.canvas, box.x, box.y)
        outline = self.show_boundaries if show_boundary is None else show_boundary
        if outline:
            self.shapes.rect(*box)
        if flow:
            self.cursor.advance(
                box.height + before * self.unit + flowable.getSpaceBefore() + flowable.getSpaceAfter()
            )
        return box

    def _place(
        self,
        flowable: Flowable,
        x: float | None,
        y: float | None,
        width: float | None,
        height: float | None,
        before: float,
        absolute: bool,
        halign: str,
        valign: str,
        wscale: float,
    ) -> Box:
        """Work out a flowable's box without drawing it."""
        wrap_width, wrap_height = self._wrap_size(width, height)
        actual_width, actual_height = flowable.wrapOn(self.canvas, wrap_width, wrap_height)
        if absolute:
            if x is None or y is None:
                raise ValueError("absolute=True needs explicit x and y, in points")
            offset = {"bottom": 0.0, "middle": actual_height / 2, "top": actual_height}[valign]
            return Box(x, y - offset, actual_width, actual_height)
        anchor_x, anchor_y = self._anchor(
            x, y, actual_height, before, flowable.getSpaceBefore(), halign, wscale
        )
        return Box(anchor_x, anchor_y, actual_width, actual_height)

    # ------------------------------------------------------------------
    # Drawing in flow
    # ------------------------------------------------------------------
    def draw_paragraph(self, text: str, style: StyleLike = None, **kwargs: Any) -> Box:
        """Lay down a paragraph. The keywords are :meth:`draw`'s."""
        return self.draw(self.make_paragraph(text, style), **kwargs)

    def draw_table(
        self,
        data: list[list[object]],
        col_widths: float | list[float] | None = None,
        row_heights: float | list[float] | None = None,
        style: Iterable[TableCommand] | TableStyle | None = None,
        **kwargs: Any,
    ) -> Box:
        """Lay down a table.

        ``style`` is a sequence of reportlab commands
        (``("GRID", (0, 0), (-1, -1), 0.5, colors.black)``) or a ``TableStyle``
        already built. Cells are middle-aligned vertically by default.
        """
        table = self.make_table(data, col_widths=col_widths, row_heights=row_heights)
        if style is None:
            style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        table.setStyle(style if isinstance(style, TableStyle) else TableStyle(list(style)))
        return self.draw(table, **kwargs)

    def draw_image(
        self,
        spec: ImageSpec | str | Path,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
        **kwargs: Any,
    ) -> Box:
        """Lay down an image. ``width``, ``height`` and ``scale`` are in points."""
        return self.draw(self.make_image(spec, width=width, height=height, scale=scale), **kwargs)

    def draw_centered_line(self, y: float | None = None, wscale: float = 1.0, **kwargs: Any) -> Box:
        """Draw a horizontal rule centred on the content width.

        ``y`` is a depth in ``unit``; without ``y`` the rule lands at the
        cursor, which then moves down by one space.
        """
        if y is None:
            depth = self.cursor.depth - self.font_size / 2
            self.add_space()
        else:
            depth = y * self.unit
        line_y = self.geometry.depth_to_y(depth)
        x1 = self.left + (1 - wscale) * self.content_width / 2
        return self.shapes.line(x1, line_y, x1 + wscale * self.content_width, line_y, **kwargs)

    # ------------------------------------------------------------------
    # Header and footer
    # ------------------------------------------------------------------
    def set_header(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Set the header redrawn on every page."""
        self.header = self._as_flowables(content)

    def set_footer(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Set the footer redrawn on every page."""
        self.footer = self._as_flowables(content)

    @staticmethod
    def _as_flowables(content: Flowable | Iterable[Flowable] | None) -> list[Flowable]:
        if content is None:
            return []
        if isinstance(content, Flowable):
            return [content]
        return list(content)

    def draw_header_footer(self) -> None:
        """Draw the header and footer on the current page.

        Called for you by :meth:`new_page` and :meth:`save`.
        """
        for flowable in self._as_flowables(self.footer):
            self.draw(flowable, y=self.bottom_depth / self.unit, page_break=False)
        for flowable in self._as_flowables(self.header):
            self.draw(flowable, y=self.top / self.unit, page_break=False)

    # ------------------------------------------------------------------
    # Frames
    # ------------------------------------------------------------------
    def new_frame(
        self,
        x: float | None = None,
        y: float | None = None,
        height: float | None = None,
        wscale: float = 1.0,
        before: float = 0,
        halign: str = "left",
        show_boundary: bool = False,
    ) -> Frame:
        """Open a frame at the cursor and move the cursor past it.

        ``height`` is in points; left out, it is one reference type size.
        """
        if height is None:
            height = self.font_size
        anchor_x, anchor_y = self._anchor(x, y, height, before, 0, halign, wscale)
        logger.debug("New frame at (%.1f, %.1f)", anchor_x, anchor_y)
        self.active_frame = Frame(
            anchor_x, anchor_y, wscale * self.content_width, height, showBoundary=show_boundary
        )
        self.cursor.advance(height + before * self.unit)
        return self.active_frame

    def draw_frame(self, story: list[Flowable], space: float = 0) -> list[Flowable]:
        """Write ``story`` into the current frame and return what did not fit."""
        if self.active_frame is None:
            raise RuntimeError("No active frame: call new_frame() first")
        if space > 0:
            story = [*story, self.make_spacer(space)]
        return FrameWriter(self.canvas, self.active_frame).write(story)

    def frame_paragraph(self, text: str, style: StyleLike = None, space: float = 0) -> list[Flowable]:
        """Write a paragraph into the current frame."""
        return self.draw_frame([self.make_paragraph(text, style)], space)

    def frame_space(self, space: float = 1) -> list[Flowable]:
        """Add a spacer inside the current frame."""
        return self.draw_frame([], space)

    def frame_image(
        self,
        spec: ImageSpec | str | Path,
        width: float = 50 * mm,
        space: float = 0,
        halign: str = "CENTER",
    ) -> list[Flowable]:
        """Write an image into the current frame. ``width`` is in points."""
        image = self.make_image(spec, width=width)
        image.hAlign = halign
        return self.draw_frame([image], space)

    # ------------------------------------------------------------------
    # Drawing directly
    # ------------------------------------------------------------------
    def metrics(self, style: StyleLike = None, scale: float = 1.0) -> TextMetrics:
        """Metrics for the requested style, at the requested scale."""
        return TextMetrics(resolve_style(style, self.stylesheet), scale)

    def apply_style(
        self, style: StyleLike = None, scale: float = 1.0, color: ColorLike = "black"
    ) -> TextMetrics:
        """Arm the canvas font and colour for a direct drawing call.

        Useful before calling ``document.canvas.drawString`` yourself. The
        ``draw_string`` method already does it.

        ``color`` defaults to black: arming a font without resetting the colour
        would leave the text in whatever fill the last shape used. Pass
        ``color=None`` to deliberately keep the current colour.
        """
        metrics = self.metrics(style, scale)
        self.canvas.setFont(metrics.font_name, metrics.font_size)
        if color is not None:
            self.canvas.setFillColor(to_color(color))
        return metrics

    def draw_string(self, text: str, x: float, y: float, **kwargs: Any) -> Box:
        """Draw a string anchored at ``(x, y)``, canvas coordinates in points.

        Keywords: ``style``, ``scale``, ``color``, ``halign``
        (``left``/``center``/``right``), ``valign``
        (``baseline``/``middle``/``cap``/``top``/``bottom``), ``angle``, ``dx``,
        ``dy``. See :meth:`reportlab_layout.text.TextPainter.draw`.
        """
        return self.text.draw(text, x, y, **kwargs)

    def draw_line(self, x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> Box:
        """Draw a line segment, canvas coordinates in points."""
        return self.shapes.line(x1, y1, x2, y2, **kwargs)

    def draw_rect(self, x: float, y: float, width: float, height: float, **kwargs: Any) -> Box:
        """Draw a rectangle, canvas coordinates in points."""
        return self.shapes.rect(x, y, width, height, **kwargs)

    def draw_round_rect(self, x: float, y: float, width: float, height: float, **kwargs: Any) -> Box:
        """Draw a rounded rectangle, canvas coordinates in points."""
        return self.shapes.round_rect(x, y, width, height, **kwargs)
