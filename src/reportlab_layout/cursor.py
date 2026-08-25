"""The flow cursor: how far down the page writing has reached."""

__all__ = ["Cursor"]


class Cursor:
    """Tracks the writing depth, measured from the top of the page.

    Depth grows downwards, unlike a reportlab canvas ordinate. Converting
    between the two is :class:`~reportlab_layout.geometry.PageGeometry`'s job.
    """

    def __init__(self, top: float, bottom_depth: float) -> None:
        self._top = top
        self._bottom_depth = bottom_depth
        self._depth = top

    def __repr__(self) -> str:
        return f"Cursor(depth={self._depth:.1f}, remaining={self.remaining:.1f})"

    @property
    def depth(self) -> float:
        """Current depth, in points."""
        return self._depth

    @depth.setter
    def depth(self, value: float) -> None:
        self._depth = float(value)

    @property
    def top(self) -> float:
        """Starting depth, that is, the top margin."""
        return self._top

    @property
    def bottom_depth(self) -> float:
        """Depth of the bottom edge of the content area."""
        return self._bottom_depth

    @property
    def remaining(self) -> float:
        """Height left before the bottom margin. Negative once overflowing."""
        return self._bottom_depth - self._depth

    def fits(self, height: float) -> bool:
        """Whether an element ``height`` points tall still fits on the page."""
        return height <= self.remaining

    def reset(self) -> float:
        """Send the cursor back to the top of the content area."""
        self._depth = self._top
        return self._depth

    def advance(self, height: float) -> float:
        """Move the cursor down by ``height`` points and return the new depth."""
        self._depth += height
        return self._depth
