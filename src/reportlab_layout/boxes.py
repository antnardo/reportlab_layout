"""Rectangle rendu par une opération de tracé."""

from typing import NamedTuple

__all__ = ["Box"]


class Box(NamedTuple):
    """Rectangle effectivement occupé par un élément dessiné, repère canvas.

    Se déballe comme un quadruplet ``(x, y, width, height)``. ``x, y`` est le
    coin **bas-gauche**, comme partout dans reportlab.
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
