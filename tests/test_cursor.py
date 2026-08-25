"""The flow cursor."""

import pytest

from reportlab_layout.cursor import Cursor


@pytest.fixture
def cursor() -> Cursor:
    return Cursor(top=50, bottom_depth=800)


class TestCursor:
    def test_starts_at_the_top_margin(self, cursor):
        assert cursor.depth == 50

    def test_advance_moves_down(self, cursor):
        assert cursor.advance(120) == 170

    def test_reset_returns_to_the_top(self, cursor):
        cursor.advance(300)
        assert cursor.reset() == 50

    def test_remaining_shrinks_as_the_page_fills(self, cursor):
        cursor.advance(250)
        assert cursor.remaining == 500

    def test_fits_is_true_while_there_is_room(self, cursor):
        assert cursor.fits(700)

    def test_fits_is_false_past_the_bottom_margin(self, cursor):
        assert not cursor.fits(800)

    def test_depth_is_settable(self, cursor):
        cursor.depth = 400
        assert cursor.remaining == 400
