"""Paragraphs with inline images and a tag on their last line."""

from pathlib import Path

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from reportlab_layout import InlineParagraph, TaggedParagraph, inline_image

WIDTH = 200
TEXT = "The quick brown fox jumps over the lazy dog and runs far away into the woods"


class RecordingCanvas(Canvas):
    """A canvas that keeps the rectangle of every image drawn, in page coordinates."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.images = []

    def drawImage(self, image, x, y, width=None, height=None, **kwargs):  # noqa: N802 - reportlab's name
        a, b, c, d, e, f = self._currentMatrix
        self.images.append((a * x + c * y + e, b * x + d * y + f, width, height))
        return super().drawImage(image, x, y, width, height, **kwargs)


@pytest.fixture
def tall(tmp_path: Path) -> Path:
    path = tmp_path / "tall.png"
    PILImage.new("L", (20, 60), 0).save(path)
    return path


@pytest.fixture
def style() -> ParagraphStyle:
    return ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12, autoLeading="max")


def draw_at(paragraph, canvas, x=50, y=500):
    width, height = paragraph.wrap(WIDTH, 1000)
    paragraph.drawOn(canvas, x, y)
    return width, height


def baselines(path, index=0):
    """Map each piece of text to the canvas ordinate of its baseline."""
    found = {}

    def record(text, cm, tm, font_dict, font_size):
        if text.strip():
            found[text.strip()] = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]

    PdfReader(str(path)).pages[index].extract_text(visitor_text=record)
    return found


class TestInlineImage:
    def test_tag_carries_size_and_depth(self, tall):
        tag = inline_image(tall, width=8, height=24, depth=6)
        assert tag == f'<img src="{tall}" width="8.000" height="24.000" valign="-6.000"/>'

    def test_one_dimension_keeps_the_aspect(self, tall):
        assert 'height="30.000"' in inline_image(tall, width=10)

    def test_quotes_in_the_path_survive_the_markup(self, tmp_path, style, out):
        path = tmp_path / 'a"b.png'
        PILImage.new("L", (4, 4), 0).save(path)
        canvas = RecordingCanvas(str(out))
        draw_at(InlineParagraph(f"x {inline_image(path, width=4, height=4)} y", style), canvas)
        canvas.save()
        assert len(canvas.images) == 1

    def test_image_hangs_its_depth_below_the_baseline(self, tall, style, out):
        canvas = RecordingCanvas(str(out))
        paragraph = InlineParagraph(f"x {inline_image(tall, width=8, height=24, depth=6)} y", style)
        draw_at(paragraph, canvas)
        [(_, image_y, _, _)] = canvas.images
        canvas.save()
        assert image_y == pytest.approx(500 + paragraph.baselines()[0] - 6, abs=0.01)


class TestInlineParagraph:
    def test_tall_first_line_stays_inside_its_block(self, tall, style, out):
        canvas = RecordingCanvas(str(out))
        paragraph = InlineParagraph(f"Top {inline_image(tall, width=8, height=24, depth=6)} {TEXT}", style)
        _, height = draw_at(paragraph, canvas)
        [(_, image_y, _, image_height)] = canvas.images
        canvas.save()
        assert image_y + image_height <= 500 + height + 0.01

    def test_reportlab_alone_lets_it_stick_out(self, tall, style, out):
        # The defect InlineParagraph fixes: the first baseline ignores the line's height.
        canvas = RecordingCanvas(str(out))
        paragraph = Paragraph(f"Top {inline_image(tall, width=8, height=24, depth=6)} {TEXT}", style)
        _, height = draw_at(paragraph, canvas)
        [(_, image_y, _, image_height)] = canvas.images
        canvas.save()
        assert image_y + image_height > 500 + height + 5

    @pytest.mark.parametrize("markup", [TEXT, f"<b>Bold</b> {TEXT}"], ids=["plain", "markup"])
    def test_ordinary_paragraph_drawn_as_reportlab_draws_it(self, markup, style, tmp_path):
        paths = []
        for kind in (Paragraph, InlineParagraph):
            path = tmp_path / f"{kind.__name__}.pdf"
            canvas = Canvas(str(path))
            draw_at(kind(markup, style), canvas)
            canvas.save()
            paths.append(path)
        assert baselines(paths[0]) == baselines(paths[1])

    @pytest.mark.parametrize("auto", ["", "max", "min"])
    def test_baselines_are_those_drawn(self, auto, tall, out):
        style = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12, autoLeading=auto)
        image = inline_image(tall, width=8, height=24, depth=6)
        paragraph = InlineParagraph(f"alpha {image} beta<br/>gamma<br/>delta {image} epsilon", style)
        canvas = Canvas(str(out))
        draw_at(paragraph, canvas)
        canvas.save()
        drawn = baselines(out)
        expected = paragraph.baselines()
        for word, line in (("alpha", 0), ("gamma", 1), ("delta", 2)):
            found = next(y for text, y in drawn.items() if text.startswith(word))
            assert found == pytest.approx(500 + expected[line], abs=0.01)


class TestTaggedParagraph:
    def test_tag_on_the_last_line_when_there_is_room(self, style, out):
        plain = Paragraph("Short text", style)
        tagged = TaggedParagraph("Short text", style, tag="[2 pts]")
        canvas = Canvas(str(out))
        _, height = draw_at(tagged, canvas)
        canvas.save()
        assert height == plain.wrap(WIDTH, 1000)[1]
        drawn = baselines(out)
        assert drawn["[2 pts]"] == pytest.approx(drawn["Short text"], abs=0.01)

    def test_tag_flush_right(self, style, out):
        tagged = TaggedParagraph("Short text", style, tag="[2 pts]")
        canvas = Canvas(str(out))
        draw_at(tagged, canvas, x=50)
        canvas.save()
        text = PdfReader(str(out)).pages[0]
        right_edges = []

        def record(chars, cm, tm, font_dict, font_size):
            if chars.strip() == "[2 pts]":
                right_edges.append(tm[4] * cm[0] + cm[4])

        text.extract_text(visitor_text=record)
        assert right_edges[0] + stringWidth("[2 pts]", "Helvetica", 10) == pytest.approx(50 + WIDTH, abs=0.01)

    def test_tag_on_a_line_of_its_own_when_the_last_is_full(self, style, out):
        full = "x" * 38  # one line, nearly as wide as the column
        plain = Paragraph(full, style)
        tagged = TaggedParagraph(full, style, tag="[2 pts]")
        canvas = Canvas(str(out))
        _, height = draw_at(tagged, canvas)
        canvas.save()
        assert height == plain.wrap(WIDTH, 1000)[1] + style.leading
        drawn = baselines(out)
        assert drawn["[2 pts]"] == pytest.approx(drawn[full] - style.leading, abs=0.01)

    def test_tag_markup_and_style(self, style, out):
        small = ParagraphStyle("tag", fontName="Courier", fontSize=6)
        tagged = TaggedParagraph("Some text", style, tag="<b>APP</b>2", tag_style=small)
        canvas = Canvas(str(out))
        draw_at(tagged, canvas)
        canvas.save()
        assert "APP2" in PdfReader(str(out)).pages[0].extract_text().replace(" ", "")

    def test_without_tag_an_ordinary_paragraph(self, style):
        assert TaggedParagraph(TEXT, style).wrap(WIDTH, 1000) == Paragraph(TEXT, style).wrap(WIDTH, 1000)

    def test_split_hands_the_tag_to_the_last_part(self, style, out):
        tagged = TaggedParagraph(" ".join([TEXT] * 4), style, tag="[2 pts]")
        tagged.wrap(WIDTH, 1000)
        first, last = tagged.split(WIDTH, 40)
        canvas = Canvas(str(out))
        for part, y in ((first, 600), (last, 300)):
            part.wrap(WIDTH, 1000)
            part.drawOn(canvas, 50, y)
        canvas.save()
        assert PdfReader(str(out)).pages[0].extract_text().count("[2 pts]") == 1
        assert baselines(out)["[2 pts]"] < 400

    def test_bullet_and_tag_together(self, out):
        style = ParagraphStyle(
            "item",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            leftIndent=20,
            bulletIndent=16,
            bulletAnchor="end",
        )
        tagged = TaggedParagraph("<bullet>NE</bullet>Item text", style, tag="[1]")
        canvas = Canvas(str(out))
        draw_at(tagged, canvas)
        canvas.save()
        drawn = baselines(out)
        assert drawn["NE"] == pytest.approx(drawn["[1]"], abs=0.01)
