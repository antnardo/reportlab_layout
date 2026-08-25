"""The rectangle a drawing operation ended up covering."""

from typing import NamedTuple

__all__ = ["Box"]


class Box(NamedTuple):
    """The rectangle an element actually occupies, in canvas coordinates.

    Unpacks as a plain ``(x, y, width, height)`` tuple. ``x, y`` is the
    **bottom-left** corner, as everywhere else in reportlab.
    """

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)
