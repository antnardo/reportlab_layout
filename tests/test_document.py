"""Document à curseur : flux, placement absolu, pagination."""

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm

from reportlab_layout import Box, PDFMaker


def read(path):
    return PdfReader(str(path))


def page_text(path, index=0):
    return read(path).pages[index].extract_text()


class TestGeometryExport:
    def test_content_width_matches_the_margins(self, doc):
        assert doc.content_width == pytest.approx(doc.width - 30 * mm)

    def test_landscape_is_wider_than_tall(self, out, stylesheet):
        doc = PDFMaker(out, landscape=True, stylesheet=stylesheet)
        assert doc.width > doc.height

    def test_named_pagesize_is_accepted(self, out, stylesheet):
        assert (
            PDFMaker(out, pagesize="A5", stylesheet=stylesheet).width
            < PDFMaker(out, pagesize="A4", stylesheet=stylesheet).width
        )

    def test_exported_attributes_stay_writable(self, doc):
        """oraux/edt recalculent y_top en cours de route : ce doit rester possible."""
        doc.y_top = 123
        assert doc.y_top == 123


class TestFlow:
    def test_cursor_starts_at_the_top_margin(self, doc):
        assert doc.cursor.depth == pytest.approx(doc.top)

    def test_paragraph_moves_the_cursor_down(self, doc):
        before = doc.cursor.depth
        doc.draw_paragraph("Bonjour")
        assert doc.cursor.depth > before

    def test_successive_paragraphs_stack_downwards(self, doc):
        first = doc.draw_paragraph("Premier")
        second = doc.draw_paragraph("Second")
        assert second.y < first.y

    def test_add_space_advances_by_the_font_size(self, doc):
        before = doc.cursor.depth
        doc.add_space(2)
        assert doc.cursor.depth - before == pytest.approx(2 * doc.font_size)

    def test_explicit_depth_leaves_the_cursor_alone(self, doc):
        before = doc.cursor.depth
        doc.draw_paragraph("Ancré", y=100)
        assert doc.cursor.depth == before

    def test_draw_returns_a_box(self, doc):
        assert isinstance(doc.draw_paragraph("Bonjour"), Box)

    def test_box_unpacks_as_four_numbers(self, doc):
        _x, _y, width, height = doc.draw_paragraph("Bonjour")
        assert width > 0 and height > 0

    def test_halign_right_pushes_a_narrow_block_to_the_margin(self, doc):
        left = doc.draw_paragraph("Bonjour", wscale=0.5)
        right = doc.draw_paragraph("Bonjour", wscale=0.5, halign="right")
        assert right.x - left.x == pytest.approx(doc.content_width / 2)

    def test_unknown_halign_is_rejected(self, doc):
        with pytest.raises(ValueError, match="halign"):
            doc.draw_paragraph("Bonjour", halign="milieu")


class TestAbsolutePlacement:
    def test_absolute_coordinates_are_points(self, doc):
        box = doc.draw_paragraph("Bonjour", x=100, y=200, width=200, absolute=True)
        assert (box.x, box.y) == pytest.approx((100, 200))

    def test_valign_top_puts_the_top_edge_on_y(self, doc):
        box = doc.draw_paragraph("Bonjour", x=100, y=200, width=200, absolute=True, valign="top")
        assert box.top == pytest.approx(200)

    def test_valign_middle_centres_the_block(self, doc):
        box = doc.draw_paragraph("Bonjour", x=100, y=200, width=200, absolute=True, valign="middle")
        assert box.center[1] == pytest.approx(200)

    def test_absolute_without_coordinates_is_rejected(self, doc):
        with pytest.raises(ValueError, match="x et y explicites"):
            doc.draw_paragraph("Bonjour", absolute=True)


class TestPagination:
    def test_new_page_resets_the_cursor(self, doc):
        doc.draw_paragraph("Bonjour")
        doc.new_page()
        assert doc.cursor.depth == pytest.approx(doc.top)

    def test_new_page_increments_the_counter(self, doc):
        doc.new_page()
        assert doc.page == 2

    def test_auto_page_break_starts_a_second_page(self, out, stylesheet):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        for _ in range(80):
            doc.draw_paragraph("Une ligne parmi beaucoup d'autres.")
        doc.save()
        assert len(read(out).pages) > 1

    def test_page_break_false_keeps_everything_on_one_page(self, out, stylesheet):
        doc = PDFMaker(out, auto_page_break=True, stylesheet=stylesheet)
        for _ in range(80):
            doc.draw_paragraph("Une ligne parmi beaucoup d'autres.", page_break=False)
        doc.save()
        assert len(read(out).pages) == 1


