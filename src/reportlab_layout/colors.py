"""Conversion des couleurs vers le type attendu par reportlab."""

from typing import TypeAlias

from reportlab.lib.colors import Color, HexColor, toColor

__all__ = ["ColorLike", "to_color"]

#: Tout ce qui peut désigner une couleur dans ce paquet. ``None`` signifie
#: « conserver la couleur courante du canvas ».
ColorLike: TypeAlias = Color | str | tuple[float, ...] | list[float] | None


def to_color(value: ColorLike) -> Color | None:
    """Normalise une couleur en ``reportlab.lib.colors.Color``.

    Accepte un ``Color``, un nom CSS ou une chaîne ``"#rrggbb"``, un triplet ou
    quadruplet de flottants dans ``[0, 1]``. ``None`` est rendu tel quel : il
    signifie « ne pas toucher à la couleur courante ».
    """
    if value is None or isinstance(value, Color):
        return value
    if isinstance(value, str):
        return HexColor(value) if value.startswith("#") else toColor(value)
    if isinstance(value, tuple | list):
        if len(value) == 3:
            return Color(*value)
        if len(value) == 4:
            return Color(value[0], value[1], value[2], alpha=value[3])
        raise ValueError(f"Un tuple de couleur doit avoir 3 ou 4 composantes, reçu {len(value)}")
    raise TypeError(f"Couleur non convertible : {value!r}")
