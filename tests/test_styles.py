"""Feuille de styles."""

import pytest
from reportlab.lib.enums import TA_CENTER

from reportlab_layout.styles import add_style, make_stylesheet, resolve_style


class TestMakeStylesheet:
    def test_provides_alignment_styles(self, stylesheet):
        for name in ("Left", "Right", "Centered", "Justify", "Small", "Footer"):
            assert name in stylesheet.byName

    def test_centered_heading_is_centered(self, stylesheet):
        assert stylesheet["Heading1 Centered"].alignment == TA_CENTER

    def test_each_call_returns_an_independent_sheet(self):
        first, second = make_stylesheet(), make_stylesheet()
        add_style(first, "Titre", fontSize=42)
        assert "Titre" not in second.byName


class TestAddStyle:
    def test_inherits_from_the_named_parent(self, stylesheet):
        style = add_style(stylesheet, "Titre", parent="Heading1", fontSize=30)
        assert style.fontName == stylesheet["Heading1"].fontName
        assert style.fontSize == 30

    def test_redefining_replaces_instead_of_raising(self, stylesheet):
        add_style(stylesheet, "Titre", fontSize=30)
        add_style(stylesheet, "Titre", fontSize=20)
        assert stylesheet["Titre"].fontSize == 20

    def test_replace_false_keeps_reportlab_behaviour(self, stylesheet):
        add_style(stylesheet, "Titre", fontSize=30)
        with pytest.raises(KeyError, match="déjà défini"):
            add_style(stylesheet, "Titre", fontSize=20, replace=False)


class TestResolveStyle:
    def test_none_gives_normal(self, stylesheet):
        assert resolve_style(None, stylesheet).name == "Normal"

    def test_name_is_looked_up(self, stylesheet):
        assert resolve_style("Right", stylesheet) is stylesheet["Right"]

    def test_style_object_passes_through(self, stylesheet):
        style = stylesheet["Small"]
        assert resolve_style(style, stylesheet) is style