class TestHeaderFooter:
    def test_footer_is_repeated_on_every_page(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer(doc.make_paragraph("Pied de page"))
        doc.draw_paragraph("Page une")
        doc.new_page()
        doc.draw_paragraph("Page deux")
        doc.save()
        assert "Pied de page" in page_text(out, 0)
        assert "Pied de page" in page_text(out, 1)

    def test_footer_accepts_several_flowables(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_footer([doc.make_paragraph("Gauche"), doc.make_paragraph("Droite")])
        doc.save()
        text = page_text(out)
        assert "Gauche" in text and "Droite" in text

    def test_footer_does_not_move_the_cursor(self, doc):
        doc.set_footer(doc.make_paragraph("Pied"))
        before = doc.cursor.depth
        doc.draw_header_footer()
        assert doc.cursor.depth == before


class TestTables:
    def test_default_columns_split_the_content_width(self, doc):
        box = doc.draw_table([["a", "b", "c"], ["1", "2", "3"]])
        assert box.width == pytest.approx(doc.content_width)

    def test_scalar_column_width_applies_to_every_column(self, doc):
        box = doc.draw_table([["a", "b"]], col_widths=60)
        assert box.width == pytest.approx(120)

    def test_extra_style_commands_are_applied(self, doc):
        """Une liste de commandes doit être acceptée telle quelle."""
        doc.draw_table(
            [["a", "b"]],
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.5, "black")],
        )
        doc.save()
        assert read(doc.canvas._filename).pages

    def test_empty_table_is_rejected(self, doc):
        with pytest.raises(ValueError, match="au moins une ligne"):
            doc.draw_table([])


class TestImages:
    def test_image_keeps_its_aspect_ratio(self, doc, picture):
        box = doc.draw_image(picture, width=80)
        assert box.height == pytest.approx(40)


class TestDirectDrawing:
    def test_draw_string_centres_at_any_scale(self, doc):
        box = doc.draw_string("Titre", 300, 400, halign="center", valign="middle", scale=0.6)
        assert box.center == pytest.approx((300, 400))

    def test_apply_style_arms_the_canvas_font(self, doc):
        metrics = doc.apply_style("Small", scale=2)
        assert doc.canvas._fontsize == pytest.approx(metrics.font_size)

    def test_rect_and_round_rect_return_their_box(self, doc):
        assert tuple(doc.draw_rect(0, 0, 10, 20)) == pytest.approx((0, 0, 10, 20))
        assert tuple(doc.draw_round_rect(0, 0, 10, 20)) == pytest.approx((0, 0, 10, 20))

    def test_centered_line_spans_the_content_width(self, doc):
        box = doc.draw_centered_line(y=50)
        assert box.width == pytest.approx(doc.content_width)

    def test_centered_line_can_be_narrowed(self, doc):
        box = doc.draw_centered_line(y=50, wscale=0.5)
        assert box.width == pytest.approx(doc.content_width / 2)


class TestFrames:
    def test_frame_paragraph_lands_in_the_pdf(self, doc):
        doc.new_frame(height=60)
        doc.frame_paragraph("Dans le cadre")
        doc.save()
        assert "Dans le cadre" in page_text(doc.canvas._filename)

    def test_overflow_is_reported_not_swallowed(self, doc):
        doc.new_frame(height=12)
        leftover = doc.draw_frame([doc.make_paragraph("Bonjour " * 200)])
        assert leftover

    def test_frame_before_new_frame_is_rejected(self, doc):
        with pytest.raises(RuntimeError, match="Aucun frame actif"):
            doc.frame_space()


class TestLifecycle:
    def test_context_manager_writes_the_file(self, out, stylesheet):
        with PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Bonjour")
        assert "Bonjour" in page_text(out)

    def test_context_manager_does_not_write_on_error(self, out, stylesheet):
        with pytest.raises(RuntimeError), PDFMaker(out, stylesheet=stylesheet) as doc:
            doc.draw_paragraph("Bonjour")
            raise RuntimeError("échec")
        assert not out.exists()

    def test_metadata_reaches_the_pdf(self, out, stylesheet):
        doc = PDFMaker(out, stylesheet=stylesheet)
        doc.set_metadata(author="A. Marchand", title="Essai")
        doc.draw_paragraph("Bonjour")
        doc.save()
        assert read(out).metadata.author == "A. Marchand"
