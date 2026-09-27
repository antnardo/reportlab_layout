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
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from reportlab.lib.styles import StyleSheet1
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, Frame, Image, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus import paragraph as platypus_paragraph

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.columns import Packing, balanced_height, pack_columns
from reportlab_layout.cursor import Cursor
from reportlab_layout.frames import FrameWriter
from reportlab_layout.geometry import PageGeometry
from reportlab_layout.images import ImageSpec, load_image
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.styles import STYLES, StyleLike, resolve_style
from reportlab_layout.text import TextPainter

__all__ = ["OutputLike", "PDFMaker", "Writable"]

logger = logging.getLogger(__name__)

#: How close to the top of the content area the cursor counts as standing on
#: it, in points: rounding, not space.
_FUZZ = 1e-6

TableCommand: TypeAlias = tuple[Any, ...]


class Writable(Protocol):
    """All reportlab asks of a file object: a ``write`` method that takes bytes.

    A protocol rather than ``BinaryIO``, which a type checker only matches
    against file classes: a Django ``HttpResponse`` writes bytes just as well,
    and would be refused. A file opened in text mode is still refused, as it
    should be.
    """

    def write(self, data: bytes, /) -> object: ...


#: Where a document is written: a path, or a binary file object -- an
#: ``io.BytesIO``, a file opened in ``"wb"`` mode, a Django ``HttpResponse``.
OutputLike: TypeAlias = str | os.PathLike[str] | Writable


def _canvas_target(output: OutputLike) -> str | Writable:
    """What to hand reportlab's ``Canvas``: a path as ``str``, a file object as is.

    ``Canvas`` takes a ``str`` or anything with a ``write`` method -- not even a
    ``Path``. Converting everything with ``str()`` covered paths, but turned a
    ``BytesIO`` into a file name, its repr: the buffer stayed empty and a file
    called ``<_io.BytesIO object at 0x...>`` appeared in the working directory.

    The file object is recognised the way reportlab does it, by a callable
    ``write``. Making :class:`Writable` runtime-checkable would not do: from
    Python 3.12 its ``isinstance`` misses a ``NamedTemporaryFile``, whose
    ``write`` only exists through ``__getattr__``. Anything else is refused
    here, rather than when ``save()`` gets to it.
    """
    if isinstance(output, str | os.PathLike):
        return os.fspath(output)
    if callable(getattr(output, "write", None)):
        return output
    raise TypeError(f"Expected a path or a binary file object, got {type(output).__name__}")


def _baselines(paragraph: Paragraph, height: float) -> tuple[float, float]:
    """Heights, above the bottom of its block, of a wrapped paragraph's first and last baselines.

    reportlab hangs the first baseline one type size below the top of the block
    and leaves ``leading - size`` under the last. The first line drops by the
    ascent instead of the size when ``paraFontSizeHeightOffset`` is off: the
    flag is read where reportlab's drawing code reads it. The line pitch is read
    back from the block rather than from the style, because ``autoLeading``
    changes it. The font and size are the style's: a size changed by markup
    inside the paragraph is not accounted for. The paragraph holds a line at
    least.
    """
    metrics = TextMetrics(paragraph.style)
    drop = metrics.font_size if platypus_paragraph.paraFontSizeHeightOffset else metrics.ascent
    lines = len(paragraph.blPara.lines)
    first = height - drop
    return first, first - (lines - 1) * height / lines


def _cap_middle(paragraph: Paragraph, height: float) -> float:
    """Height, above the bottom of its block, of the middle of a wrapped paragraph's capitals.

    The capitals run from the cap height of the first line down to the
    baseline of the last. Since reportlab hangs the first baseline one type
    size below the top of the block and leaves ``leading - size`` under the
    last, the middle of that span lies ``size - (leading + cap height) / 2``
    below the middle of the block, whatever the number of lines: 2.1 pt low for
    Helvetica 15 set solid, 1.3 pt high for Helvetica 12 on 18.
    """
    if not paragraph.blPara.lines:
        return height / 2
    first, last = _baselines(paragraph, height)
    return (first + TextMetrics(paragraph.style).cap_height + last) / 2


