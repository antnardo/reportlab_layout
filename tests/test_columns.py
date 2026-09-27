"""Columns: packing, balancing, and the flow from page to page."""

import logging

import pytest
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import CondPageBreak, FrameBreak, KeepTogether, Paragraph
from reportlab.platypus.flowables import Flowable

from reportlab_layout import PDFMaker, balanced_height, keep_with_next, pack_columns

STYLE = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12)


def lines(count, prefix="line"):
    """One-line paragraphs, easy to count and to find."""
    return [Paragraph(f"{prefix} {n}", STYLE) for n in range(count)]


def words(count):
    return [f"word{n}" for n in range(count)]


def long_paragraph(count=60):
    """A paragraph of ``count`` words, some 300 pt tall in a 100 pt column."""
    return Paragraph(" ".join(words(count)), STYLE)


def page_words(path):
    """The first word of every text line on each page, with its position."""
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        found = []

        def record(text, cm, tm, font_dict, font_size, found=found):
            if text.strip():
                found.append((text.strip(), tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5]))

        page.extract_text(visitor_text=record)
        pages.append(found)
    return pages


class Block(Flowable):
    """A flowable of a fixed size that refuses to split."""

    def __init__(self, width, height):
        super().__init__()
        self.width, self.height = width, height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        self.canv.rect(0, 0, self.width, self.height)


class Copying(Block):
    """A block that splits into a fresh copy of itself, as tall: taking that split never ends."""

    def __init__(self, width, height, generation=0):
        super().__init__(width, height)
        self.generation = generation

    def split(self, available_width, available_height):
        assert self.generation < 50, "the packer keeps splitting the copies"
        return [Copying(self.width, self.height, self.generation + 1)]


@pytest.fixture
def canvas(tmp_path):
    return Canvas(str(tmp_path / "scratch.pdf"))


