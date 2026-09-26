"""TrueType font families: the faces registered together, so that markup can switch.

reportlab's fourteen standard fonts stop at Latin-1: a Polish ł, a Romanian ș, a
Greek letter or an arrow come out as black boxes. A TrueType font covers them,
and embeds its glyphs so the text still extracts. Using one takes two steps, and
the second is the one that gets forgotten: ``registerFont`` for each face, then
``registerFontFamily``, without which ``<b>`` and ``<i>`` inside a ``Paragraph``
fail with reportlab's "Can't map determine family/bold/italic". The faces also
need names of their own, which nobody wants to invent at each call site.

:func:`register_font_family` does both, under predictable names. A face left out
falls back on the closest one given, as reportlab's own family does: bold and
italic on the regular face, bold italic on the bold, else the italic.

Only TrueType outlines are read. An OpenType font with PostScript outlines (CFF,
the usual ``.otf``) is refused by reportlab and has to be converted first.

reportlab takes a face's cap height from its OS/2 table. A table older than
version 2 has none, and reportlab silently puts the ascent in its place, which
drops ``valign="cap"`` far too low. Such a face is reported in the log: centre
its labels with ``middle`` rather than ``cap``.
"""

import logging
import os
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

__all__ = ["register_font_family"]

logger = logging.getLogger(__name__)

_SUFFIXES = ("", "-Bold", "-Italic", "-BoldItalic")

#: What each family was registered with: its four faces, as absolute paths.
_REGISTERED: dict[str, tuple[Path, Path, Path, Path]] = {}

PathLike = str | os.PathLike[str]


def register_font_family(
    name: str,
    regular: PathLike,
    *,
    bold: PathLike | None = None,
    italic: PathLike | None = None,
    bold_italic: PathLike | None = None,
) -> str:
    """Register a TrueType family and return its name, the ``fontName`` of a style.

    The faces are registered as ``name``, ``name-Bold``, ``name-Italic`` and
    ``name-BoldItalic``. A face left out takes the closest one given: bold and
    italic fall back on ``regular``, ``bold_italic`` on ``bold``, else on
    ``italic``, else on ``regular``.

    Registering the same family again with the same files does nothing, so a
    module can do it at import time. With other files it raises ``ValueError``
    rather than changing the look of every document already using the name; so
    does the name of one of the standard fonts, which it would shadow. A missing
    file raises ``FileNotFoundError``.
    """
    if any(name + suffix in pdfmetrics.standardFonts for suffix in _SUFFIXES):
        raise ValueError(f"{name!r} would shadow one of reportlab's standard fonts")
    regular_path = Path(regular).resolve()
    bold_path, italic_path, bold_italic_path = (
        None if path is None else Path(path).resolve() for path in (bold, italic, bold_italic)
    )
    faces = (
        regular_path,
        bold_path or regular_path,
        italic_path or regular_path,
        bold_italic_path or bold_path or italic_path or regular_path,
    )
    known = _REGISTERED.get(name)
    if known is not None:
        if known == faces:
            return name
        raise ValueError(f"Font family {name!r} is already registered with other files")
    for path in dict.fromkeys(faces):
        if not path.is_file():
            raise FileNotFoundError(f"No font file at {path}")
    for suffix, path in zip(_SUFFIXES, faces, strict=True):
        font = TTFont(name + suffix, str(path))
        pdfmetrics.registerFont(font)
        face = font.face
        if face.capHeight == face.ascent:
            logger.warning(
                "%s has no cap height of its own (OS/2 table older than version 2): "
                "reportlab uses its ascent, and valign='cap' will sit too low",
                path.name,
            )
    pdfmetrics.registerFontFamily(
        name,
        normal=name,
        bold=name + "-Bold",
        italic=name + "-Italic",
        boldItalic=name + "-BoldItalic",
    )
    _REGISTERED[name] = faces
    return name
