"""A whole PDF written again without what a predicate refuses: a redaction.

Each page of the source is laid down, filtered, on a page of a new document of
the same size (see :mod:`reportlab_layout.pdfcontent` for what the filter takes
out, and :mod:`reportlab_layout.pdfpages` for how a page is copied). Writing a
new document rather than editing the old one is the point: a box drawn over the
original leaves the text under it, and the original's catalogue keeps its XMP
metadata, its structure tree and its information dictionary, which can repeat
the text. Nothing of those is carried over here; only the pages' drawing is.
"""

from pathlib import Path
from typing import IO

from reportlab_layout.document import OutputLike, PDFMaker
from reportlab_layout.pdfcontent import Keep, PdfElement
from reportlab_layout.pdfpages import _reader, pdf_page

__all__ = ["redact_pdf"]


def redact_pdf(source: str | Path | bytes | IO[bytes], output: OutputLike, keep: Keep) -> list[PdfElement]:
    """Write ``source`` into ``output`` again, every page without what ``keep`` refuses.

    ``keep`` is asked about every glyph, image, painted path and shading of every
    page; :attr:`~reportlab_layout.PdfElement.page` tells the pages apart. Gives
    back what was taken out, in the order the pages draw it. Read the output with
    :func:`~reportlab_layout.pdf_elements`, or any text extractor, before sharing
    it.
    """
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str | Path):
        data = Path(source).read_bytes()
    else:
        data = source.read()
    pages = [pdf_page(data, index) for index in range(len(_reader(data).pages))]
    removed: list[PdfElement] = []

    def judge(element: PdfElement) -> bool:
        if keep(element):
            return True
        removed.append(element)
        return False

    with PDFMaker(output, pagesize=(pages[0].width, pages[0].height)) as doc:
        for page in pages:
            if page.index:
                doc.new_page()
            doc.canvas.setPageSize((page.width, page.height))
            doc.draw_pdf_page(page, 0, 0, keep=judge)
    return removed