class TestPackColumns:
    def test_first_column_filled_before_the_second(self, canvas):
        packing = pack_columns(canvas, lines(10), 100, 60, 2)
        assert [p.column for p in packing.placements] == [0] * 5 + [1] * 5
        assert packing.rest == ()

    def test_what_does_not_fit_is_left(self, canvas):
        packing = pack_columns(canvas, lines(12), 100, 60, 2)
        assert len(packing.placements) == 10
        assert len(packing.rest) == 2

    def test_long_paragraph_split_between_columns(self, canvas):
        packing = pack_columns(canvas, [long_paragraph()], 100, 60, 2)
        assert {p.column for p in packing.placements} == {0, 1}

    def test_frame_break_ends_the_column(self, canvas):
        packing = pack_columns(canvas, [*lines(2), FrameBreak(), *lines(2, "next")], 100, 60, 2)
        assert [p.column for p in packing.placements] == [0, 0, 1, 1]

    def test_keep_together_moves_to_the_next_column(self, canvas):
        story = [*lines(4), KeepTogether(lines(3, "kept"))]
        packing = pack_columns(canvas, story, 100, 60, 2)
        kept = [p for p in packing.placements if p.column == 1]
        assert kept and not packing.rest

    @pytest.mark.parametrize("overflow", [False, True])
    @pytest.mark.parametrize("before", [0, 2])
    def test_keep_together_around_one_flowable_lays_that_flowable(self, canvas, before, overflow):
        # Its split is that flowable alone: a single part, which up to 1.5.0 counted as no split.
        alone = Paragraph("alone", STYLE)
        story = [*lines(before), KeepTogether([alone])]
        packing = pack_columns(canvas, story, 100, 60, 2, overflow=overflow)
        assert packing.placements[-1].flowable is alone and packing.rest == ()

    @pytest.mark.parametrize("before", [0, 2])
    def test_empty_keep_together_is_dropped(self, canvas, before):
        story = [*lines(before), KeepTogether([]), *lines(2, "after")]
        packing = pack_columns(canvas, story, 100, 60, 2)
        assert [p.column for p in packing.placements] == [0] * (before + 2) and packing.rest == ()

    @pytest.mark.parametrize("after", [0, 1])
    def test_keep_together_too_tall_at_the_top_of_a_page_gives_way_to_its_flowables(self, canvas, after):
        # With overflow, the columns are as tall as the page: no column holds the group together.
        story = [KeepTogether([long_paragraph(), *lines(after, "after")])]
        packing = pack_columns(canvas, story, 100, 60, 2, overflow=True)
        assert [(p.column, type(p.flowable)) for p in packing.placements] == [(0, Paragraph), (1, Paragraph)]

    def test_keep_together_too_tall_waits_without_overflow(self, canvas):
        story = [KeepTogether([long_paragraph()])]
        packing = pack_columns(canvas, story, 100, 60, 2)
        assert packing.placements == () and packing.rest == tuple(story)

    @pytest.mark.parametrize("overflow", [False, True])
    def test_block_splitting_into_a_copy_of_itself_stays_whole(self, canvas, overflow):
        block = Copying(50, 200)
        packing = pack_columns(canvas, [block, *lines(2)], 100, 60, 2, overflow=overflow)
        kept = [p.flowable for p in packing.placements] + list(packing.rest)
        assert [flowable for flowable in kept if isinstance(flowable, Copying)] == [block]

    @pytest.mark.parametrize(("before", "columns"), [(2, [0, 0, 0, 0]), (3, [0, 0, 0, 1, 1])])
    def test_cond_page_break_ends_the_column_only_when_short_of_room(self, canvas, before, columns):
        # Out of a document template it takes what is left of the column, when that is too little.
        story = [*lines(before), CondPageBreak(30), *lines(2, "after")]
        packing = pack_columns(canvas, story, 100, 60, 2)
        assert [p.column for p in packing.placements if isinstance(p.flowable, Paragraph)] == columns

    def test_heading_kept_with_the_next_flowable(self, canvas):
        heading = ParagraphStyle("heading", parent=STYLE, keepWithNext=1)
        story = [*lines(4), Paragraph("Heading", heading), *lines(3, "after")]
        packing = pack_columns(canvas, story, 100, 60, 2)
        # Room for the heading at the foot of the first column, not for its text too.
        assert [p.column for p in packing.placements][:5] == [0, 0, 0, 0, 1]
        assert packing.placements[4].top == 0

    def test_group_taller_than_a_column_does_not_leave_it_empty(self, canvas):
        heading = ParagraphStyle("heading", parent=STYLE, keepWithNext=1)
        story = [Paragraph(f"heading {n}", heading) for n in range(8)] + lines(2)
        packing = pack_columns(canvas, story, 100, 60, 2)
        assert {p.column for p in packing.placements} == {0, 1}

    def test_space_before_dropped_at_the_top_of_a_column(self, canvas):
        story = [*lines(5), Paragraph("spaced", ParagraphStyle("s", parent=STYLE, spaceBefore=30))]
        packing = pack_columns(canvas, story, 100, 60, 2)
        spaced = packing.placements[-1]
        assert (spaced.column, spaced.top) == (1, pytest.approx(0))

    def test_unsplittable_block_taller_than_a_column_overflows_with_a_warning(self, canvas, caplog):
        with caplog.at_level(logging.WARNING, logger="reportlab_layout.columns"):
            packing = pack_columns(canvas, [Block(50, 200), *lines(2)], 100, 60, 2, overflow=True)
        assert "overflows" in caplog.text
        assert packing.placements[0].height == 200
        assert [p.column for p in packing.placements] == [0, 1, 1]

    def test_without_overflow_a_block_too_tall_waits(self, canvas):
        packing = pack_columns(canvas, [Block(50, 200), *lines(2)], 100, 60, 2)
        assert packing.placements == () and len(packing.rest) == 3


class TestKeepWithNext:
    def test_runs_bound_to_the_next_flowable(self):
        heading = ParagraphStyle("heading", parent=STYLE, keepWithNext=1)
        story = [Paragraph("a", heading), Paragraph("b", heading), *lines(2)]
        grouped = keep_with_next(story)
        assert [type(f).__name__ for f in grouped] == ["KeepTogether", "Paragraph"]

    def test_story_without_headings_unchanged(self):
        story = lines(3)
        assert keep_with_next(story) == story


