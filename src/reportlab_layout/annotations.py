"""Drawings that stay movable: PDF annotations whose appearance is ordinary drawing.

What a canvas draws becomes part of the page: a reader shows it, prints it, and can
neither move it nor remove it. A PDF annotation lies on top of the page instead, as
an object of its own that every reader lets you drag aside or delete -- the stamps
and notes a corrector puts on a scanned copy, which the reader of the copy may want
out of the way.

reportlab can draw a *form XObject*, a piece of drawing kept apart from the page,
and can attach annotations to a page, but not both at once: its annotation classes
take their text and leave the look to each reader, which draws a FreeText in its
own font and a Stamp as a generic icon. Here the annotation carries an *appearance
stream* (``/AP``) -- the form XObject, drawn with the same calls as the page -- so
every reader shows exactly what was drawn, and it is only the object that moves.

The annotation is a ``/Stamp``: of the subtypes a reader lets you move and delete,
the only one that needs nothing but its rectangle, and that no reader redraws from
a font of its own. Its ``Contents`` is the text a reader lists in its comments
panel, and ``T`` its author. The ``Print`` flag keeps it on paper.

The form's bounding box is the annotation's rectangle, in page coordinates, with no
matrix: the reader maps one onto the other unchanged, so what is drawn at a point of
the page inside the block lands exactly there.
"""

from typing import Any

from reportlab.pdfbase import pdfdoc

__all__ = ["AppearanceAnnotation"]

PRINT_FLAG = 4  # the annotation flag that keeps it when the page is printed


class AppearanceAnnotation(pdfdoc.Annotation):  # type: ignore[misc]  # reportlab is untyped
    """A ``/Stamp`` annotation drawn by a form XObject, as reportlab writes it.

    ``rect`` is ``(x1, y1, x2, y2)`` in page coordinates; ``form`` is the internal
    name reportlab gave the form XObject (``xObjectName(name)``).
    """

    permitted = (*pdfdoc.Annotation.permitted, "NM")

    def __init__(
        self, rect: tuple[float, float, float, float], contents: str, form: str, author: str = ""
    ) -> None:
        self.rect = rect
        self.contents = contents
        self.form = form
        self.author = author

    def Dict(self) -> Any:  # noqa: N802 - reportlab's name
        entries: dict[str, Any] = {
            "Subtype": "/Stamp",
            "Rect": list(self.rect),
            "Contents": self.contents,
            "F": PRINT_FLAG,
            "NM": pdfdoc.PDFString(self.form),
            "AP": pdfdoc.PDFDictionary({"N": pdfdoc.PDFObjectReference(self.form)}),
        }
        if self.author:
            entries["T"] = pdfdoc.PDFString(self.author)
        return self.AnnotationDict(**entries)
