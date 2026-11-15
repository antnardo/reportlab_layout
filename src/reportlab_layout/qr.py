"""QR codes: the drawing of one, and the modules it is made of.

reportlab draws QR codes with its ``QrCodeWidget``, and three things about it
cost each caller the same lines. Its size comes out of ``getBounds`` and has to
be scaled into a ``Drawing``; its correction level defaults to L, which loses
the code once 7 % of it is written on or creased, while H keeps it up to 30 %;
and every dark run is a rectangle of its own, which a viewer anti-aliases into
hairline seams between rows. :func:`qr_drawing` draws the modules as one path,
filled once, the quiet zone included in the side asked for.

A program that reads its own codes back from a scan wants the modules it
printed, to compare with what it sees. :func:`qr_matrix` runs the same encoder
with the same choices -- reportlab picks the mask pattern deterministically --
so the matrix and the drawing made from the same arguments are the same code.
"""

from typing import Any

from reportlab.graphics.barcode import qrencoder
from reportlab.graphics.shapes import Drawing, Path

from reportlab_layout.colors import ColorLike, to_color

__all__ = ["QR_LEVELS", "qr_drawing", "qr_matrix"]

#: Correction levels, from the least to the most redundant: a code survives the
#: loss of about 7, 15, 25 or 30 % of it.
QR_LEVELS = ("L", "M", "Q", "H")


def _encoded(payload: str, level: str, version: int | None) -> Any:
    if level not in QR_LEVELS:
        raise ValueError(f"level must be one of {QR_LEVELS}, got {level!r}")
    if version is not None and not 1 <= version <= 40:
        raise ValueError(f"A QR version runs from 1 to 40, got {version}")
    code = qrencoder.QRCode(version, getattr(qrencoder.QRErrorCorrectLevel, level))
    code.addData(payload)
    try:
        code.make()
    except Exception as error:
        # reportlab raises a bare Exception when the payload does not fit.
        if "overflow" not in str(error):
            raise
        size = "any version" if version is None else f"version {version}"
        raise ValueError(
            f"{len(payload)} characters do not fit a QR code of {size} at level {level}"
        ) from error
    return code


def qr_matrix(payload: str, *, level: str = "H", version: int | None = None) -> list[list[bool]]:
    """The modules of the QR code for ``payload``, row by row from the top: true is dark.

    ``version`` fixes the size, 4 × version + 17 modules a side; ``None``
    takes the smallest that holds the payload at ``level``. A payload that does
    not fit raises ``ValueError``. The quiet zone is not part of the matrix.
    """
    return [[bool(module) for module in row] for row in _encoded(payload, level, version).modules]


def qr_drawing(
    payload: str,
    side: float,
    *,
    level: str = "H",
    border: int = 4,
    version: int | None = None,
    color: ColorLike = "black",
) -> Drawing:
    """A QR code ``side`` points square, quiet zone included, to lay with ``PDFMaker.draw``.

    ``border`` is the quiet zone, in modules: the standard asks for 4, and a
    code printed on a white margin of its own can make do with less.
    ``level`` and ``version`` are those of :func:`qr_matrix`, which gives the
    very modules drawn here. The light modules are left out, not painted white.
    """
    if side <= 0:
        raise ValueError(f"A QR code needs a positive side, got {side}")
    if border < 0:
        raise ValueError(f"The quiet zone cannot be negative, got {border}")
    matrix = qr_matrix(payload, level=level, version=version)
    module = side / (len(matrix) + 2 * border)
    path = Path(fillColor=to_color(color), strokeColor=None, strokeWidth=0)
    for row, modules in enumerate(matrix):
        top = side - (row + border) * module
        column = 0
        while column < len(modules):
            if not modules[column]:
                column += 1
                continue
            start = column
            while column < len(modules) and modules[column]:
                column += 1
            left, right = (start + border) * module, (column + border) * module
            path.moveTo(left, top)
            path.lineTo(right, top)
            path.lineTo(right, top - module)
            path.lineTo(left, top - module)
            path.closePath()
    drawing = Drawing(side, side)
    drawing.add(path)
    return drawing
