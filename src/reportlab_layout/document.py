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

import itertools
import logging
import os
import threading
import weakref
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, ClassVar, Protocol, TypeAlias

from reportlab import rl_config
from reportlab.lib.styles import StyleSheet1
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, Frame, Image, KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus import paragraph as platypus_paragraph
from reportlab.platypus.doctemplate import ActionFlowable

from reportlab_layout.annotations import AppearanceAnnotation, form_resources
from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.columns import _UNBOUNDED, Packing, balanced_height, pack_columns
from reportlab_layout.cursor import Cursor
from reportlab_layout.frames import FrameWriter
from reportlab_layout.geometry import PageGeometry
from reportlab_layout.images import ImageLike, load_image
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.pdfpages import PdfSource, draw_pdf_page
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.styles import STYLES, StyleLike, resolve_style
from reportlab_layout.text import TextPainter

__all__ = ["OutputLike", "PDFMaker", "Writable"]

logger = logging.getLogger(__name__)

#: A distance below which two positions count as one, in points: rounding, not
#: space. The cursor stands on the top of the content area, an element keeps
#: to the page, within it.
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


def _opened(canvas: pdfcanvas.Canvas, flowables: Iterable[Flowable], width: float) -> list[Flowable]:
    """``flowables`` with every ``KeepTogether`` among them opened, at any depth.

    Where this is called, nothing is left to keep together: a stack never
    breaks, and a group that no page can hold breaks anyway. Opening them all
    also gets round a ``KeepTogether`` inside another, which the outer one
    counts at the 16777215 pt the inner one reports: it would never fit,
    however tall the column. Split in a column with no bottom, a
    ``KeepTogether`` hands back what it holds, after a break when such an inner
    one swells it; the break goes, with any other action, which a column
    ignores anyway.
    """
    opened: list[Flowable] = []
    for flowable in flowables:
        if isinstance(flowable, KeepTogether):
            held = flowable.splitOn(canvas, width, _UNBOUNDED)
            opened += _opened(canvas, [part for part in held if not isinstance(part, ActionFlowable)], width)
        else:
            opened.append(flowable)
    return opened


class _Stack(Flowable):
    """The flowables of a ``KeepTogether``, one under the other: what :meth:`PDFMaker.draw` lays for it.

    A ``KeepTogether`` only lives to be split: its ``wrap`` reports 16777215 pt
    so that a frame always splits it, and it has no ``draw``. Packed in a single
    column with no bottom to it, its flowables stack as a frame would stack
    them, space between them included, and as :meth:`PDFMaker.draw_columns`
    does: a flowable narrower than the widest is placed by its own ``hAlign``.
    The stack is as tall as they make together, which tells ``draw`` whether
    the group fits, and it draws that very packing.
    """

    def __init__(self, kept: KeepTogether) -> None:
        super().__init__()
        self.kept = kept
        self.spaceBefore = kept.getSpaceBefore()
        self.spaceAfter = kept.getSpaceAfter()
        self.packing = Packing((), (), 0.0)

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        flowables = _opened(self.canv, [self.kept], available_width)
        self.packing = pack_columns(self.canv, flowables, available_width, _UNBOUNDED, 1)
        self.width = max((placement.width for placement in self.packing.placements), default=0.0)
        self.height = self.packing.height
        return self.width, self.height

    def draw(self) -> None:
        for placement in self.packing.placements:
            bottom = self.height - placement.bottom
            placement.flowable.drawOn(self.canv, 0, bottom, _sW=self.width - placement.width)