class TestBalancedHeight:
    def test_columns_end_level(self, canvas):
        height = balanced_height(canvas, lines(10), 100, 500, 2)
        assert height == pytest.approx(60, abs=0.5)

    def test_headings_kept_with_their_text_still_balance(self, canvas):
        # KeepTogether reports a height of 16777215 to be split: the search must not add it up.
        heading = ParagraphStyle("heading", parent=STYLE, keepWithNext=1)
        story = []
        for part in range(3):
            story += [Paragraph(f"Part {part}", heading), *lines(5, f"part{part}")]
        height = balanced_height(canvas, story, 100, 500, 2)
        packing = pack_columns(canvas, story, 100, height, 2)
        bottoms = [max(p.bottom for p in packing.placements if p.column == c) for c in (0, 1)]
        assert height < 150 and abs(bottoms[0] - bottoms[1]) <= 2 * STYLE.leading

    def test_odd_count_leaves_the_longer_column_first(self, canvas):
        height = balanced_height(canvas, lines(9), 100, 500, 2)
        packing = pack_columns(canvas, lines(9), 100, height, 2)
        assert [p.column for p in packing.placements].count(0) == 5


class TestDrawColumns:
    def test_balanced_on_one_page_and_cursor_below(self, out):
        doc = PDFMaker(out)
        start = doc.cursor.depth
        box = doc.draw_columns(lines(10))
        doc.save()
        assert box.height == pytest.approx(60, abs=0.5)
        assert doc.cursor.depth == pytest.approx(start + box.height)
        [words] = page_words(out)
        xs = sorted({round(x) for _, x, _ in words})
        assert len(xs) == 2

    def test_unbalanced_fills_the_first_column(self, out):
        doc = PDFMaker(out)
        doc.draw_columns(lines(10), balance=False)
        doc.save()
        [words] = page_words(out)
        left = min(x for _, x, _ in words)
        assert sum(1 for _, x, _ in words if x == left) == 10

    def test_long_story_carries_on_over_pages(self, out):
        doc = PDFMaker(out)
        doc.set_header(Paragraph("Header", STYLE))
        doc.draw_columns(lines(300))
        doc.draw_paragraph("After the columns")
        doc.save()
        pages = page_words(out)
        assert len(pages) == 3
        assert all(any(word == "Header" for word, _, _ in page) for page in pages)
        found = [word for page in pages for word, _, _ in page if word.startswith("line")]
        assert found == [f"line {n}" for n in range(300)]

    def test_block_after_the_columns_starts_below_the_longest(self, out):
        doc = PDFMaker(out)
        box = doc.draw_columns(lines(9))
        after = doc.draw_paragraph("After the columns")
        doc.save()
        assert after.top == pytest.approx(box.y, abs=0.01)

    def test_no_room_left_starts_on_the_next_page(self, out):
        doc = PDFMaker(out)
        doc.advance(doc.remaining_height - 5)
        doc.draw_columns(lines(4))
        doc.save()
        pages = page_words(out)
        assert pages[0] == [] and len(pages[1]) == 4

    def test_keep_together_around_one_paragraph_is_drawn(self, out):
        doc = PDFMaker(out)
        doc.draw_columns([KeepTogether([Paragraph("alone", STYLE)])])
        doc.save()
        assert [word for word, _, _ in page_words(out)[0]] == ["alone"]

    @pytest.mark.parametrize("after", [[], ["after"]])
    def test_keep_together_taller_than_the_page_flows_over_pages(self, out, after):
        # 1.5.0 failed on the first, and laid the long paragraph of the second 6,000 pt tall.
        story = [KeepTogether([long_paragraph(800), *(Paragraph(word, STYLE) for word in after)])]
        doc = PDFMaker(out)
        doc.draw_columns(story)
        doc.save()
        pages = page_words(out)
        found = [word for page in pages for text, _, _ in page for word in text.split()]
        assert len(pages) > 1 and found == words(800) + after
        assert all(y > doc.y_bottom for page in pages for _, _, y in page)

    def test_three_columns(self, out):
        doc = PDFMaker(out)
        doc.draw_columns(lines(9), columns=3)
        doc.save()
        [words] = page_words(out)
        assert len({round(x) for _, x, _ in words}) == 3

    @pytest.mark.parametrize(("columns", "gap"), [(0, 4), (2, 500)])
    def test_impossible_columns_are_refused(self, out, columns, gap):
        with pytest.raises(ValueError):
            PDFMaker(out).draw_columns(lines(2), columns=columns, gap=gap)
