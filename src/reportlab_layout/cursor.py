"""Curseur de flux : profondeur d'écriture courante dans la page."""

__all__ = ["Cursor"]


class Cursor:
    """Suit la profondeur d'écriture, mesurée depuis le haut de la page.

    La profondeur croît vers le bas, contrairement à l'ordonnée du canvas
    reportlab. La conversion est du ressort de
    :class:`~reportlab_layout.geometry.PageGeometry`.
    """

    def __init__(self, top: float, bottom_depth: float) -> None:
        self._top = top
        self._bottom_depth = bottom_depth
        self._depth = top

    def __repr__(self) -> str:
        return f"Cursor(depth={self._depth:.1f}, remaining={self.remaining:.1f})"

    @property
    def depth(self) -> float:
        """Profondeur courante, en points."""
        return self._depth

    @depth.setter
    def depth(self, value: float) -> None:
        self._depth = float(value)

    @property
    def top(self) -> float:
        """Profondeur de départ, c'est-à-dire la marge haute."""
        return self._top

    @property
    def bottom_depth(self) -> float:
        """Profondeur de la limite basse de la zone de contenu."""
        return self._bottom_depth

    @property
    def remaining(self) -> float:
        """Hauteur restante avant la marge basse. Négative en cas de débordement."""
        return self._bottom_depth - self._depth

    def fits(self, height: float) -> bool:
        """Vrai si un élément de hauteur ``height`` tient encore sur la page."""
        return height <= self.remaining

    def reset(self) -> float:
        """Ramène le curseur en haut de la zone de contenu."""
        self._depth = self._top
        return self._depth

    def advance(self, height: float) -> float:
        """Descend le curseur de ``height`` points et rend la nouvelle profondeur."""
        self._depth += height
        return self._depth
