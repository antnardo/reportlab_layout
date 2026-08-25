"""Page geometry: size, margins, and conversion between coordinate systems.

Two coordinate systems live side by side in this package, and confusing them is
the first cause of layout bugs:

* reportlab's **canvas frame**, origin at the bottom left, `y` growing upwards;
* **depth**, the distance from the top of the page, growing downwards, used by
  the flow cursor (:mod:`reportlab_layout.cursor`).

:class:`PageGeometry` is the only place that converts between the two.
"""

from dataclasses import dataclass

from reportlab.lib import pagesizes
from reportlab.lib.units import mm

__all__ = ["Margins", "PageGeometry", "resolve_pagesize"]


def resolve_pagesize(pagesize: str | tuple[float, float], landscape: bool = False) -> tuple[float, float]:
    """Normalise a page size into a ``(width, height)`` pair, in points.

    ``pagesize`` accepts any name ``reportlab.lib.pagesizes`` knows (``"A4"``,
    ``"letter"``, ``"A3"``...) or an explicit pair.
    """
    if isinstance(pagesize, str):
        try:
            size = getattr(pagesizes, pagesize.upper() if len(pagesize) <= 3 else pagesize)
        except AttributeError:
            try:
                size = getattr(pagesizes, pagesize.lower())
            except AttributeError as exc:
                raise ValueError(f"Unknown page size: {pagesize!r}") from exc
        pagesize = size
    width, height = float(pagesize[0]), float(pagesize[1])
    if landscape and height > width:
        width, height = height, width
    elif not landscape and width > height:
        # A size given explicitly in landscape stays that way: we only straighten
        # up when the caller asked for portrait without saying so.
        pass
    return width, height


@dataclass(frozen=True, slots=True)
class Margins:
    """Page margins, in points."""

    left: float
    right: float
    top: float
    bottom: float

    @classmethod
    def build(
        cls,
        left: float = 15,
        right: float = 15,
        top: float = 15,
        bottom: float = 15,
        unit: float = mm,
    ) -> "Margins":
        """Build margins expressed in ``unit`` (millimetres by default)."""
        return cls(left * unit, right * unit, top * unit, bottom * unit)


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """Page size and margins, plus the content area they leave.

    Every value is in PostScript points (1/72 inch).
    """

    width: float
    height: float
    margins: Margins

    @classmethod
    def build(
        cls,
        pagesize: str | tuple[float, float] = "A4",
        landscape: bool = False,
        unit: float = mm,
        left: float = 15,
        right: float = 15,
        top: float = 15,
        bottom: float = 15,
    ) -> "PageGeometry":
        width, height = resolve_pagesize(pagesize, landscape)
        return cls(width, height, Margins.build(left, right, top, bottom, unit))

    # -- content area ---------------------------------------------------
    @property
    def content_width(self) -> float:
        return self.width - self.margins.left - self.margins.right

    @property
    def content_height(self) -> float:
        return self.height - self.margins.top - self.margins.bottom

    @property
    def x_left(self) -> float:
        """Canvas abscissa of the left edge of the content area."""
        return self.margins.left

    @property
    def x_right(self) -> float:
        return self.width - self.margins.right

    @property
    def y_top(self) -> float:
        """Canvas ordinate of the top of the content area."""
        return self.height - self.margins.top

    @property
    def y_bottom(self) -> float:
        return self.margins.bottom

    @property
    def content_box(self) -> tuple[float, float, float, float]:
        """``(x, y, width, height)`` of the content area, canvas coordinates."""
        return (self.x_left, self.y_bottom, self.content_width, self.content_height)

    @property
    def bottom_depth(self) -> float:
        """Depth, from the top, of the bottom edge of the content area."""
        return self.height - self.margins.bottom

    # -- conversions ----------------------------------------------------
    def depth_to_y(self, depth: float) -> float:
        """Depth from the top -> canvas ordinate."""
        return self.height - depth

    def y_to_depth(self, y: float) -> float:
        """Canvas ordinate -> depth from the top."""
        return self.height - y
