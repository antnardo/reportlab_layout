"""Feuille de styles : construction, extension et résolution.

reportlab fournit ``getSampleStyleSheet()``. Ce module l'enrichit des styles
alignés qui manquent presque toujours (``Right``, ``Centered``, ``Justify``…) et
fournit :func:`make_stylesheet`, qui rend une feuille **neuve** à chaque appel.

Le module expose aussi :data:`STYLES`, une feuille partagée, pratique pour un
script mais dangereuse pour une bibliothèque : deux modules qui y ajoutent le
même nom de style se marchent dessus. Dès qu'un document a des styles à lui,
préférez ``make_stylesheet()`` et passez la feuille au constructeur du document.
"""

from typing import TypeAlias

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet

__all__ = ["STYLES", "StyleLike", "add_style", "make_stylesheet", "resolve_style"]

#: Un style, son nom dans la feuille, ou ``None`` pour le style ``Normal``.
StyleLike: TypeAlias = str | ParagraphStyle | None


def add_style(
    stylesheet: StyleSheet1,
    name: str,
    parent: str | ParagraphStyle = "Normal",
    *,
    replace: bool = True,
    **attributes: object,
) -> ParagraphStyle:
    """Ajoute (ou remplace) un style dérivé de ``parent`` dans ``stylesheet``.

    ``StyleSheet1.add`` lève ``KeyError`` si le nom existe déjà, ce qui fait
    échouer un second import du module appelant. Avec ``replace=True``, le style
    existant est écrasé ; avec ``replace=False``, le comportement de reportlab est
    conservé.
    """
    if isinstance(parent, str):
        parent = stylesheet[parent]
    style = ParagraphStyle(name=name, parent=parent, **attributes)
    if name in stylesheet.byName:
        if not replace:
            raise KeyError(f"Le style {name!r} est déjà défini dans cette feuille")
        stylesheet.byName[name] = style
        return style
    stylesheet.add(style)
    return style


def make_stylesheet() -> StyleSheet1:
    """Rend une feuille de styles neuve, enrichie des alignements usuels.

    Styles ajoutés : ``Left``, ``Right``, ``Centered``, ``Justify``, ``Small``,
    ``Footer``, ``Heading1 Centered``, ``Heading1 Left``.
    """
    stylesheet = getSampleStyleSheet()
    add_style(stylesheet, "Left", alignment=TA_LEFT)
    add_style(stylesheet, "Right", alignment=TA_RIGHT)
    add_style(stylesheet, "Centered", alignment=TA_CENTER)
    add_style(stylesheet, "Justify", alignment=TA_JUSTIFY)
    add_style(stylesheet, "Small", fontSize=8, leading=10)
    add_style(stylesheet, "Footer", fontSize=6, leading=8)
    add_style(stylesheet, "Heading1 Centered", parent="Heading1", alignment=TA_CENTER)
    add_style(stylesheet, "Heading1 Left", parent="Heading1", alignment=TA_LEFT)
    return stylesheet


#: Feuille de styles partagée par défaut. Voir l'avertissement en tête de module.
STYLES: StyleSheet1 = make_stylesheet()


def resolve_style(style: StyleLike, stylesheet: StyleSheet1 | None = None) -> ParagraphStyle:
    """Rend un ``ParagraphStyle``, que l'on ait reçu un style ou son nom.

    ``None`` donne le style ``Normal`` de la feuille.
    """
    if stylesheet is None:
        stylesheet = STYLES
    if style is None:
        return stylesheet["Normal"]
    if isinstance(style, str):
        return stylesheet[style]
    return style
