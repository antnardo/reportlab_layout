"""A marked copy: the corrector's marks are annotations, laid over the answer.

    uv run python examples/annotations.py

Writes ``annotations.pdf`` into the current directory. The answer is drawn on
the page; each mark -- the score, the ticks, a comment, a highlight, a sketch --
is an annotation drawn with the usual ``draw_*`` calls. A reader shows the marks
as drawn and prints them with the page; one with an annotation editor lets you
drag them aside or delete them, and leaves the answer underneath untouched.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.pdfbase.pdfmetrics import stringWidth

from reportlab_layout import Box, PDFMaker

RED = "#c62828"
GREEN = "#2e7d32"
HIGHLIGHT = (1.0, 0.85, 0.1, 0.4)  # a fourth component makes it see-through
ROUND = 1  # PDF line cap and line join: round
MARKER = "Marker"

ANSWER = [
    "1. The only force on the ball is its weight, so its acceleration is g, downwards.",
    "2. Energy is conserved: m g h = ½ m v², hence v² = 2 g h.",
    "3. With h = 10 m and g = 9.8 m/s², v = 14.",
    "4. The fall lasts t = v / g = 1.4 s.",
    "5. Dropped from twice as high, the ball lands twice as fast.",
]


def sketch() -> bytes:
    """The corrector's sketch of v against h, red on a transparent ground, as PNG."""
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.line([(20, 10), (20, 140), (230, 140)], fill=RED, width=4)  # axes
    curve = [(20 + x, 140 - int(9 * x**0.5)) for x in range(0, 205, 5)]
    pen.line(curve, fill=RED, width=5, joint="curve")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def tick(doc: PDFMaker, x: float, y: float) -> None:
    """A tick whose foot stands at ``(x, y)``."""
    with doc.annotation(x - 6, y - 4, 24, 20, contents="Correct", author=MARKER):
        points = [(x - 2, y + 5), (x + 3, y), (x + 14, y + 13)]
        doc.draw_polygon(points, close=False, stroke=GREEN, line_width=2.5, line_cap=ROUND, line_join=ROUND)


def comment(doc: PDFMaker, text: str, x: float, y: float, note: str) -> None:
    """A boxed remark whose lower-left corner is ``(x, y)``; ``note`` is what the reader lists."""
    width, height = stringWidth(text, "Helvetica", 11) + 10, 18
    with doc.annotation(x, y, width, height, contents=note, author=MARKER):
        # A stroke straddles its path: kept half a line width inside, it is not clipped.
        doc.draw_round_rect(
            x + 0.5, y + 0.5, width - 1, height - 1, radius=4, fill="white", stroke=RED, line_width=1
        )
        doc.draw_string(text, x + 5, y + height / 2, color=RED, valign="cap")


def highlight(doc: PDFMaker, line: Box, text: str, note: str) -> None:
    """A see-through band over the first line of a paragraph."""
    width = stringWidth(text, "Helvetica", 12) + 4
    x, y = line.x - 2, line.y + line.height - 15
    with doc.annotation(x, y, width, 15, contents=note, author=MARKER):
        doc.draw_rect(x, y, width, 15, fill=HIGHLIGHT, stroke=None)


def build(path: Path) -> Path:
    with PDFMaker(path, top=25, right=60) as doc:
        doc.set_metadata(author="Student 07", title="Exercise 2, marked")
        doc.draw_paragraph("Exercise 2 — A ball dropped from a balcony", "Heading2")
        doc.add_space(2)
        lines = []
        for text in ANSWER:
            lines.append(doc.draw_paragraph(text))
            doc.add_space(3)
        margin = doc.x_left + doc.content_width + 8

        with doc.annotation(margin, 760, 90, 40, contents="Mark: 14/20", author=MARKER):
            doc.draw_round_rect(
                margin + 1, 761, 88, 38, radius=6, fill=(1, 1, 1, 0.85), stroke=RED, line_width=2
            )
            doc.draw_string(
                "14/20", margin + 45, 780, color=RED, scale=2, halign="center", valign="cap", outline=0.6
            )

        tick(doc, margin, lines[0].y + 4)
        tick(doc, margin, lines[1].y + 4)
        tick(doc, margin, lines[3].y + 4)
        comment(doc, "unit?", margin, lines[2].y, note="The speed needs its unit: v = 14 m/s.")
        highlight(doc, lines[4], ANSWER[4], note="No: v grows as the square root of h.")

        below = lines[4].y - 75
        with doc.annotation(
            margin - 30, below, 130, 80, contents="v against h: a square root", author=MARKER
        ):
            doc.draw_image(sketch(), 90, 60, x=margin - 20, y=below + 20, absolute=True)
            doc.draw_string("v", margin - 26, below + 72, color=RED, valign="cap")
            doc.draw_string("h", margin + 70, below + 18, color=RED, valign="cap")
            doc.draw_string("× 1.4, not × 2", margin - 20, below + 4, color=RED)
    return path


if __name__ == "__main__":
    print(build(Path("annotations.pdf")).resolve())