class _Ascii85Switch:
    """Holds reportlab's ``useA85`` off while documents written in binary are open.

    reportlab ASCII85-encodes every image and page stream unless
    ``rl_config.useA85`` is false. That is a process-wide setting, read when
    each image is drawn and again when each page is written -- there is no
    per-document one. So a document that asks for binary streams has to hold
    the setting off from its first drawing to the end of :meth:`PDFMaker.save`.

    Several such documents can be open at once -- threads in a web application
    -- so the switch counts them under a lock: the first turns the setting off,
    the last restores whatever it was before. Turning it off early or late is
    safe, merely wasteful: each image and each stream records its own filters
    alongside its content, so the PDF stays valid either way, only bigger.
    """

    _lock: ClassVar[threading.Lock] = threading.Lock()
    _holders: ClassVar[int] = 0
    _saved: ClassVar[Any] = None

    @classmethod
    def acquire(cls) -> None:
        with cls._lock:
            if cls._holders == 0:
                cls._saved = rl_config.useA85
                rl_config.useA85 = 0
            cls._holders += 1

    @classmethod
    def release(cls) -> None:
        with cls._lock:
            cls._holders -= 1
            if cls._holders == 0:
                rl_config.useA85 = cls._saved


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
    :param canvasmaker: what builds the canvas, called like reportlab's
        ``Canvas``, with the output and ``pagesize=``: a ``Canvas`` subclass
        such as :class:`~reportlab_layout.NumberedCanvas`, which stamps "page x
        of y".
    :param ascii85: ``True`` lets reportlab encode images and page streams in
        ASCII85, as it does by default. This package writes them in binary
        instead: ASCII85 keeps a PDF to 7-bit text at the cost of a quarter more
        bytes, which no mail or web transport has needed for decades -- a mail
        attachment is base64-encoded anyway. reportlab only has a process-wide
        switch for it, so while a binary document is open, any other PDF built
        in the same process is written in binary too, ``ascii85=True`` or not:
        valid, only smaller.
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
        canvasmaker: Callable[..., pdfcanvas.Canvas] = pdfcanvas.Canvas,
        ascii85: bool = False,
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
        self.unit = unit
        self.font_size = font_size
        self.stylesheet = stylesheet if stylesheet is not None else STYLES
        self.auto_page_break = auto_page_break
        self.show_boundaries = show_boundaries

        self.cursor = Cursor(self.geometry.margins.top, self.geometry.bottom_depth)
        self.canvas = canvasmaker(_canvas_target(path), pagesize=(self.geometry.width, self.geometry.height))

        #: Height :meth:`add_space` adds when called bare, in type sizes.
        self.default_space = 1.0
        self.header: list[Flowable] = []
        self.footer: list[Flowable] = []
        self.active_frame: Frame | None = None
        self.page = 1
        self._warned: set[str] = set()
        self._annotations = itertools.count(1)  # names the forms that draw annotations
        self._annotating = False  # inside an annotation block, where a page cannot end

        self._export_geometry()
        self.canvas.setFontSize(self.font_size)

        # Taken last, once nothing above can fail. weakref.finalize releases it
        # exactly once: from save() or a failing with block, or when the
        # document is collected if it is dropped without either.
        if ascii85:
            self._release_ascii85: Callable[[], object] = lambda: None
        else:
            _Ascii85Switch.acquire()
            self._release_ascii85 = weakref.finalize(self, _Ascii85Switch.release)

    @property
    def canvas(self) -> pdfcanvas.Canvas:
        """The reportlab canvas everything is drawn on.

        Replacing it moves ``shapes`` and ``text``, the painters behind
        ``draw_rect`` and ``draw_string``, onto the new canvas too. Left on the
        old one, which is never saved, their drawings vanished without an
        error. Replace it before drawing anything, since what the old canvas
        holds is lost with it -- or pass ``canvasmaker`` to the constructor.
        """
        return self._canvas

    @canvas.setter
    def canvas(self, canvas: pdfcanvas.Canvas) -> None:
        self._canvas = canvas
        self.shapes = ShapePainter(canvas)
        self.text = TextPainter(canvas, self.stylesheet)

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
        else:
            self._release_ascii85()

    def set_metadata(self, author: str = "", title: str = "", subject: str = "") -> None:
        """Set the PDF metadata."""
        self.canvas.setAuthor(author)
        self.canvas.setTitle(title)
        self.canvas.setSubject(subject)

    def new_page(self) -> int:
        """Finish the current page -- header and footer included -- and open a fresh one."""
        if self._annotating:
            raise RuntimeError("an annotation cannot span a page break")
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
        if self._annotating:
            # reportlab would write the annotation's drawing onto the page, lose
            # what the page held, then fail when the block closes its form.
            raise RuntimeError("a document cannot be saved inside an annotation")
        try:
            self.draw_header_footer()
            self.canvas.save()
        finally:
            self._release_ascii85()

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
        spec: ImageLike,
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

        A ``KeepTogether`` is laid as one block: its flowables one under the
        other, spaced as in a frame, in a box as tall as they make together.
        It moves to a new page whole, and only a group no page can hold is
        split over the pages, as any block would be. ``halign`` and
        ``valign`` place that box, and the box is what comes back.

        An element that runs off the page, in any mode, is logged as well:
        what lies past the edge is lost, and the PDF says nothing of it.
        """
        flow = y is None and not absolute
        allow_break = self.auto_page_break if page_break is None else page_break
        outline = self.show_boundaries if show_boundary is None else show_boundary
        block = _Stack(flowable) if isinstance(flowable, KeepTogether) else flowable

        box = self._place(block, x, y, width, height, before, absolute, halign, valign, wscale)
        if flow and allow_break and box.y < self.bottom:
            # A new page sends the cursor back to the top: the box rises by as much.
            if box.y + self.cursor.depth - self.cursor.top < self.bottom:
                return self._draw_over_pages(flowable, x, width, before, halign, wscale, outline)
            self.new_page()
            box = self._place(block, x, y, width, height, before, absolute, halign, valign, wscale)

        self._lay(block, box, outline)
        self._report_off_page(flowable, box)
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

    def _report_off_page(self, flowable: Flowable, box: Box) -> None:
        """Log an element whose box runs past an edge of the page, and by how much.

        reportlab draws off the page without a word, and a viewer shows nothing
        of it: 25 rows of a table placed near the bottom went that way, found
        only by counting them. Only :meth:`draw` checks; the canvas-level
        ``draw_*`` shapes and strings are left to bleed, as a full-bleed
        background has to.
        """
        past = {
            "left": -box.x,
            "right": box.right - self.geometry.width,
            "bottom": -box.y,
            "top": box.top - self.geometry.height,
        }
        edges = [f"{amount:.1f} pt past its {edge} edge" for edge, amount in past.items() if amount > _FUZZ]
        if edges:
            logger.warning("%s runs off page %d: %s", type(flowable).__name__, self.page, ", ".join(edges))

    def _warn_once(self, message: str) -> None:
        """Log a warning the first time this document meets it, and never again.

        The header and footer are drawn on every page: a band too tall for its
        margin said so once per page, the same line a hundred times over.
        """
        if message not in self._warned:
            self._warned.add(message)
            logger.warning(message)

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
        leaving it out would lose it without a word. The packing does that,
        told that the column at the top of a page is as tall as any will be,
        as it does for :meth:`draw_columns`.

        A ``KeepTogether`` that no page can hold has nothing left to keep: its
        flowables go on as if they were not grouped, the first filling what is
        left of this page like the first part of any other block.

        Every part sits at the ``x`` the whole flowable would have had, and
        ``before`` and the space before only push the first one down.
        """
        wrap_width = self.content_width if width is None else width
        left, _ = self._anchor(x, None, 0, 0, 0, halign, wscale)
        at_top = self.cursor.depth <= self.cursor.top + _FUZZ
        self.cursor.advance(before * self.unit + flowable.getSpaceBefore())
        queue = _opened(self.canvas, [flowable], wrap_width)
        box = Box(left, self.cursor_y, 0, 0)
        while queue:
            # At the top of a page the column is as tall as any: overflow it rather than wait.
            packing = pack_columns(self.canvas, queue, wrap_width, self.remaining_height, 1, overflow=at_top)
            top = self.cursor_y
            for placement in packing.placements:
                box = Box(left, top - placement.bottom, placement.width, placement.height)
                self._lay(placement.flowable, box, outline)
                self._report_off_page(placement.flowable, box)
            self.cursor.advance(packing.height)
            queue = list(packing.rest)
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
            return 0  # not 0.0, which would turn an x given as 10 into 10.0 in the Box
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
                given = flowable.kept if isinstance(flowable, _Stack) else flowable
                raise ValueError(
                    f"valign='cap' needs a Paragraph, and {type(given).__name__} is not one: use 'middle'"
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
        spec: ImageLike,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
        **kwargs: Any,
    ) -> Box:
        """Lay down an image. ``width``, ``height`` and ``scale`` are in points."""
        return self.draw(self.make_image(spec, width=width, height=height, scale=scale), **kwargs)

    def draw_pdf_page(
        self,
        page: PdfSource,
        x: float,
        y: float,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> Box:
        """Draw a page of a PDF as vector drawing, its lower-left corner at ``(x, y)``.

        Canvas coordinates in points, like the shapes; ``page`` is a
        :class:`~reportlab_layout.PdfPage` or a PDF (path, bytes, file) whose first
        page is taken. See :func:`~reportlab_layout.draw_pdf_page`.
        """
        return draw_pdf_page(self.canvas, page, x, y, width, height, scale)

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
            if box.y < -_FUZZ:
                self._warn_once(f"Footer taller than the bottom margin: {-box.y:.1f} pt off the page")
        header_edge = self.geometry.depth_to_y(self.top)
        for flowable, box in self._band(self._as_flowables(self.header), header_edge, header=True):
            self._lay(flowable, box, self.show_boundaries)
            overflow = box.top - self.geometry.height
            if overflow > _FUZZ:
                self._warn_once(f"Header taller than the top margin: {overflow:.1f} pt off the page")

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
        spec: ImageLike,
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

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------
    @contextmanager
    def annotation(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        contents: str = "",
        author: str = "",
    ) -> Iterator[Box]:
        """Make what is drawn inside the block a PDF annotation, movable and removable.

        Every reader shows the annotation exactly as drawn, prints it with the page,
        and lets its user drag it aside or delete it, which nothing drawn on the page
        allows. ``x``, ``y``, ``width``, ``height`` is its rectangle, canvas
        coordinates in points; draw inside the block with the usual ``draw_*``
        methods, in absolute coordinates on the same page -- what falls outside the
        rectangle is clipped, the outer half of a stroke laid on its edge
        included. ``contents`` is the text a reader lists in its comments panel,
        ``author`` the name it shows beside it. See
        :mod:`reportlab_layout.annotations`.

        The block yields the rectangle as a :class:`Box`. It must neither start a
        new page nor save the document. If it raises, nothing is added, and the
        page goes on as before.
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"an annotation needs a positive width and height, got {width} x {height}")
        if self._annotating:
            raise RuntimeError("annotations do not nest")
        name = f"annotation{next(self._annotations)}"
        # reportlab sets the page's drawing and annotations aside while a form is
        # drawn only when the page already holds some drawing; on a blank page they
        # are dropped instead when the form ends -- the annotations added before
        # with them -- and a page left with no drawing is never written. An empty
        # q/Q pair is drawing enough, and draws nothing.
        self.canvas.saveState()
        self.canvas.restoreState()
        self.canvas.beginForm(name, lowerx=x, lowery=y, upperx=x + width, uppery=y + height)
        self._annotating = True
        try:
            yield Box(x, y, width, height)
        finally:
            # Always closed: an open form would swallow the rest of the page.
            self._annotating = False
            shading = dict(self.canvas._shadingUsed)
            self.canvas.endForm()
        form = self.canvas._doc.idToObject[pdfdoc.xObjectName(name)]
        form.Resources = form_resources(form, shading)
        rect = (x, y, x + width, y + height)
        self.canvas._addAnnotation(AppearanceAnnotation(rect, contents, pdfdoc.xObjectName(name), author))
