"""Une couche de mise en page à curseur au-dessus de reportlab.

Le canvas de reportlab dessine où on lui dit, en points, depuis le coin
bas-gauche. Ses ``platypus`` templates, à l'inverse, gèrent le flux mais
reprennent la main sur la page entière. Ce paquet occupe l'espace entre les
deux : un curseur qui descend dans la page, et le canvas resté accessible pour
tout ce qui doit être placé au point près.

    from reportlab_layout import PDFMaker

    with PDFMaker("bulletin.pdf", top=20) as doc:
        doc.draw_paragraph("Bulletin du 3e trimestre", "Heading1 Centered")
        doc.add_space()
        doc.draw_table([["Matière", "Note"], ["Maths", "17"]])
"""

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.cursor import Cursor
from reportlab_layout.document import PDFMaker
from reportlab_layout.frames import FrameWriter
from reportlab_layout.geometry import Margins, PageGeometry, resolve_pagesize
from reportlab_layout.images import ImageSpec, image_spec, load_image
from reportlab_layout.metrics import (
    TextMetrics,
    baseline_offset,
    cap_height,
    font_ascent,
    font_descent,
    font_height,
    string_width,
)
from reportlab_layout.numbering import NumberedCanvas
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.styles import STYLES, StyleLike, add_style, make_stylesheet, resolve_style
from reportlab_layout.text import TextPainter

__version__ = "1.0.0"

__all__ = [
    "STYLES",
    "Box",
    "ColorLike",
    "Cursor",
    "FrameWriter",
    "ImageSpec",
    "Margins",
    "NumberedCanvas",
    "PDFMaker",
    "PageGeometry",
    "ShapePainter",
    "StyleLike",
    "TextMetrics",
    "TextPainter",
    "__version__",
    "add_style",
    "baseline_offset",
    "cap_height",
    "font_ascent",
    "font_descent",
    "font_height",
    "image_spec",
    "load_image",
    "make_stylesheet",
    "resolve_pagesize",
    "resolve_style",
    "string_width",
    "to_color",
]
