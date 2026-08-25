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

    Pass it as ``canvasmaker`` to ``SimpleDocTemplate.build``, or use it
    directly in place of ``canvas.Canvas``::

        doc.build(story, canvasmaker=NumberedCanvas)

    Position, font and label are set through class attributes or by subclassing.
    """

    #: Folio position, in points from the bottom-left corner.
    folio_position: tuple[float, float] = (195 * mm, 10 * mm)
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
        self.drawRightString(*self.folio_position, type(self).folio_label(page, total))
