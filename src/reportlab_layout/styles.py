"""Stylesheets: building them, extending them, resolving names.

reportlab ships ``getSampleStyleSheet()``. This module adds the aligned styles
it always turns out to be missing (``Right``, ``Centered``, ``Justify``...) and
offers :func:`make_stylesheet`, which returns a **fresh** sheet every call.

It also exposes :data:`STYLES`, a shared sheet: handy in a script, dangerous in
a library, because two modules adding the same style name to it collide. As soon
as a document has styles of its own, prefer ``make_stylesheet()`` and hand the
sheet to the document constructor.
"""

from typing import TypeAlias

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet

__all__ = ["STYLES", "StyleLike", "add_style", "make_stylesheet", "resolve_style"]

#: A style, its name in the sheet, or ``None`` for the ``Normal`` style.
StyleLike: TypeAlias = str | ParagraphStyle | None


def add_style(
    stylesheet: StyleSheet1,
    name: str,
    parent: str | ParagraphStyle = "Normal",
    *,
    replace: bool = True,
    **attributes: object,
) -> ParagraphStyle:
    """Add (or replace) a style derived from ``parent`` in ``stylesheet``.

    ``StyleSheet1.add`` raises ``KeyError`` when the name already exists, which
    breaks the second import of the calling module. With ``replace=True`` the
    existing style is overwritten; with ``replace=False`` reportlab's behaviour
    is kept.
    """
    if isinstance(parent, str):
        parent = stylesheet[parent]
    style = ParagraphStyle(name=name, parent=parent, **attributes)
    if name in stylesheet.byName:
        if not replace:
            raise KeyError(f"Style {name!r} is already defined in this stylesheet")
        stylesheet.byName[name] = style
        return style
    stylesheet.add(style)
    return style


def make_stylesheet() -> StyleSheet1:
    """Return a fresh stylesheet, extended with the usual alignments.

    Styles added: ``Left``, ``Right``, ``Centered``, ``Justify``, ``Small``,
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


#: The default shared stylesheet. See the warning at the top of this module.
STYLES: StyleSheet1 = make_stylesheet()


def resolve_style(style: StyleLike, stylesheet: StyleSheet1 | None = None) -> ParagraphStyle:
    """Return a ``ParagraphStyle``, whether given a style or its name.

    ``None`` yields the sheet's ``Normal`` style.
    """
    if stylesheet is None:
        stylesheet = STYLES
    if style is None:
        return stylesheet["Normal"]
    if isinstance(style, str):
        return stylesheet[style]
    return style
