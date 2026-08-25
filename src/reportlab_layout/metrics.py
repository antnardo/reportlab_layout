"""Métriques de police : largeur, ascendante, descendante, ligne de base.

C'est ici que se joue le placement vertical du texte. Une chaîne dessinée par
``canvas.drawString(x, y, texte)`` a sa **ligne de base** en ``y`` ; les jambages
descendent sous cette ligne. Pour centrer verticalement une chaîne dans une boîte
dont le milieu est en ``y_centre``, la ligne de base doit être placée en

    y_centre - (ascendante + descendante) / 2

et non en ``y_centre - hauteur / 2`` avec ``hauteur = ascendante - descendante``.
La descendante étant négative, cette seconde formule descend le texte de
``|descendante|`` de trop, soit environ 20 % du corps.
"""

from dataclasses import dataclass

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import getAscentDescent, getFont, stringWidth

__all__ = [
    "STANDARD_CAP_HEIGHTS",
    "TextMetrics",
    "baseline_offset",
    "cap_height",
    "font_ascent",
    "font_descent",
    "font_height",
    "string_width",
]

#: Ancrages verticaux acceptés par :meth:`TextMetrics.baseline`.
VALIGNS = ("baseline", "middle", "cap", "top", "bottom")

#: Hauteurs de capitale des polices PostScript standard, en millièmes de
#: cadratin, telles que publiées dans leurs fichiers AFM par Adobe. reportlab
#: n'expose pas cette métrique pour ces polices : il ne donne que l'ascendante,
#: qui vaut la hauteur de capitale chez Helvetica mais pas chez Times ni Courier.
#: Symbol et ZapfDingbats sont volontairement absents : leur AFM annonce une
#: hauteur de capitale nulle, qui ne veut rien dire pour un centrage.
STANDARD_CAP_HEIGHTS = {
    "Courier": 562,
    "Courier-Bold": 562,
    "Courier-Oblique": 562,
    "Courier-BoldOblique": 562,
    "Helvetica": 718,
    "Helvetica-Bold": 718,
    "Helvetica-Oblique": 718,
    "Helvetica-BoldOblique": 718,
    "Times-Roman": 662,
    "Times-Bold": 676,
    "Times-Italic": 653,
    "Times-BoldItalic": 676,
}
#: Ancrages horizontaux acceptés par :meth:`TextMetrics.left_edge`.
HALIGNS = ("left", "center", "right")


@dataclass(frozen=True, slots=True)
class TextMetrics:
    """Métriques d'un style, éventuellement mis à l'échelle.

    ``scale`` multiplie le corps du style. Toutes les métriques exposées ici en
    tiennent compte : c'est la raison d'être de cette classe. Calculer la largeur
    d'une chaîne au corps nominal puis la dessiner à ``scale = 0.5`` produit un
    centrage faux d'un facteur deux.
    """

    style: ParagraphStyle
    scale: float = 1.0

    @property
    def font_name(self) -> str:
        return self.style.fontName

    @property
    def font_size(self) -> float:
        """Corps effectif, échelle comprise."""
        return self.style.fontSize * self.scale

    @property
    def leading(self) -> float:
        """Interligne effectif, échelle comprise."""
        return (self.style.leading or 1.2 * self.style.fontSize) * self.scale

    @property
    def ascent(self) -> float:
        """Hauteur au-dessus de la ligne de base, positive."""
        return getAscentDescent(self.font_name, self.font_size)[0]

    @property
    def descent(self) -> float:
        """Profondeur sous la ligne de base, **négative**."""
        return getAscentDescent(self.font_name, self.font_size)[1]

    @property
    def height(self) -> float:
        """Hauteur de la boîte em : ``ascendante - descendante``."""
        ascent, descent = getAscentDescent(self.font_name, self.font_size)
        return ascent - descent

    @property
    def cap_height(self) -> float:
        """Hauteur des capitales au-dessus de la ligne de base, en points.

        Lue dans :data:`STANDARD_CAP_HEIGHTS` pour les polices PostScript
        standard, sinon dans la fonte elle-même quand elle la déclare
        (TrueType), sinon rabattue sur l'ascendante — approximation exacte pour
        les fontes de type Helvetica, généreuse d'environ 3 % pour Times.
        """
        if (published := STANDARD_CAP_HEIGHTS.get(self.font_name)) is not None:
            return published / 1000 * self.font_size
        face = getFont(self.font_name).face
        declared = getattr(face, "capHeight", None)
        if declared:
            return declared / 1000 * self.font_size
        return self.ascent

    @property
    def cap_offset(self) -> float:
        """Écart entre le milieu de la boîte de capitale et la ligne de base.

        C'est le décalage à retrancher pour centrer optiquement une étiquette
        courte — un libellé de cellule, un titre de bandeau — dans sa boîte.
        Contrairement au centrage sur la boîte em, il ne réserve pas la place
        des jambages, ce qui donne un résultat stable d'une étiquette à l'autre,
        qu'elle ait des descendantes ou non.
        """
        return self.cap_height / 2

    @property
    def baseline_offset(self) -> float:
        """Écart entre le milieu de la boîte em et la ligne de base.

        Soustrait de l'ordonnée du centre visé, il donne la ligne de base à
        utiliser pour un texte centré verticalement.
        """
        ascent, descent = getAscentDescent(self.font_name, self.font_size)
        return (ascent + descent) / 2

    def width(self, text: str) -> float:
        """Largeur de ``text`` au corps effectif."""
        return stringWidth(text, self.font_name, self.font_size)

    def baseline(self, y: float, valign: str = "baseline") -> float:
        """Ordonnée de ligne de base pour un ancrage vertical donné.

        ``baseline`` : ``y`` est déjà la ligne de base.
        ``middle`` : ``y`` est le milieu de la boîte em, jambages compris.
        ``cap`` : ``y`` est le milieu de la boîte de capitale — le centrage
        optique d'une étiquette courte.
        ``top`` : ``y`` est le sommet de la boîte em.
        ``bottom`` : ``y`` est le bas de la boîte em.
        """
        if valign == "baseline":
            return y
        if valign == "middle":
            return y - self.baseline_offset
        if valign == "cap":
            return y - self.cap_offset
        if valign == "top":
            return y - self.ascent
        if valign == "bottom":
            return y - self.descent
        raise ValueError(f"valign doit valoir l'un de {VALIGNS}, reçu {valign!r}")

    def left_edge(self, x: float, text: str, halign: str = "left") -> float:
        """Abscisse de départ du tracé pour un ancrage horizontal donné."""
        if halign == "left":
            return x
        if halign == "center":
            return x - self.width(text) / 2
        if halign == "right":
            return x - self.width(text)
        raise ValueError(f"halign doit valoir l'un de {HALIGNS}, reçu {halign!r}")


def string_width(text: str, style: ParagraphStyle, scale: float = 1.0) -> float:
    """Largeur de ``text`` rendu avec ``style`` mis à l'échelle ``scale``."""
    return TextMetrics(style, scale).width(text)


def font_ascent(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Ascendante du style, en points."""
    return TextMetrics(style, scale).ascent


def font_descent(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Descendante du style, en points (valeur négative)."""
    return TextMetrics(style, scale).descent


def font_height(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Hauteur de la boîte em du style, en points."""
    return TextMetrics(style, scale).height


def baseline_offset(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Décalage à retrancher au centre visé pour obtenir la ligne de base."""
    return TextMetrics(style, scale).baseline_offset


def cap_height(style: ParagraphStyle, scale: float = 1.0) -> float:
    """Hauteur des capitales du style, en points."""
    return TextMetrics(style, scale).cap_height
