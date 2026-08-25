"""Géométrie de page : format, marges et conversions de repères.

Deux repères coexistent dans ce paquet, et les confondre est la première source
de bugs de mise en page :

* le **repère canvas** de reportlab, origine en bas à gauche, `y` croissant vers
  le haut ;
* la **profondeur** (`depth`), distance depuis le haut de la page, croissante
  vers le bas, utilisée par le curseur de flux (:mod:`reportlab_layout.cursor`).

:class:`PageGeometry` est le seul endroit où l'on passe de l'un à l'autre.
"""

from dataclasses import dataclass

from reportlab.lib import pagesizes
from reportlab.lib.units import mm

__all__ = ["Margins", "PageGeometry", "resolve_pagesize"]


def resolve_pagesize(pagesize: str | tuple[float, float], landscape: bool = False) -> tuple[float, float]:
    """Normalise un format de page en couple ``(largeur, hauteur)`` en points.

    ``pagesize`` accepte un nom reconnu par ``reportlab.lib.pagesizes``
    (``"A4"``, ``"letter"``, ``"A3"``…) ou un couple explicite.
    """
    if isinstance(pagesize, str):
        try:
            size = getattr(pagesizes, pagesize.upper() if len(pagesize) <= 3 else pagesize)
        except AttributeError:
            try:
                size = getattr(pagesizes, pagesize.lower())
            except AttributeError as exc:
                raise ValueError(f"Format de page inconnu : {pagesize!r}") from exc
        pagesize = size
    width, height = float(pagesize[0]), float(pagesize[1])
    if landscape and height > width:
        width, height = height, width
    elif not landscape and width > height:
        # Un format explicitement paysage reste paysage : on ne redresse que si
        # l'appelant a demandé le portrait sans le dire.
        pass
    return width, height


@dataclass(frozen=True, slots=True)
class Margins:
    """Marges d'une page, en points."""

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
        """Construit des marges exprimées en ``unit`` (millimètres par défaut)."""
        return cls(left * unit, right * unit, top * unit, bottom * unit)


@dataclass(frozen=True, slots=True)
class PageGeometry:
    """Format de page et marges, avec la zone de contenu qui en découle.

    Toutes les valeurs sont en points PostScript (1/72 de pouce).
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

    # -- zone de contenu ------------------------------------------------
    @property
    def content_width(self) -> float:
        return self.width - self.margins.left - self.margins.right

    @property
    def content_height(self) -> float:
        return self.height - self.margins.top - self.margins.bottom

    @property
    def x_left(self) -> float:
        """Abscisse canvas du bord gauche de la zone de contenu."""
        return self.margins.left

    @property
    def x_right(self) -> float:
        return self.width - self.margins.right

    @property
    def y_top(self) -> float:
        """Ordonnée canvas du haut de la zone de contenu."""
        return self.height - self.margins.top

    @property
    def y_bottom(self) -> float:
        return self.margins.bottom

    @property
    def content_box(self) -> tuple[float, float, float, float]:
        """``(x, y, largeur, hauteur)`` de la zone de contenu, repère canvas."""
        return (self.x_left, self.y_bottom, self.content_width, self.content_height)

    @property
    def bottom_depth(self) -> float:
        """Profondeur (depuis le haut) de la limite basse de la zone de contenu."""
        return self.height - self.margins.bottom

    # -- conversions ----------------------------------------------------
    def depth_to_y(self, depth: float) -> float:
        """Profondeur depuis le haut -> ordonnée canvas."""
        return self.height - depth

    def y_to_depth(self, y: float) -> float:
        """Ordonnée canvas -> profondeur depuis le haut."""
        return self.height - y
