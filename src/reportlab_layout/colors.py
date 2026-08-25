"""Coercing colours into the type reportlab expects."""

from typing import TypeAlias

from reportlab.lib.colors import Color, HexColor, toColor

__all__ = ["ColorLike", "to_color"]

#: Anything that can name a colour in this package. ``None`` means "leave the
#: canvas colour alone".
ColorLike: TypeAlias = Color | str | tuple[float, ...] | list[float] | None


def to_color(value: ColorLike) -> Color | None:
    """Normalise a colour into a ``reportlab.lib.colors.Color``.

    Accepts a ``Color``, a CSS name or a ``"#rrggbb"`` string, and 3- or
    4-tuples of floats in ``[0, 1]``. ``None`` passes through: it means "do not
    touch the current colour".
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
        raise ValueError(f"A colour tuple needs 3 or 4 components, got {len(value)}")
    raise TypeError(f"Cannot convert to a colour: {value!r}")
