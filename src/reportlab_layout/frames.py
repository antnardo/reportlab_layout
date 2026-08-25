"""Writing into a reportlab ``Frame``.

A frame is a fixed-height box you fill with flowables: reportlab handles the
wrapping and stops writing once the box is full. Useful for a callout, a
standfirst, a column. Whatever did not fit is reported rather than vanishing
silently.
"""

import logging

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Frame

__all__ = ["FrameWriter"]

logger = logging.getLogger(__name__)


class FrameWriter:
    """Fills a ``Frame`` and reports the overflow."""

    def __init__(self, canvas: Canvas, frame: Frame) -> None:
        self._canvas = canvas
        self.frame = frame

    def write(self, story: list[Flowable]) -> list[Flowable]:
        """Write ``story`` into the frame and return the flowables that did not fit.

        reportlab consumes the list it is given: whatever is left in it after
        the call is exactly what overflowed.
        """
        remaining = list(story)
        self.frame.addFromList(remaining, self._canvas)
        if remaining:
            logger.warning("Frame full: %d item(s) left out", len(remaining))
        return remaining