class PDFMaker:
    """A PDF document built page by page, with a flow cursor.

    :param path: where the PDF goes: a path, or a binary file object -- an
        ``io.BytesIO``, a file opened in ``"wb"`` mode, a Django
        ``HttpResponse``. A file object receives the whole PDF at :meth:`save`
        and is left open.
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
        path: OutputLike,
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
        self.canvas = pdfcanvas.Canvas(
            _canvas_target(path), pagesize=(self.geometry.width, self.geometry.height)
        )
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
        """Draw the last page's header and footer, then write the PDF.

        A file object is written to but not closed, since the caller still has
        to read or send it. Its position is left at the end of the PDF: rewind
        it with ``seek(0)`` before reading it back.
        """
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
        repeat_rows: int = 0,
    ) -> Table:
        """Build a ``Table``.

        Without ``col_widths`` the content width is split evenly. A scalar
        applies to every column. The first ``repeat_rows`` rows are repeated
        at the top of every part when the table is split across pages.
        """
        if not data or not data[0]:
            raise ValueError("A table needs at least one non-empty row")
        columns = len(data[0])
        if col_widths is None:
            col_widths = [self.content_width / columns] * columns
        elif not isinstance(col_widths, list | tuple):
            col_widths = [col_widths] * columns
        return Table(data, colWidths=list(col_widths), rowHeights=row_heights, repeatRows=repeat_rows)

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
        x += self._halign_offset((1 - wscale) * self.content_width, halign)
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

        In flow, ``halign`` places a block ``wscale`` content widths wide
        across the content width. In absolute mode it says what ``x`` refers
        to instead, as it does for :meth:`draw_string`: the element's left edge
        (``"left"``, the default), its middle (``"center"``) or its right edge
        (``"right"``), from the width the element wraps to.

        ``valign`` only applies in absolute mode and says what ``y`` refers to:
        the element's bottom (``"bottom"``, the default), its middle
        (``"middle"``) or its top (``"top"``). A paragraph also takes
        ``"cap"``, the middle of its capitals, from the cap height of the first
        line down to the baseline of the last: that is what makes a title look
        centred. Any other flowable refuses it.

        ``page_break`` at ``None`` follows the document's ``auto_page_break``
        setting; ``True`` or ``False`` force it for this call. With page breaks
        on, a flowable laid in flow that would cross the bottom margin starts a
        new page, whole. One that no page could hold is split instead, from the
        cursor, over as many pages as it takes, and the box returned is its
        last part's. What cannot split is laid at the top of a page anyway,
        overflowing it, and logged.
        """
        flow = y is None and not absolute
        allow_break = self.auto_page_break if page_break is None else page_break
        outline = self.show_boundaries if show_boundary is None else show_boundary

        box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)
        if flow and allow_break and box.y < self.bottom:
            # A new page sends the cursor back to the top: the box rises by as much.
            if box.y + self.cursor.depth - self.cursor.top < self.bottom:
                return self._draw_over_pages(flowable, x, width, before, halign, wscale, outline)
            self.new_page()
            box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)

        self._lay(flowable, box, outline)
        if flow:
            self.cursor.advance(
                box.height + before * self.unit + flowable.getSpaceBefore() + flowable.getSpaceAfter()
            )
        return box

    def _lay(self, flowable: Flowable, box: Box, outline: bool) -> None:
        """Draw a flowable already wrapped into ``box``, and outline the box if asked."""
        flowable.drawOn(self.canvas, box.x, box.y)
        if outline:
            self.shapes.rect(*box)

    def _draw_over_pages(
        self,
        flowable: Flowable,
        x: float | None,
        width: float | None,
        before: float,
        halign: str,
        wscale: float,
        outline: bool,
    ) -> Box:
        """Lay down in flow a flowable taller than the content area, split over the pages.

        Breaking the page first, as for a block that only needs a fresh page,
        would leave the page empty and the block no shorter: 1.5.0 did that,
        then let the block run off the bottom of the next page. The splitting
        is :func:`pack_columns`'s, in a single column as tall as what is left
        of the page, the one :meth:`draw_columns` relies on: a paragraph splits
        between two lines, a table between two rows and repeats its heading
        rows. The first part fills what is left of this page, if a line or a
        row fits there; the rest go on the pages after, from the top.

        What cannot split -- an image, a single row taller than the page -- is
        laid at the top of a page all the same, overflowing it, and reported in
        the log: raising would stop the whole document for one block, and
        leaving it out would lose it without a word.

        Every part sits at the ``x`` the whole flowable would have had, and
        ``before`` and the space before only push the first one down.
        """
        wrap_width = self.content_width if width is None else width
        left, _ = self._anchor(x, None, 0, 0, 0, halign, wscale)
        at_top = self.cursor.depth <= self.cursor.top + _FUZZ
        self.cursor.advance(before * self.unit + flowable.getSpaceBefore())
        queue = [flowable]
        box = Box(left, self.cursor_y, 0, 0)
        while queue:
            packing = pack_columns(self.canvas, queue, wrap_width, self.remaining_height, 1)
            if packing.placements:
                top = self.cursor_y
                for placement in packing.placements:
                    box = Box(left, top - placement.bottom, placement.width, placement.height)
                    self._lay(placement.flowable, box, outline)
                self.cursor.advance(packing.height)
                queue = list(packing.rest)
            elif at_top:
                head, *queue = packing.rest
                # A failed split can leave the flowable unwrapped: a Paragraph drops its lines.
                head_width, head_height = head.wrapOn(self.canvas, wrap_width, self.height)
                box = Box(left, self.cursor_y - head_height, head_width, head_height)
                self._lay(head, box, outline)
                self.cursor.advance(head_height)
                logger.warning(
                    "%s is %.1f pt tall and cannot split: it overflows the %.1f pt content area of page %d",
                    type(head).__name__,
                    head_height,
                    self.cursor.bottom_depth - self.cursor.top,
                    self.page,
                )
            if queue:
                self.new_page()
                at_top = True
        self.cursor.advance(flowable.getSpaceAfter())
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
            left = x - self._halign_offset(actual_width, halign)
            bottom = y - self._valign_offset(flowable, actual_height, valign)
            return Box(left, bottom, actual_width, actual_height)
        anchor_x, anchor_y = self._anchor(
            x, y, actual_height, before, flowable.getSpaceBefore(), halign, wscale
        )
        return Box(anchor_x, anchor_y, actual_width, actual_height)

    @staticmethod
    def _halign_offset(width: float, halign: str) -> float:
        """Distance from the left edge of an element ``width`` wide to the point ``halign`` names.

        Absolute mode moves the element back by it, so that its named point
        lands on ``x``. Flow moves a ``wscale`` block forward by the offset of
        the width it leaves free: the block's named point then lands on the
        content area's.
        """
        if halign == "left":
            return 0.0
        if halign == "center":
            return width / 2
        if halign == "right":
            return width
        raise ValueError(f"halign must be 'left', 'center' or 'right', got {halign!r}")

    @staticmethod
    def _valign_offset(flowable: Flowable, height: float, valign: str) -> float:
        """Height above the bottom of a wrapped flowable of the point ``valign`` names.

        ``"cap"`` only means something for text: a table or an image has no
        capitals, and falling back to ``"middle"`` would hide the mistake.
        """
        if valign == "bottom":
            return 0.0
        if valign == "middle":
            return height / 2
        if valign == "top":
            return height
        if valign == "cap":
            if not isinstance(flowable, Paragraph):
                raise ValueError(
                    f"valign='cap' needs a Paragraph, and {type(flowable).__name__} is not one: use 'middle'"
                )
            return _cap_middle(flowable, height)
        raise ValueError(f"valign must be 'bottom', 'middle', 'cap' or 'top', got {valign!r}")

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
        repeat_rows: int = 0,
        **kwargs: Any,
    ) -> Box:
        """Lay down a table.

        ``style`` is a sequence of reportlab commands
        (``("GRID", (0, 0), (-1, -1), 0.5, colors.black)``) or a ``TableStyle``
        already built. Cells are middle-aligned vertically by default. A table
        taller than the page is split across pages when page breaks are on,
        its first ``repeat_rows`` rows at the top of every part.
        """
        table = self.make_table(data, col_widths=col_widths, row_heights=row_heights, repeat_rows=repeat_rows)
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
    # Columns
    # ------------------------------------------------------------------
    def draw_columns(
        self,
        story: Iterable[Flowable],
        *,
        columns: int = 2,
        gap: float = 4,
        balance: bool = True,
        show_boundary: bool | None = None,
    ) -> Box:
        """Flow a story over columns, from the cursor, onto as many pages as it takes.

        ``gap`` is the space between two columns, in ``unit``. Every page but
        the last is filled to its bottom margin, then a new page is opened, with
        its header and footer; on the last, the columns are balanced to end
        level, unless ``balance`` is false. The cursor moves under the columns,
        whose box on that last page is returned. See
        :mod:`reportlab_layout.columns`.

        When nothing fits in what is left of the page, the columns start on the
        next one, as a block too tall for the page would.
        """
        if columns < 1:
            raise ValueError(f"columns must be at least 1, got {columns}")
        spacing = gap * self.unit
        width = (self.content_width - (columns - 1) * spacing) / columns
        if width <= 0:
            raise ValueError(f"No room for {columns} columns {gap} apart in {self.content_width:.1f} pt")
        outline = self.show_boundaries if show_boundary is None else show_boundary
        queue = list(story)
        while True:
            room = self.remaining_height
            at_top = self.cursor.depth <= self.cursor.top + _FUZZ
            packing = pack_columns(self.canvas, queue, width, room, columns, overflow=at_top)
            if packing.rest and not packing.placements and not at_top:
                self.new_page()
                continue
            if not packing.rest:
                if balance and columns > 1 and packing.height > 0:
                    level = balanced_height(self.canvas, queue, width, packing.height, columns)
                    balanced = pack_columns(self.canvas, queue, width, level, columns, overflow=at_top)
                    if not balanced.rest:
                        packing = balanced
                top = self.cursor_y
                self._draw_packing(packing, top, width, spacing, packing.height, outline)
                self.cursor.advance(packing.height)
                return Box(self.left, top - packing.height, self.content_width, packing.height)
            self._draw_packing(packing, self.cursor_y, width, spacing, room, outline)
            self.new_page()
            queue = list(packing.rest)

    def _draw_packing(
        self, packing: Packing, top: float, width: float, spacing: float, height: float, outline: bool
    ) -> None:
        """Draw what :func:`pack_columns` laid out, the columns' top at canvas ordinate ``top``."""
        columns = {placement.column for placement in packing.placements}
        for placement in packing.placements:
            x = self.left + placement.column * (width + spacing)
            y = top - placement.top - placement.height
            placement.flowable.drawOn(self.canvas, x, y, _sW=width - placement.width)
        if outline:
            for column in sorted(columns):
                self.shapes.rect(self.left + column * (width + spacing), top - height, width, height)

    # ------------------------------------------------------------------
    # Header and footer
    # ------------------------------------------------------------------
    def set_header(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Set the header redrawn on every page, in the top margin."""
        self.header = self._as_flowables(content)

    def set_footer(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Set the footer redrawn on every page, in the bottom margin."""
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

        Both live in the margins and leave the content area to the flow: the
        footer hangs from its bottom edge, the header stands on its top edge,
        the line the cursor starts from. Reserving the header's height inside
        the area instead would shrink it behind the caller's back, and a ``y=``
        depth could still land on the header. The margin has to be tall enough:
        whatever sticks out past the page edge is logged.

        The gap to the content is the header style's ``spaceAfter`` and the
        footer's ``spaceBefore``. A paragraph in the header keeps it under its
        descenders as well as under its block, which reportlab ends above them
        unless the leading is loose. Several flowables share one edge rather
        than stacking: a logo on the left and a centred title make a single
        band, and the paragraphs of a band share one baseline, the last line's
        in a header, the first line's in a footer.

        Called for you by :meth:`new_page` and :meth:`save`.
        """
        footer_edge = self.geometry.depth_to_y(self.bottom_depth)
        for flowable, box in self._band(self._as_flowables(self.footer), footer_edge, header=False):
            self._lay(flowable, box, self.show_boundaries)
            if box.y < 0:
                logger.warning("Footer taller than the bottom margin: %.1f pt off the page", -box.y)
        header_edge = self.geometry.depth_to_y(self.top)
        for flowable, box in self._band(self._as_flowables(self.header), header_edge, header=True):
            self._lay(flowable, box, self.show_boundaries)
            if box.top > self.geometry.height:
                overflow = box.top - self.geometry.height
                logger.warning("Header taller than the top margin: %.1f pt off the page", overflow)

    def _band(self, flowables: list[Flowable], edge: float, *, header: bool) -> list[tuple[Flowable, Box]]:
        """Where the flowables of a header go, standing on ``edge``, or of a footer, hanging from it.

        Each block keeps clear of the edge by its gap, a header's
        ``spaceAfter``, a footer's ``spaceBefore``. A paragraph in a header also
        keeps its descenders clear of it: reportlab leaves only
        ``leading - size`` under the last baseline, 2 pt in 10/12 for a descent
        of 2.07, none at all set solid, so that a block standing on the edge
        reached into the content area and over the rule of a table laid first.
        The descent is the font's own, the one ``draw_string`` anchors on.

        The paragraphs of a band then share one baseline: the last line's in a
        header, the first line's in a footer, set as far from the content as
        the one that needs it most. Lining their blocks up instead left a 14/18
        heading 2 pt above a 10/12 line beside it, since each style leaves its
        own room under its last line. Anything else -- an image, a table --
        keeps its block against the edge, clear by its gap.
        """
        wrapped = []
        for flowable in flowables:
            width, height = flowable.wrapOn(self.canvas, self.content_width, self.height)
            text = isinstance(flowable, Paragraph) and bool(flowable.blPara.lines)
            first, last = _baselines(flowable, height) if text else (0.0, 0.0)
            wrapped.append((flowable, width, height, text, first, last))

        placed = []
        if header:
            # The last baselines rise until every paragraph's descent line clears the edge.
            baseline = max(
                (
                    edge + flowable.getSpaceAfter() + max(last, -TextMetrics(flowable.style).descent)
                    for flowable, _, _, text, _, last in wrapped
                    if text
                ),
                default=edge,
            )
            for flowable, width, height, text, _, last in wrapped:
                bottom = baseline - last if text else edge + flowable.getSpaceAfter()
                placed.append((flowable, Box(self.left, bottom, width, height)))
            return placed
        # The first baselines sink to the lowest one, so that every block still hangs clear.
        baseline = min(
            (
                edge - flowable.getSpaceBefore() - (height - first)
                for flowable, _, height, text, first, _ in wrapped
                if text
            ),
            default=edge,
        )
        for flowable, width, height, text, first, _ in wrapped:
            bottom = baseline - first if text else edge - flowable.getSpaceBefore() - height
            placed.append((flowable, Box(self.left, bottom, width, height)))
        return placed

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

    def draw_ellipse(self, x: float, y: float, radius_x: float, radius_y: float, **kwargs: Any) -> Box:
        """Draw an ellipse centred on ``(x, y)``, canvas coordinates in points."""
        return self.shapes.ellipse(x, y, radius_x, radius_y, **kwargs)

    def draw_circle(self, x: float, y: float, radius: float, **kwargs: Any) -> Box:
        """Draw a circle centred on ``(x, y)``, canvas coordinates in points."""
        return self.shapes.circle(x, y, radius, **kwargs)

    def draw_polygon(self, points: Sequence[tuple[float, float]], **kwargs: Any) -> Box:
        """Draw a polygon through ``points``, canvas coordinates in points."""
        return self.shapes.polygon(points, **kwargs)

    def draw_regular_polygon(self, x: float, y: float, radius: float, **kwargs: Any) -> Box:
        """Draw a regular polygon or star centred on ``(x, y)``."""
        return self.shapes.regular_polygon(x, y, radius, **kwargs)
