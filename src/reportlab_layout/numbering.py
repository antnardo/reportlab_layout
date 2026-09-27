"""Numbering pages "page x of y".

The page count is only known at the end. :class:`NumberedCanvas` records each
page's state, then replays them once the total is known to stamp the folio on.

After the ActiveState 546511 recipe, corrected: the version that circulates only
works behind a ``DocTemplate``, which always ends with a ``showPage``. Used
directly as a canvas, it silently loses the last page.
"""

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

__all__ = ["NumberedCanvas"]


def _default_label(page: int, total: int) -> str:
    return f"Page {page} of {total}"


class NumberedCanvas(canvas.Canvas):
    """A canvas that stamps a "page x of y" folio on every page.

    Pass it as ``canvasmaker`` to ``SimpleDocTemplate.build`` or to
    :class:`~reportlab_layout.PDFMaker`, or use it directly in place of
    ``canvas.Canvas``::

        doc.build(story, canvasmaker=NumberedCanvas)

    Position, font and label are set through class attributes or by subclassing.
    """

    #: Where the folio ends -- it is set flush right against that point --, in
    #: points from the bottom-left corner. ``None`` follows the page: see
    #: ``folio_inset``.
    folio_position: tuple[float, float] | None = None
    #: Without ``folio_position``, how far the folio ends from the right edge of
    #: the page, and its baseline from the bottom, in points. A fixed point only
    #: suits one page size: 195 mm, the default until 1.5.0, ends the folio 15 mm
    #: from the right edge of A4 portrait, but 21 mm from it on letter and
    #: 102 mm on A4 landscape.
    folio_inset: tuple[float, float] = (15 * mm, 10 * mm)
    folio_font: tuple[str, float] = ("Helvetica", 9)
    #: A ``(page, total) -> str`` function producing the label.
    folio_label: Callable[[int, int], str] = staticmethod(_default_label)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - name imposed by reportlab
        """Record the page instead of writing it out right away."""
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        """Replay every page with its folio, then write the file."""
        # Used directly as a canvas -- rather than through a DocTemplate, which
        # always ends with a showPage -- the last page was never recorded. A
        # non-empty `_code` means drawings are still pending.
        if self._code:
            self._saved_page_states.append(dict(self.__dict__))
        total = len(self._saved_page_states)
        for number, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            self.draw_folio(number, total)
            super().showPage()
        self._saved_page_states.clear()
        super().save()

    def draw_folio(self, page: int, total: int) -> None:
        """Stamp the folio. Override to change how it looks."""
        self.setFont(*self.folio_font)
        self.drawRightString(*self._folio_point(), type(self).folio_label(page, total))

    def _folio_point(self) -> tuple[float, float]:
        """Where the folio of the page being stamped ends, in points from the bottom-left corner.

        Read from the page's own size, which a canvas may change from one page
        to the next.
        """
        if self.folio_position is not None:
            return self.folio_position
        right, bottom = self.folio_inset
        return self._pagesize[0] - right, bottom
